"""Discipline, clubs, library and health records through the API, as ssms_app."""

from datetime import date

import pytest
from sqlalchemy import select

from app.models import AuditLog, SmsMessage
from app.services import calendar
from tests.helpers import SCHOOL_A, as_school, bearer, login, rekey_phone, u

API = "/api/v1"
TODAY = date(2026, 10, 21)
AMANI, ZAWADI, BARAKA, REHEMA = (u(6, n) for n in (11, 12, 13, 14))
LYIMO, LYIMO_PHONE = u(2, 23), "255765000023"  # Baraka's father
MASSAWE, MASSAWE_PHONE = u(2, 21), "255754000021"  # Amani's father
DEBATE, BOOK = u(51, 1), u(52, 1)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(calendar, "today", lambda: TODAY)


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


@pytest.fixture
async def salma(client) -> dict:
    return bearer(await login(client, username="tch.salma"))  # teacher, patron of the Debate club


async def test_discipline_record_notifies_parent_and_resolves(client, db, dispatcher, admin, salma):
    await rekey_phone(db, SCHOOL_A, LYIMO, LYIMO_PHONE)
    body = {
        "student_id": str(BARAKA),
        "incident_date": "2026-10-20",
        "category": "FIGHTING",
        "description": "Alipigana na mwenzake.",
    }
    created = await client.post(f"{API}/discipline-records", headers=salma, json=body)
    assert created.status_code == 201, created.text
    record = created.json()
    assert (
        record["status"] == "OPEN" and record["parent_notified_at"] and record["recorded_by_name"] == "Salma Abdallah"
    )
    await as_school(db, SCHOOL_A)
    message = (await db.execute(select(SmsMessage).where(SmsMessage.related_id == record["id"]))).scalar_one()
    assert (
        message.template_key == "discipline_notice" and "Baraka Lyimo" in message.body and "20/10/2026" in message.body
    )
    assert dispatcher.take("sms.send")
    quiet = await client.post(f"{API}/discipline-records", headers=salma, json={**body, "notify_parent": False})
    assert quiet.json()["parent_notified_at"] is None

    url = f"{API}/discipline-records/{record['id']}"
    assert (await client.patch(url, headers=salma, json={"resolve": True})).json()["details"][0]["code"] == "required"
    mwita = bearer(await login(client, username="tch.mwita"))
    assert (await client.patch(url, headers=mwita, json={"action_taken": "x"})).status_code == 403  # not the recorder
    resolved = await client.patch(
        url, headers=salma, json={"action_taken": "Ushauri", "resolution": "Wamepatana", "resolve": True}
    )
    assert resolved.json()["status"] == "RESOLVED"
    assert (await client.patch(url, headers=admin, json={"action_taken": "y"})).status_code == 409
    history = (await client.get(f"{API}/discipline-records?student_id={BARAKA}", headers=salma)).json()
    assert len(history) == 2
    bursar = bearer(await login(client, username="bursar"))
    assert (await client.get(f"{API}/discipline-records", headers=bursar)).status_code == 403


async def test_clubs_patron_manages_members(client, admin, salma):
    listed = {a["name"]: a for a in (await client.get(f"{API}/activities", headers=salma)).json()}
    debate = listed["Debate Club / Klabu ya Mdahalo"]
    assert debate["members"] == 2 and debate["patron_name"] == "Salma Abdallah"
    members = (await client.get(f"{API}/activities/{DEBATE}/members", headers=salma)).json()
    assert {(m["student_id"], m["role"]) for m in members} == {(str(ZAWADI), "SECRETARY"), (str(AMANI), "MEMBER")}
    added = await client.post(f"{API}/activities/{DEBATE}/members", headers=salma, json={"student_id": str(BARAKA)})
    assert added.status_code == 201
    assert (
        await client.post(f"{API}/activities/{DEBATE}/members", headers=salma, json={"student_id": str(BARAKA)})
    ).status_code == 409
    mwita = bearer(await login(client, username="tch.mwita"))
    assert (
        await client.post(f"{API}/activities/{DEBATE}/members", headers=mwita, json={"student_id": str(REHEMA)})
    ).status_code == 403
    assert (
        await client.post(f"{API}/activities", headers=salma, json={"name": "Football", "kind": "SPORT"})
    ).status_code == 403
    football = await client.post(
        f"{API}/activities",
        headers=admin,
        json={"name": "Football", "kind": "SPORT", "patron_staff_id": str(u(8, 3)), "meeting_day": 5},
    )
    assert football.status_code == 201 and football.json()["patron_name"] == "Daudi Mwita"
    assert (
        await client.post(
            f"{API}/activities/{football.json()['id']}/members",
            headers=mwita,
            json={"student_id": str(AMANI), "role": "CAPTAIN"},
        )
    ).status_code == 201

    amani = bearer(await login(client, username="mf-2025-0014"))
    mine = (await client.get(f"{API}/me/activities", headers=amani)).json()
    assert {(m["activity_name"], m["role"]) for m in mine} == {
        ("Debate Club / Klabu ya Mdahalo", "MEMBER"),
        ("Football", "CAPTAIN"),
    }
    assert (await client.delete(f"{API}/activity-members/{added.json()['id']}", headers=salma)).status_code == 204
    assert (await client.get(f"{API}/activities", headers=salma)).json()[0]["members"] == 2  # Zawadi and Amani


