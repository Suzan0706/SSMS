"""Reports (preview + export), dashboards, compliance exports and data-subject requests, as ssms_app."""

import io
import json
import uuid
from datetime import date, datetime, timedelta

import pytest
from openpyxl import load_workbook
from sqlalchemy import select, update

from app.models import AuditLog, ConsentRecord, DataSubjectRequest, Guardian, User
from app.services import calendar, compliance, dashboards, reports
from tests.helpers import F2, F2_A, SCHOOL_A, TERM1, YEAR_2026, as_school, bearer, login, u

API = "/api/v1"
BARAKA_USER, MOLLEL_USER, SALMA_USER = u(2, 13), u(2, 27), u(2, 4)


@pytest.fixture(autouse=True)
def seeded_day(monkeypatch):
    monkeypatch.setattr(calendar, "today", lambda: date(2026, 3, 2))  # registers and gate taps in the seed
    dashboards.clear_cache()


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


async def test_report_previews_and_permissions(client, admin):
    enrolment = (await client.get(f"{API}/reports/enrolment", headers=admin)).json()
    assert enrolment["total"] == 7 and enrolment["columns"][:3] == ["admission_no", "name", "sex"]
    assert (await client.get(f"{API}/reports/enrolment?class_id={F2}", headers=admin)).json()["total"] == 6
    assert (await client.get(f"{API}/reports/enrolment?stream_id={F2_A}", headers=admin)).json()["total"] == 4

    attendance = (
        await client.get(
            f"{API}/reports/attendance?stream_id={F2_A}&date_from=2026-03-01&date_to=2026-03-07", headers=admin
        )
    ).json()
    baraka = next(r for r in attendance["rows"] if r["admission_no"] == "MF-2025-0031")
    assert (baraka["absent"], baraka["rate_pct"]) == ("3", "40.00")
    results = (await client.get(f"{API}/reports/results?term_id={TERM1}&class_id={F2}", headers=admin)).json()
    assert results["total"] == 6 and results["rows"][0]["position"] == "1"
    assert (await client.get(f"{API}/reports/results", headers=admin)).status_code == 422
    fees = (await client.get(f"{API}/reports/fees?term_id={TERM1}", headers=admin)).json()
    assert fees["total"] == 7 and all("." in r["invoiced_tzs"] for r in fees["rows"])
    money = (
        await client.get(f"{API}/reports/transactions?date_from=2026-01-01&date_to=2026-10-21", headers=admin)
    ).json()
    assert money["total"] >= 1 and money["rows"][0]["amount_tzs"].endswith(".00")
    assert (await client.get(f"{API}/reports/staff", headers=admin)).json()["total"] >= 6
    assert (
        await client.get(f"{API}/reports/enrolment?date_from=2026-05-01&date_to=2026-01-01", headers=admin)
    ).status_code == 422

    teacher = bearer(await login(client, username="tch.salma"))
    assert (await client.get(f"{API}/reports/enrolment", headers=teacher)).status_code == 200
    assert (await client.get(f"{API}/reports/fees", headers=teacher)).status_code == 403
    assert (await client.get(f"{API}/reports/unknown", headers=admin)).status_code == 422


