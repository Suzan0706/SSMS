"""Registers (offline sync, conflicts, ETag), reports and chronic absence, through the API as ssms_app."""

import uuid
from datetime import date, datetime, timedelta

import pytest

from app.services import calendar
from tests.helpers import F2_A, F5_PCM, SCHOOL_A, bearer, login, parent_login, u

API = "/api/v1"
TODAY = date(2026, 10, 21)  # a Wednesday in Term Two
AMANI, ZAWADI, BARAKA, REHEMA = (u(6, n) for n in (11, 12, 13, 14))
LYIMO, LYIMO_PHONE = u(2, 23), "255765000023"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(calendar, "today", lambda: TODAY)


@pytest.fixture
async def salma(client) -> dict:
    """Class teacher of Form II A (not a teacher of Form V PCM)."""
    return bearer(await login(client, username="tch.salma"))


def item(student, status="PRESENT", day=TODAY, at="07:45", stream=F2_A, record=None) -> dict:
    return {
        "client_record_id": str(record or uuid.uuid4()),
        "session_date": day.isoformat(),
        "stream_id": str(stream),
        "student_id": str(student),
        "status": status,
        "captured_at": f"{day.isoformat()}T{at}:00+03:00",
    }


async def sync(client, headers, *items) -> list[dict]:
    response = await client.post(f"{API}/attendance/sync", headers=headers, json={"items": list(items)})
    assert response.status_code == 200, response.text
    return response.json()["results"]


async def test_class_teacher_sees_her_streams_and_an_empty_register(client, salma):
    streams = (await client.get(f"{API}/attendance/my-streams", headers=salma)).json()
    assert streams[0] == {"stream_id": str(F2_A), "label": "F2 A", "class_teacher": True}
    assert str(F5_PCM) not in {s["stream_id"] for s in streams}

    register = await client.get(f"{API}/attendance/register?stream_id={F2_A}", headers=salma)
    body = register.json()
    assert body["session_id"] is None and body["school_day"] is True and body["session_date"] == TODAY.isoformat()
    assert [s["student_id"] for s in body["students"]] and all(s["status"] is None for s in body["students"])
    again = await client.get(
        f"{API}/attendance/register?stream_id={F2_A}", headers={**salma, "If-None-Match": register.headers["ETag"]}
    )
    assert again.status_code == 304
    weekend = (await client.get(f"{API}/attendance/register?stream_id={F2_A}&date=2026-10-24", headers=salma)).json()
    assert weekend["school_day"] is False and weekend["reason"] == "weekend"
    assert (await client.get(f"{API}/attendance/register?stream_id={F5_PCM}", headers=salma)).status_code == 200


async def test_sync_is_idempotent_and_later_edit_wins(client, salma):
    first = item(BARAKA, "ABSENT", at="07:40")
    results = await sync(client, salma, first, item(AMANI), item(ZAWADI), item(REHEMA, "LATE"))
    assert [r["result"] for r in results] == ["synced"] * 4
    assert (await sync(client, salma, first))[0]["result"] == "synced"  # same record sent again

    older = item(BARAKA, "PRESENT", at="07:30")  # another phone, marked earlier
    conflict = (await sync(client, salma, older))[0]
    assert conflict["result"] == "conflict" and conflict["server"]["status"] == "ABSENT"
    assert (await sync(client, salma, item(BARAKA, "LATE", at="08:05")))[0]["result"] == "synced"

    register = (await client.get(f"{API}/attendance/register?stream_id={F2_A}", headers=salma)).json()
    status = {s["student_id"]: s["status"] for s in register["students"]}
    assert status[str(BARAKA)] == "LATE" and status[str(REHEMA)] == "LATE"
    close = await client.post(f"{API}/attendance/sessions/{register['session_id']}/close", headers=salma)
    assert close.status_code == 204


