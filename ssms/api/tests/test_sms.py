"""SMS providers over a mocked HTTP transport: payload shape, transient vs permanent failures, idempotent delivery."""

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import SmsMessage
from app.services import sms
from tests.helpers import SCHOOL_A, as_school


@pytest.fixture
def http(monkeypatch):
    """Route every httpx.AsyncClient created by app.services.sms to a handler set by the test."""
    state = {"requests": [], "reply": lambda request: httpx.Response(200, json={})}
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["reply"](request)

    monkeypatch.setattr(sms.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return state


@pytest.fixture
def provider(monkeypatch):
    def use(name: str):
        monkeypatch.setattr(get_settings(), "sms_provider", name)

    return use


async def _queued(db) -> SmsMessage:
    await as_school(db, SCHOOL_A)
    message = await sms.queue_sms(
        db, school_id=SCHOOL_A, phone="255754000021", body="Habari", language="sw", idempotency_key="test-sms-1"
    )
    await db.commit()
    return message


async def test_beem_payload_and_message_id(db, http, provider):
    provider("beem")
    http["reply"] = lambda r: httpx.Response(200, json={"request_id": 4711, "successful": True})
    message = await _queued(db)
    assert await sms.deliver(db, message.id, sender="MFANO-SS") == "sent"
    body = json.loads(http["requests"][0].content)
    assert body["source_addr"] == "MFANO-SS" and body["recipients"][0]["dest_addr"] == "255754000021"
    assert http["requests"][0].headers["authorization"].startswith("Basic ")
    stored = (await db.execute(select(SmsMessage).where(SmsMessage.id == message.id))).scalar_one()
    assert stored.status == "SENT" and stored.provider_message_id == "4711"


async def test_nextsms_payload(db, http, provider):
    provider("nextsms")
    http["reply"] = lambda r: httpx.Response(200, json={"messages": [{"messageId": "ns-1"}]})
    message = await _queued(db)
    assert await sms.deliver(db, message.id, sender="SSMS") == "sent"
    assert json.loads(http["requests"][0].content) == {"from": "SSMS", "to": "255754000021", "text": "Habari"}


async def test_provider_outage_is_retried_not_failed(db, http, provider):
    provider("beem")
    http["reply"] = lambda r: httpx.Response(503)
    message = await _queued(db)
    with pytest.raises(sms.TransientSmsError):
        await sms.deliver(db, message.id)
    http["reply"] = lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))
    with pytest.raises(sms.TransientSmsError):
        await sms.deliver(db, message.id)


async def test_rejected_message_is_failed_without_retry(db, http, provider):
    provider("nextsms")
    http["reply"] = lambda r: httpx.Response(400, json={"error": "bad sender"})
    message = await _queued(db)
    assert await sms.deliver(db, message.id) == "failed"
    assert await sms.deliver(db, message.id) == "skipped"
    stored = (await db.execute(select(SmsMessage.status, SmsMessage.error).where(SmsMessage.id == message.id))).one()
    assert stored.status == "FAILED" and stored.error == "HTTPStatusError"