async def test_report_export_job_is_audited(client, db, admin, dispatcher):
    headers = {**admin, "Idempotency-Key": "export-enrolment-csv"}
    body = {"format": "csv", "class_id": str(F2)}
    queued = await client.post(f"{API}/reports/enrolment/export", headers=headers, json=body)
    assert queued.status_code == 202
    assert (await client.post(f"{API}/reports/enrolment/export", headers=headers, json=body)).json()[
        "id"
    ] == queued.json()["id"]
    for call in dispatcher.take("reports.export"):
        assert await reports.run_export(**call) == "succeeded"
    job = (await client.get(f"{API}/jobs/{queued.json()['id']}", headers=admin)).json()
    assert job["status"] == "SUCCEEDED" and job["processed_items"] == 6
    file = await client.get(f"{API}/jobs/{queued.json()['id']}/files/result", headers=admin)
    assert file.headers["content-type"].startswith("text/csv") and file.headers["content-disposition"].endswith('.csv"')
    lines = file.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("admission_no,name,sex") and len(lines) == 7

    pdf = await client.post(
        f"{API}/reports/staff/export", headers={**admin, "Idempotency-Key": "export-staff-pdf"}, json={"format": "pdf"}
    )
    for call in dispatcher.take("reports.export"):
        await reports.run_export(**call)
    assert (await client.get(f"{API}/jobs/{pdf.json()['id']}/files/result", headers=admin)).content[:4] == b"%PDF"
    await as_school(db, SCHOOL_A)
    exports = (
        (await db.execute(select(AuditLog).where(AuditLog.action == "EXPORT", AuditLog.entity_type == "reports")))
        .scalars()
        .all()
    )
    assert len(exports) == 2
    bursar = bearer(await login(client, username="bursar"))
    assert (
        await client.post(f"{API}/reports/staff/export", headers={**bursar, "Idempotency-Key": "bursar-staff"}, json={})
    ).status_code == 403


async def test_dashboards_per_role(client, admin):
    office = (await client.get(f"{API}/dashboards/admin", headers=admin)).json()
    tiles = office["tiles"]
    assert (tiles["students_active"], tiles["registers_taken"], tiles["attendance_today_pct"]) == (7, 1, 75.0)
    assert tiles["sms_credit"] == 998 and tiles["pending"]["privacy_requests"] == 1
    assert {c["class"] for c in office["series"]["enrolment_by_class"]} == {"F2", "F5"}
    assert len(office["series"]["collections_30_days"]) == 30
    bursar = bearer(await login(client, username="bursar"))
    money = (await client.get(f"{API}/dashboards/bursar", headers=bursar)).json()
    assert money["tiles"]["billed_tzs"].endswith(".00") and [a["bucket"] for a in money["series"]["aging"]] == [
        "1-30",
        "31-60",
        "61-90",
        "90+",
    ]
    salma = bearer(await login(client, username="tch.salma"))
    mine = (await client.get(f"{API}/dashboards/teacher", headers=salma)).json()
    assert (
        mine["series"]["registers_today"][0]["label"] == "F2 A" and mine["series"]["registers_today"][0]["marked"] == 4
    )
    assert (await client.get(f"{API}/dashboards/admin", headers=salma)).status_code == 403
    assert (await client.get(f"{API}/dashboards/bursar", headers=salma)).status_code == 403


async def test_compliance_exports(client, admin, dispatcher):
    body = {"templates": ["ENROLMENT", "RESULTS", "STAFF", "ATTENDANCE"], "academic_year_id": str(YEAR_2026)}
    queued = await client.post(
        f"{API}/compliance-exports", headers={**admin, "Idempotency-Key": "compliance-2026"}, json=body
    )
    assert queued.status_code == 202
    for call in dispatcher.take("compliance.export"):
        assert await compliance.run(**call) == "succeeded"
    file = await client.get(f"{API}/jobs/{queued.json()['id']}/files/result", headers=admin)
    book = load_workbook(io.BytesIO(file.content))
    assert book.sheetnames == ["ENROLMENT", "RESULTS", "STAFF", "ATTENDANCE"]
    enrolment = [list(r) for r in book["ENROLMENT"].iter_rows(min_row=3, values_only=True)]
    assert sum(r[-2] + r[-1] for r in enrolment) == 7  # every active student counted once
    results = [list(r) for r in book["RESULTS"].iter_rows(min_row=3, values_only=True)]
    assert results[0][0] == "F2" and sum(results[0][1:]) == 6
    two_csv = {**body, "format": "csv", "templates": ["ENROLMENT", "STAFF"]}
    assert (
        await client.post(
            f"{API}/compliance-exports", headers={**admin, "Idempotency-Key": "compliance-csv"}, json=two_csv
        )
    ).status_code == 422
    teacher = bearer(await login(client, username="tch.salma"))
    assert (
        await client.post(f"{API}/compliance-exports", headers={**teacher, "Idempotency-Key": "t-comp"}, json=body)
    ).status_code == 403