async def test_library_loans_copies_and_overdue_reminders(client, db, dispatcher, admin):
    await rekey_phone(db, SCHOOL_A, MASSAWE, MASSAWE_PHONE)
    book = (await client.get(f"{API}/library/books?q=Mathematics", headers=admin)).json()[0]
    assert (book["copies"], book["on_loan"], book["available"]) == (3, 1, 2)
    first = await client.post(
        f"{API}/library/loans", headers=admin, json={"book_id": str(BOOK), "admission_no": "mf-2025-0031"}
    )
    assert (
        first.status_code == 201
        and first.json()["borrower_name"] == "Baraka Joseph Lyimo"
        and first.json()["due_date"] == "2026-11-04"
    )
    assert (
        await client.post(
            f"{API}/library/loans", headers=admin, json={"book_id": str(BOOK), "borrower_user_id": str(u(2, 4))}
        )
    ).status_code == 201
    none_left = await client.post(
        f"{API}/library/loans", headers=admin, json={"book_id": str(BOOK), "admission_no": "MF-2025-0035"}
    )
    assert none_left.status_code == 422 and none_left.json()["details"][0]["code"] == "no_copies"
    assert (await client.patch(f"{API}/library/books/{BOOK}", headers=admin, json={"copies": 2})).status_code == 422
    returned = await client.post(f"{API}/library/loans/{first.json()['id']}/return", headers=admin)
    assert returned.json()["returned_at"]
    assert (
        await client.post(
            f"{API}/library/loans", headers=admin, json={"book_id": str(BOOK), "admission_no": "MF-2025-0035"}
        )
    ).status_code == 201

    overdue = (await client.get(f"{API}/library/loans?overdue=true", headers=admin)).json()
    assert [(o["borrower_user_id"], o["overdue"]) for o in overdue] == [(str(u(2, 11)), True)]  # Amani, due 16/03
    assert (await client.post(f"{API}/library/reminders/run", headers=admin)).json() == {"queued": 1}
    assert (await client.post(f"{API}/library/reminders/run", headers=admin)).json() == {"queued": 0}  # once a week
    await as_school(db, SCHOOL_A)
    message = (await db.execute(select(SmsMessage).where(SmsMessage.template_key == "library_overdue"))).scalar_one()
    assert message.to_user_id == MASSAWE and "16/03/2026" in message.body

    amani = bearer(await login(client, username="mf-2025-0014"))
    assert [loan["title"] for loan in (await client.get(f"{API}/me/loans", headers=amani)).json()] == [book["title"]]
    assert (await client.post(f"{API}/library/loans", headers=amani, json={"book_id": str(BOOK)})).status_code == 403


async def test_health_records_need_consent_and_are_audited(client, db, admin):
    url = f"{API}/students/{REHEMA}/health-records"
    seeded = (await client.get(url, headers=admin)).json()
    assert [(r["kind"], r["notes"]) for r in seeded] == [("ALLERGY", None)]  # seed text is not real ciphertext
    added = await client.post(
        url, headers=admin, json={"record_date": "2026-10-20", "kind": "CLINIC_VISIT", "notes": "Homa; amepewa dawa"}
    )
    assert added.status_code == 201 and added.json()["notes"] == "Homa; amepewa dawa"
    again = (await client.get(url, headers=admin)).json()
    assert again[0]["notes"] == "Homa; amepewa dawa" and len(again) == 2
    await as_school(db, SCHOOL_A)
    views = (
        (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "VIEW_SENSITIVE", AuditLog.entity_type == "health_records")
            )
        )
        .scalars()
        .all()
    )
    assert len(views) == 2
    no_consent = await client.get(f"{API}/students/{BARAKA}/health-records", headers=admin)
    assert no_consent.status_code == 403 and no_consent.json()["details"][0]["code"] == "no_consent"
    salma = bearer(await login(client, username="tch.salma"))
    assert (await client.get(url, headers=salma)).status_code == 403