async def test_sync_errors_per_item(client, salma):
    outsider = u(6, 15)  # Form II B
    results = await sync(
        client,
        salma,
        item(outsider),
        item(AMANI, stream=F5_PCM),
        item(AMANI, day=TODAY + timedelta(days=1)),
        item(AMANI, day=TODAY - timedelta(days=30)),
        item(AMANI, day=date(2026, 10, 18)),  # Sunday
        item(ZAWADI),
    )
    assert [(r["result"], r["code"]) for r in results] == [
        ("error", "not_enrolled"),
        ("error", "forbidden"),
        ("error", "future_date"),
        ("error", "too_old"),
        ("error", "not_school_day"),
        ("synced", None),
    ]
    bursar = bearer(await login(client, username="bursar"))
    response = await client.post(f"{API}/attendance/sync", headers=bursar, json={"items": [item(AMANI)]})
    assert response.status_code == 403


async def test_reports_chronic_and_who_may_see_a_student(client, db, dispatcher, salma):
    admin = bearer(await login(client))
    report = await client.get(f"{API}/attendance/reports?stream_id={F2_A}&from=2026-03-01&to=2026-03-07", headers=admin)
    body = report.json()
    assert body["register_days"] == 5
    baraka = next(r for r in body["rows"] if r["student_id"] == str(BARAKA))
    assert (baraka["absent"], baraka["present"], baraka["rate_pct"]) == (3, 2, 40.0)
    excel = await client.get(
        f"{API}/attendance/reports?stream_id={F2_A}&from=2026-03-01&to=2026-03-07&format=xlsx", headers=admin
    )
    assert excel.content[:2] == b"PK"
    bad = await client.get(f"{API}/attendance/reports?stream_id={F2_A}&from=2026-03-07&to=2026-03-01", headers=admin)
    assert bad.status_code == 422

    chronic = (await client.get(f"{API}/attendance/chronic?week=2026-03-04", headers=admin)).json()
    assert [(c["student_id"], c["days_absent"], c["stream_label"]) for c in chronic] == [(str(BARAKA), 3, "F2 A")]

    parent = await parent_login(client, db, dispatcher, SCHOOL_A, LYIMO, LYIMO_PHONE)
    days = await client.get(f"{API}/students/{BARAKA}/attendance?from=2026-03-01&to=2026-03-07", headers=parent)
    assert days.status_code == 200 and days.json()["absent"] == 3
    gate = {d["day"]: d["gate_in_at"] for d in days.json()["days"]}
    assert gate["2026-03-02"] is None  # Baraka did not pass the gate that day
    other = await client.get(f"{API}/students/{AMANI}/attendance?from=2026-03-01&to=2026-03-07", headers=parent)
    assert other.status_code == 403


# ---------------------------------------------------------------- devices, cards and gate taps

GATE_KEY = "demo-device-key-mfano-gate"  # seed: school A main gate reader
OTHER_SCHOOL_KEY = "demo-device-key-upendo-gate"


def tap(token, at="07:25", day=TODAY, record=None) -> dict:
    return {
        "token": token,
        "captured_at": f"{day.isoformat()}T{at}:00+03:00",
        "client_record_id": str(record or uuid.uuid4()),
    }


async def send_taps(client, key, *taps):
    return await client.post(f"{API}/devices/taps", headers={"X-Device-Key": key}, json={"taps": list(taps)})


