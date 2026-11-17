"""SMS credit (debit, skip, essential, refund, low-credit notice), delivery reports and absence alerts."""

import uuid
from datetime import date

import pytest
from sqlalchemy import select, text

from app.core.config import get_settings
from app.models import AbsenceAlert, Notification, SmsCreditTransaction, SmsMessage
from app.models.enums import CreditKind
from app.services import alerts, calendar, sms
from app.tasks import handlers
from tests.helpers import ADMIN_B, SCHOOL_A, SCHOOL_B, as_school, bearer, login, rekey_phone, u

API = "/api/v1"
TODAY = date(2026, 10, 21)
AMANI, BARAKA, JUMA, MARIAM, EMMANUEL = (u(6, n) for n in (11, 13, 15, 16, 17))
LYIMO, LYIMO_PHONE = u(2, 23), "255765000023"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(calendar, "today", lambda: TODAY)


async def balance(db, school) -> int:
    await as_school(db, school)
    return await sms.credits_left(db, school)


async def queue(db, school, template_key="results_ready", body="Habari", key=None) -> SmsMessage:
    await as_school(db, school)
    message = await sms.queue_sms(
        db,
        school_id=school,
        phone="255700000001",
        body=body,
        language="sw",
        idempotency_key=key or f"test:{uuid.uuid4().hex}",
        template_key=template_key,
    )
    await db.commit()
    return message


async def test_credit_debit_skip_and_essential(db):
    before = await balance(db, SCHOOL_A)
    message = await queue(db, SCHOOL_A, body="x" * 200)  # two segments
    assert message.status == "QUEUED" and message.cost_credits == 2
    assert await balance(db, SCHOOL_A) == before - 2

    assert await balance(db, SCHOOL_B) == 0  # the seed gives school B no credit
    skipped = await queue(db, SCHOOL_B)
    assert (skipped.status, skipped.error, skipped.cost_credits) == ("SKIPPED", "no_credit", 0)
    assert await handlers.sms_send(str(skipped.id), str(SCHOOL_B)) == "skipped"
    login_code = await queue(db, SCHOOL_B, template_key="otp_login")
    assert login_code.status == "QUEUED"  # sign-in codes are never blocked
    assert await balance(db, SCHOOL_B) == -1


async def test_low_credit_notice_and_refund_on_permanent_failure(db, monkeypatch):
    await as_school(db, SCHOOL_B)
    db.add(SmsCreditTransaction(school_id=SCHOOL_B, kind=CreditKind.TOPUP, credits=101))
    await db.commit()
    message = await queue(db, SCHOOL_B, body="y" * 200)
    notices = (await db.execute(select(Notification).where(Notification.kind == "LOW_SMS_CREDIT"))).scalars().all()
    assert [n.user_id for n in notices] == [ADMIN_B] and "99" in notices[0].body
    await queue(db, SCHOOL_B)
    assert len((await db.execute(select(Notification).where(Notification.kind == "LOW_SMS_CREDIT"))).all()) == 1

    class Refusing:
        async def send(self, phone, text, sender):
            raise ValueError("400 invalid number")

    monkeypatch.setattr(sms, "get_provider", Refusing)
    assert await handlers.sms_send(str(message.id), str(SCHOOL_B)) == "failed"
    await as_school(db, SCHOOL_B)
    refund = (await db.execute(select(SmsCreditTransaction).where(SmsCreditTransaction.kind == "REFUND"))).scalar_one()
    assert refund.credits == 2 and refund.note == f"refund:{message.id}"
    assert await sms.credits_left(db, SCHOOL_B) == 100
    with pytest.raises(Exception, match="permission denied"):
        await db.execute(text("UPDATE sms_credit_transactions SET credits = 1"))


async def test_delivery_reports(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "sms_webhook_secret", "s" * 40)
    message = await queue(db, SCHOOL_A)
    assert await handlers.sms_send(str(message.id), str(SCHOOL_A)) == "sent"
    await as_school(db, SCHOOL_A)
    sent = (await db.execute(select(SmsMessage).where(SmsMessage.id == message.id))).scalar_one()
    await db.refresh(sent)
    url = f"{API}/webhooks/sms/console?token={'s' * 40}"
    assert (await client.post(f"{API}/webhooks/sms/console?token=wrong", json={})).status_code == 401
    report = {"results": [{"messageId": sent.provider_message_id, "status": {"groupName": "DELIVERED"}}, {"id": "x"}]}
    assert (await client.post(url, json=report)).status_code == 204
    await db.refresh(sent)
    assert sent.status == "DELIVERED" and sent.delivered_at is not None
    assert (
        await client.post(url, json={"request_id": sent.provider_message_id, "status": "FAILED"})
    ).status_code == 204
    await db.refresh(sent)
    assert sent.status == "DELIVERED"  # a later report never undoes delivery


async def test_absence_alerts(client, db, dispatcher):
    await rekey_phone(db, SCHOOL_A, LYIMO, LYIMO_PHONE)  # Baraka's and Emmanuel's father
    salma = bearer(await login(client, username="tch.salma"))
    items = [
        {
            "client_record_id": str(uuid.uuid4()),
            "session_date": TODAY.isoformat(),
            "stream_id": str(u(19, 2)),
            "student_id": str(student),
            "status": status,
            "captured_at": "2026-10-21T07:45:00+03:00",
        }
        for student, status in ((AMANI, "PRESENT"), (BARAKA, "ABSENT"), (u(6, 12), "EXCUSED"), (u(6, 14), "LATE"))
    ]
    assert (await client.post(f"{API}/attendance/sync", headers=salma, json={"items": items})).status_code == 200

    async def run(at: str) -> str:
        return await alerts.run(str(SCHOOL_A), TODAY.isoformat(), f"2026-10-21T{at}:00+03:00")

    assert await run("08:00") == "0 absence alerts"  # before the 08:30 cut-off
    assert await run("08:35") == "1 absence alerts"  # gate not used yet: only the register counts
    calls = dispatcher.take("sms.send")
    await as_school(db, SCHOOL_A)
    message = (await db.execute(select(SmsMessage).where(SmsMessage.id == uuid.UUID(calls[0]["sms_id"])))).scalar_one()
    assert message.template_key == "absence_alert" and "Baraka Lyimo" in message.body and "21/10/2026" in message.body

    taps = [{"token": "card-15", "captured_at": "2026-10-21T07:20:00+03:00", "client_record_id": str(uuid.uuid4())}]
    gate = await client.post(
        f"{API}/devices/taps", headers={"X-Device-Key": "demo-device-key-mfano-gate"}, json={"taps": taps}
    )
    assert gate.json()["results"][0]["result"] == "present"
    assert await run("08:40") == "1 absence alerts"  # Emmanuel (no register, no tap); Mariam's guardian has no phone
    assert await run("08:45") == "0 absence alerts"  # never twice
    await as_school(db, SCHOOL_A)
    alerted = set(
        (await db.execute(select(AbsenceAlert.student_id).where(AbsenceAlert.absence_date == TODAY))).scalars()
    )
    assert alerted == {BARAKA, EMMANUEL, MARIAM}
    assert await run("12:30") == "0 absence alerts"  # after the alert window