async def test_data_subject_requests(client, db, admin):
    created = await client.post(
        f"{API}/data-subject-requests",
        headers=admin,
        json={"subject_user_id": str(BARAKA_USER), "request_type": "EXPORT"},
    )
    assert created.status_code == 201 and created.json()["status"] == "RECEIVED" and created.json()["overdue"] is False
    assert (
        await client.patch(
            f"{API}/data-subject-requests/{created.json()['id']}", headers=admin, json={"status": "COMPLETED"}
        )
    ).status_code == 422
    done = await client.post(f"{API}/data-subject-requests/{created.json()['id']}/export", headers=admin)
    assert done.json()["status"] == "COMPLETED" and done.json()["has_file"]
    data = json.loads(
        (await client.get(f"{API}/data-subject-requests/{created.json()['id']}/file", headers=admin)).content
    )
    assert (
        data["student"]["admission_no"] == "MF-2025-0031"
        and data["results"]
        and data["invoices"]
        and len(data["attendance"]) >= 5
    )
    assert {g["first_name"] for g in data["guardians"]} == {"Joseph"}

    erase = await client.post(
        f"{API}/data-subject-requests",
        headers=admin,
        json={"subject_user_id": str(MOLLEL_USER), "request_type": "DELETE", "details": "Mzazi ameomba kufutwa"},
    )
    out = await client.post(f"{API}/data-subject-requests/{erase.json()['id']}/anonymise", headers=admin)
    assert out.status_code == 200 and out.json()["subject_name"].startswith("Aliyefutwa")
    await as_school(db, SCHOOL_A)
    user = (await db.execute(select(User).where(User.id == MOLLEL_USER))).scalar_one()
    assert (user.phone_enc, user.email, user.username, user.status) == (None, None, None, "NO_LOGIN")
    guardian = (await db.execute(select(Guardian.id).where(Guardian.user_id == MOLLEL_USER))).scalar_one()
    open_consents = (
        await db.execute(
            select(ConsentRecord).where(ConsentRecord.guardian_id == guardian, ConsentRecord.withdrawn_at.is_(None))
        )
    ).all()
    assert open_consents == []

    staff = await client.post(
        f"{API}/data-subject-requests",
        headers=admin,
        json={"subject_user_id": str(SALMA_USER), "request_type": "DELETE"},
    )
    assert (
        await client.post(f"{API}/data-subject-requests/{staff.json()['id']}/anonymise", headers=admin)
    ).status_code == 409
    fix = await client.post(
        f"{API}/data-subject-requests",
        headers=admin,
        json={"subject_user_id": str(SALMA_USER), "request_type": "CORRECT"},
    )
    await db.execute(
        update(DataSubjectRequest)
        .where(DataSubjectRequest.id == uuid.UUID(fix.json()["id"]))
        .values(due_at=calendar.local(datetime(2026, 1, 1)))
    )
    await db.commit()
    listed = {r["id"]: r for r in (await client.get(f"{API}/data-subject-requests", headers=admin)).json()}
    assert listed[fix.json()["id"]]["overdue"] is True
    corrected = await client.patch(
        f"{API}/data-subject-requests/{fix.json()['id']}",
        headers=admin,
        json={"status": "COMPLETED", "note": "Jina limesahihishwa"},
    )
    assert corrected.json()["status"] == "COMPLETED" and corrected.json()["overdue"] is False
    teacher = bearer(await login(client, username="tch.salma"))
    assert (await client.get(f"{API}/data-subject-requests", headers=teacher)).status_code == 403
    assert timedelta(days=29) < datetime.fromisoformat(listed[created.json()["id"]]["due_at"]) - datetime.fromisoformat(
        listed[created.json()["id"]]["requested_at"]
    )