async def test_gate_taps_mark_present_late_duplicate_and_unknown(client, salma, monkeypatch):
    first = tap("card-11", "07:25")
    response = await send_taps(
        client,
        GATE_KEY,
        first,
        tap("card-11", "07:40"),
        tap("card-12", "08:45"),  # after the 08:30 cut-off
        tap("no-such-card"),
        tap("card-13", day=date(2026, 10, 18)),  # Sunday
        tap("card-14", day=TODAY - timedelta(days=30)),
    )
    assert response.status_code == 200, response.text
    assert [(r["result"], r["student_name"]) for r in response.json()["results"]] == [
        ("present", "Amani Massawe"),
        ("duplicate", "Amani Massawe"),
        ("late", "Zawadi Hassan"),
        ("unknown_card", None),
        ("not_school_day", None),
        ("out_of_window", None),
    ]
    assert (await send_taps(client, GATE_KEY, first)).json()["results"][0]["result"] == "duplicate"
    assert (await send_taps(client, "wrong-key", tap("card-11"))).status_code == 401

    # School B's device cannot reach school A's cards: the key routes to its own school (whose only term is over,
    # so the school-day check is bypassed here to reach the card lookup).
    async def open_day(session, day):
        return None

    monkeypatch.setattr(calendar, "closed_reason", open_day)
    assert (await send_taps(client, OTHER_SCHOOL_KEY, tap("card-15"))).json()["results"][0]["result"] == "unknown_card"

    register = (await client.get(f"{API}/attendance/register?stream_id={F2_A}", headers=salma)).json()
    gate = {s["student_id"]: s["gate_in_at"] for s in register["students"]}
    arrived = datetime.fromisoformat(gate[str(AMANI)]).astimezone(calendar.EAT)  # same moment in any zone
    assert arrived.isoformat().startswith("2026-10-21T07:25") and gate[str(BARAKA)] is None


async def test_devices_and_cards(client):
    gatekeeper = bearer(await login(client, username="gate.juma"))
    created = await client.post(
        f"{API}/devices", headers=gatekeeper, json={"name": "Back gate", "kind": "QR_SCANNER", "location": "Back"}
    )
    assert created.status_code == 201
    device = created.json()
    key = device.pop("api_key")
    assert key.startswith("ssmsdev_") and "api_key" not in (await client.get(f"{API}/devices", headers=gatekeeper)).text

    card = await client.post(
        f"{API}/rfid-cards", headers=gatekeeper, json={"student_id": str(BARAKA), "kind": "QR", "token": "QR-BARAKA-1"}
    )
    assert card.status_code == 201
    result = (await send_taps(client, key, tap("QR-BARAKA-1"))).json()["results"][0]
    assert result == {
        "client_record_id": result["client_record_id"],
        "result": "present",
        "student_name": "Baraka Lyimo",
    }

    replacement = await client.post(
        f"{API}/rfid-cards", headers=gatekeeper, json={"student_id": str(BARAKA), "kind": "QR", "token": "QR-BARAKA-2"}
    )
    cards = [
        c
        for c in (await client.get(f"{API}/rfid-cards?student_id={BARAKA}", headers=gatekeeper)).json()
        if c["kind"] == "QR"
    ]
    assert {(c["id"], c["status"]) for c in cards} == {
        (card.json()["id"], "REVOKED"),
        (replacement.json()["id"], "ACTIVE"),
    }
    in_use = await client.post(
        f"{API}/rfid-cards", headers=gatekeeper, json={"student_id": str(AMANI), "kind": "QR", "token": "QR-BARAKA-2"}
    )
    assert in_use.status_code == 409 and in_use.json()["details"][0]["code"] == "card_in_use"
    lost = await client.patch(
        f"{API}/rfid-cards/{replacement.json()['id']}", headers=gatekeeper, json={"status": "LOST"}
    )
    assert lost.json()["status"] == "LOST"
    later = tap("QR-BARAKA-2", day=TODAY - timedelta(days=1))
    assert (await send_taps(client, key, later)).json()["results"][0]["result"] == "unknown_card"

    disabled = await client.patch(f"{API}/devices/{device['id']}", headers=gatekeeper, json={"status": "DISABLED"})
    assert disabled.json()["status"] == "DISABLED"
    assert (await send_taps(client, key, tap("card-11"))).status_code == 401
    rotated = (await client.post(f"{API}/devices/{device['id']}/rotate-key", headers=gatekeeper)).json()
    assert rotated["api_key"] != key

    teacher = bearer(await login(client, username="tch.salma"))
    assert (await client.get(f"{API}/devices", headers=teacher)).status_code == 403
