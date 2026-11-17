"""Inquiries, calendar, staff attendance, leave, student photos and CSV exports (FR-77..81, FR-99, FR-78, FR-79)."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.sheets import csv_cell as _cell
from app.models import AuditLog
from app.services import calendar
from tests.helpers import F2_A, GUARDIAN_A, SCHOOL_A, SHARED_PHONE, as_school, bearer, login, parent_login, u
from tests.test_enrolment import application

API = "/api/v1"
GATE_JUMA = u(2, 6)
STAFF_ADMIN, STAFF_MWITA = u(8, 1), u(8, 3)
AMANI = u(6, 11)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


@pytest.fixture
async def teacher(client) -> dict:
    return bearer(await login(client, username="tch.mwita"))


async def receptionist(client, admin) -> dict:
    assert (
        await client.post(f"{API}/users/{GATE_JUMA}/roles", headers=admin, json={"role_code": "receptionist"})
    ).status_code == 201
    return bearer(await login(client, username="gate.juma"))


# ---------------------------------------------------------------- inquiries


async def test_front_desk_records_follows_up_and_converts_an_inquiry(client, admin, teacher):
    desk = await receptionist(client, admin)
    made = await client.post(
        f"{API}/inquiries",
        headers=desk,
        json={
            "full_name": "Neema Said",
            "phone": "0712 000 111",
            "source": "PHONE",
            "follow_up_on": (calendar.today() - timedelta(days=1)).isoformat(),
        },
    )
    assert made.status_code == 201, made.text
    inquiry = made.json()
    assert inquiry["phone"] == "255712000111" and inquiry["status"] == "OPEN"

    due = (await client.get(f"{API}/inquiries?due=true", headers=desk)).json()["items"]
    assert inquiry["id"] in [i["id"] for i in due]
    noted = await client.patch(
        f"{API}/inquiries/{inquiry['id']}", headers=desk, json={"notes": "Called back, will visit"}
    )
    assert noted.json()["notes"] == "Called back, will visit"

    converted = await client.post(
        f"{API}/inquiries/{inquiry['id']}/convert", headers=desk, json={"application": application()}
    )
    assert converted.status_code == 201, converted.text
    after = (await client.get(f"{API}/inquiries?status=CONVERTED", headers=desk)).json()["items"]
    assert after[0]["application_id"] == converted.json()["application_id"]
    again = await client.post(
        f"{API}/inquiries/{inquiry['id']}/convert", headers=desk, json={"application": application()}
    )
    assert again.status_code == 409
    closing = await client.patch(f"{API}/inquiries/{inquiry['id']}", headers=desk, json={"status": "CLOSED"})
    assert closing.status_code == 409  # a converted inquiry stays converted

    assert (await client.get(f"{API}/inquiries", headers=teacher)).status_code == 403


async def test_an_inquiry_needs_a_phone_or_an_email(client, admin):
    desk = await receptionist(client, admin)
    assert (await client.post(f"{API}/inquiries", headers=desk, json={"full_name": "No Contact"})).status_code == 422
    assert (
        await client.post(f"{API}/inquiries", headers=desk, json={"full_name": "Bad", "phone": "123"})
    ).status_code == 422


# ---------------------------------------------------------------- calendar


async def test_the_calendar_shows_each_audience_its_events(client, db, dispatcher, admin, teacher):
    day = (calendar.today() + timedelta(days=10)).isoformat()
    for title, audience in (("Staff meeting", "STAFF"), ("Parents day", "PARENTS"), ("Sports day", "ALL")):
        made = await client.post(
            f"{API}/events",
            headers=admin,
            json={"title_en": title, "title_sw": title, "starts_on": day, "ends_on": day, "audience": audience},
        )
        assert made.status_code == 201, made.text
    staff_view = {e["title_en"] for e in (await client.get(f"{API}/events", headers=teacher)).json()}
    assert {"Staff meeting", "Parents day", "Sports day"} <= staff_view
    parent = await parent_login(client, db, dispatcher, SCHOOL_A, GUARDIAN_A, SHARED_PHONE)
    parent_view = {e["title_en"] for e in (await client.get(f"{API}/events", headers=parent)).json()}
    assert "Parents day" in parent_view and "Sports day" in parent_view and "Staff meeting" not in parent_view
    bad = {"title_en": "Back", "title_sw": "Back", "starts_on": day, "ends_on": "2020-01-01"}
    assert (await client.post(f"{API}/events", headers=admin, json=bad)).status_code == 422
    assert (await client.post(f"{API}/events", headers=teacher, json={**bad, "ends_on": day})).status_code == 403


# ---------------------------------------------------------------- staff attendance and leave


async def test_staff_attendance_is_one_record_per_person_per_day(client, admin, teacher):
    today = calendar.today().isoformat()
    marks = {"marks": [{"staff_id": str(STAFF_MWITA), "status": "LATE", "time_in": "08:20"}]}
    assert (await client.put(f"{API}/staff-attendance?on={today}", headers=admin, json=marks)).status_code == 204
    marks["marks"][0]["status"] = "PRESENT"  # a correction updates the same record
    assert (await client.put(f"{API}/staff-attendance?on={today}", headers=admin, json=marks)).status_code == 204
    day = (await client.get(f"{API}/staff-attendance?on={today}", headers=admin)).json()
    mwita = next(r for r in day if r["staff_id"] == str(STAFF_MWITA))
    assert mwita["status"] == "PRESENT" and mwita["time_in"] == "08:20:00"
    month = (
        await client.get(f"{API}/staff-attendance/monthly?year={today[:4]}&month={int(today[5:7])}", headers=admin)
    ).json()
    assert next(r for r in month if r["staff_id"] == str(STAFF_MWITA))["present"] == 1

    tomorrow = (calendar.today() + timedelta(days=1)).isoformat()
    assert (await client.put(f"{API}/staff-attendance?on={tomorrow}", headers=admin, json=marks)).status_code == 422
    assert (await client.put(f"{API}/staff-attendance?on={today}", headers=teacher, json=marks)).status_code == 403


async def test_leave_limits_decisions_overlaps_and_cancelling(client, admin, teacher):
    annual = (
        await client.post(
            f"{API}/leave-types",
            headers=admin,
            json={"name_en": "Annual", "name_sw": "Ya mwaka", "applies_to": "STAFF", "days_per_year": 5},
        )
    ).json()
    other = (
        await client.post(
            f"{API}/leave-types",
            headers=admin,
            json={"name_en": "Compassionate", "name_sw": "Msiba", "applies_to": "STAFF"},
        )
    ).json()
    start = date(calendar.today().year, 12, 1)

    def ask(kind, first, days):
        return {
            "leave_type_id": kind["id"],
            "start_date": first.isoformat(),
            "end_date": (first + timedelta(days=days - 1)).isoformat(),
            "reason": "Family matters",
        }

    first = await client.post(f"{API}/leave-requests", headers=teacher, json=ask(annual, start, 3))
    assert first.status_code == 201, first.text
    over = await client.post(f"{API}/leave-requests", headers=teacher, json=ask(annual, start + timedelta(days=10), 3))
    assert over.status_code == 422 and over.json()["error_code"] == "LEAVE_DAYS_EXCEEDED"

    leave_id = first.json()["id"]
    assert (
        await client.post(f"{API}/leave-requests/{leave_id}/decide", headers=teacher, json={"approve": True})
    ).status_code == 403
    assert (
        await client.post(f"{API}/leave-requests/{leave_id}/decide", headers=admin, json={"approve": True})
    ).status_code == 204
    day = (await client.get(f"{API}/staff-attendance?on={start.isoformat()}", headers=admin)).json()
    assert next(r for r in day if r["staff_id"] == str(STAFF_MWITA))["on_leave"] is True

    overlapping = (
        await client.post(f"{API}/leave-requests", headers=teacher, json=ask(other, start + timedelta(days=2), 2))
    ).json()
    clash = await client.post(f"{API}/leave-requests/{overlapping['id']}/decide", headers=admin, json={"approve": True})
    assert clash.status_code == 409 and clash.json()["error_code"] == "LEAVE_OVERLAP"
    assert (await client.post(f"{API}/leave-requests/{overlapping['id']}/cancel", headers=admin)).status_code == 404
    assert (await client.post(f"{API}/leave-requests/{overlapping['id']}/cancel", headers=teacher)).status_code == 204

    mine = await client.post(f"{API}/leave-requests", headers=admin, json=ask(other, start + timedelta(days=20), 1))
    own = await client.post(f"{API}/leave-requests/{mine.json()['id']}/decide", headers=admin, json={"approve": True})
    assert own.status_code == 403  # nobody approves their own leave

    listed = (await client.get(f"{API}/leave-requests?scope=all", headers=admin)).json()
    assert {r["status"] for r in listed} >= {"APPROVED", "CANCELLED", "PENDING"}
    assert (await client.get(f"{API}/leave-requests?scope=all", headers=teacher)).status_code == 403


async def test_a_teacher_asks_leave_for_a_student(client, admin, teacher):
    sick = (
        await client.post(
            f"{API}/leave-types", headers=admin, json={"name_en": "Sick", "name_sw": "Ugonjwa", "applies_to": "STUDENT"}
        )
    ).json()
    staff_kind = (
        await client.post(
            f"{API}/leave-types", headers=admin, json={"name_en": "Study", "name_sw": "Masomo", "applies_to": "STAFF"}
        )
    ).json()
    body = {"student_id": str(AMANI), "start_date": "2026-11-02", "end_date": "2026-11-03", "reason": "Malaria"}
    assert (
        await client.post(f"{API}/leave-requests", headers=teacher, json={**body, "leave_type_id": sick["id"]})
    ).status_code == 201
    wrong = await client.post(
        f"{API}/leave-requests", headers=teacher, json={**body, "leave_type_id": staff_kind["id"]}
    )
    assert wrong.status_code == 422


# ---------------------------------------------------------------- photos


async def test_a_student_photo_is_set_shown_and_removed(client, admin, teacher):
    photo = (
        await client.post(f"{API}/files", headers=admin, data={"purpose": "PHOTO"}, files={"file": ("a.png", PNG)})
    ).json()
    assert (await client.get(f"{API}/students/{AMANI}/photo", headers=admin)).status_code == 404
    assert (
        await client.put(f"{API}/students/{AMANI}/photo", headers=admin, json={"file_id": photo["id"]})
    ).status_code == 204
    shown = await client.get(f"{API}/students/{AMANI}/photo", headers=teacher)
    assert shown.status_code == 200 and shown.content == PNG and shown.headers["content-type"] == "image/png"
    assert (
        await client.put(f"{API}/students/{AMANI}/photo", headers=teacher, json={"file_id": photo["id"]})
    ).status_code == 403
    assert (await client.delete(f"{API}/students/{AMANI}/photo", headers=admin)).status_code == 204
    assert (await client.get(f"{API}/students/{AMANI}/photo", headers=admin)).status_code == 404


async def test_only_photo_uploads_can_become_a_photo(client, admin):
    # school admins may upload certificate backgrounds too, but such a file is not a photograph
    background = await client.post(
        f"{API}/files", headers=admin, data={"purpose": "CERT_TEMPLATE"}, files={"file": ("bg.png", PNG)}
    )
    assert background.status_code == 201, background.text
    refused = await client.put(
        f"{API}/students/{AMANI}/photo", headers=admin, json={"file_id": background.json()["id"]}
    )
    assert refused.status_code == 422
    missing = await client.put(f"{API}/students/{AMANI}/photo", headers=admin, json={"file_id": str(u(99, 1))})
    assert missing.status_code == 404


# ---------------------------------------------------------------- exports


def test_csv_cells_never_start_a_formula():
    assert _cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and _cell("+255") == "'+255" and _cell("@x") == "'@x"
    assert _cell("Amani") == "Amani" and _cell(None) == "" and _cell(5) == "5"


async def test_lists_export_as_csv_without_sensitive_fields_and_are_audited(client, db, admin, teacher):
    students = await client.get(f"{API}/exports/students.csv", headers=admin)
    assert students.status_code == 200 and students.headers["content-type"].startswith("text/csv")
    text = students.content.decode("utf-8")
    assert text.startswith("﻿admission_no,name,gender,class,stream,status") and "MF-2025-0014" in text
    assert (await client.get(f"{API}/exports/students.csv", headers=teacher)).status_code == 403

    staff = (await client.get(f"{API}/exports/staff.csv", headers=admin)).content.decode()
    assert "MF-STF-003" in staff and "salary" not in staff and "phone" not in staff and "2400000" not in staff

    term = (await client.get(f"{API}/terms", headers=admin)).json()[0]["id"]
    assert (
        await client.get(
            f"{API}/exports/invoices.csv?term_id={term}", headers=bearer(await login(client, username="bursar"))
        )
    ).status_code == 200
    assert (await client.get(f"{API}/exports/invoices.csv?term_id={term}", headers=teacher)).status_code == 403

    sheet = await client.get(
        f"{API}/exports/attendance.csv?stream_id={F2_A}&from=2026-01-12&to=2026-03-31", headers=teacher
    )
    assert sheet.status_code == 200 and sheet.content.decode().splitlines()[0].endswith("rate_pct")

    await as_school(db, SCHOOL_A)
    exported = (await db.execute(select(AuditLog.entity_type).where(AuditLog.action == "EXPORT"))).scalars().all()
    assert {"students", "staff", "invoices", "attendance"} <= set(exported)
