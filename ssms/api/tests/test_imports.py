"""Bulk import (all-or-nothing, error report, Idempotency-Key), jobs API and audit-log API."""

import csv
import io
import uuid

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.core.errors import AppError
from app.models import Staff, Stream, Student
from app.services import imports
from app.services import staff as staff_service
from tests.helpers import ADMIN_A, SCHOOL_A, as_school, bearer, login, u

API = "/api/v1"
F1 = u(16, 1)


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


def csv_file(kind: str, rows: list[dict]) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=[c[0] for c in imports.COLUMNS[kind]])
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def student_row(**overrides) -> dict:
    row = {
        "first_name": "Halima",
        "last_name": "Said",
        "gender": "F",
        "date_of_birth": "2013-04-02",
        "birth_cert_no": f"BC-{uuid.uuid4().hex[:8]}",
        "class_code": "F1",
        "stream_name": "A",
        "guardian_first_name": "Said",
        "guardian_last_name": "Omari",
        "guardian_gender": "M",
        "guardian_phone": "0655100200",
        "guardian_relationship": "FATHER",
        "guardian_sms_consent": "YES",
        "data_processing_consent": "YES",
    }
    row.update(overrides)
    return row


async def upload(client, headers, kind: str, data: bytes, key: str | None = "key-" + "0" * 8, name="file.csv"):
    extra = {"Idempotency-Key": key} if key else {}
    return await client.post(
        f"{API}/imports/{kind}", headers={**headers, **extra}, files={"file": (name, data, "text/csv")}
    )


async def run_queued(dispatcher) -> list[str]:
    return [await imports.run_job(**call) for call in dispatcher.take("imports.run")]


async def count_students(db) -> int:
    await as_school(db, SCHOOL_A)
    return (await db.execute(select(func.count()).select_from(Student))).scalar()


async def test_template_and_permissions(client, admin):
    response = await client.get(f"{API}/imports/templates/students", headers=admin)
    assert response.status_code == 200
    sheet = load_workbook(io.BytesIO(response.content)).worksheets[0]
    assert [c.value for c in sheet[1]][:3] == ["first_name", "middle_name", "last_name"]
    teacher = bearer(await login(client, username="tch.salma"))
    assert (await client.get(f"{API}/imports/templates/students", headers=teacher)).status_code == 403
    assert (await client.get(f"{API}/imports/templates/marks", headers=admin)).status_code == 422


async def test_upload_checks(client, admin):
    good = csv_file("students", [student_row()])
    missing_key = await upload(client, admin, "students", good, key=None)
    assert missing_key.status_code == 422 and missing_key.json()["error_code"] == "IDEMPOTENCY_KEY_REQUIRED"
    headers = await upload(client, admin, "students", b"name,age\nJuma,12\n")
    assert headers.status_code == 422 and headers.json()["error_code"] == "IMPORT_HEADERS"
    assert "first_name" in headers.json()["details"][0]["missing"]
    binary = await upload(client, admin, "students", b"\xff\xfe\x00\x01garbage", name="x.bin")
    assert binary.status_code == 422 and binary.json()["error_code"] == "FILE_TYPE"


async def test_students_import_succeeds_and_is_idempotent(client, db, admin, dispatcher):
    before = await count_students(db)
    data = csv_file(
        "students",
        [
            student_row(),
            student_row(first_name="Hamisi", gender="M"),
            student_row(first_name="Asha", class_code="", stream_name=""),
        ],
    )
    response = await upload(client, admin, "students", data, key="students-2026-001")
    assert response.status_code == 202 and response.json()["status"] == "QUEUED"
    job_id = response.json()["id"]
    assert await run_queued(dispatcher) == ["succeeded"]
    assert await imports.run_job(job_id=job_id, school_id=str(SCHOOL_A)) == "skipped"  # a retry does nothing

    job = (await client.get(f"{API}/jobs/{job_id}", headers=admin)).json()
    assert job["status"] == "SUCCEEDED" and job["processed_items"] == 3 and job["result_url"]
    assert await count_students(db) == before + 3
    result = load_workbook(io.BytesIO((await client.get(job["result_url"], headers=admin)).content)).worksheets[0]
    numbers = [row[2] for row in result.iter_rows(min_row=2, values_only=True)]
    assert len(numbers) == 3 and all(n.startswith("TZ-") for n in numbers)

    same = await upload(client, admin, "students", data, key="students-2026-001")
    assert same.status_code == 202 and same.json()["id"] == job_id and dispatcher.sent == []
    other = await upload(client, admin, "students", csv_file("students", [student_row()]), key="students-2026-001")
    assert other.status_code == 422 and other.json()["error_code"] == "IDEMPOTENCY_MISMATCH"
    listed = (await client.get(f"{API}/jobs", headers=admin)).json()["items"]
    assert listed[0]["id"] == job_id


async def test_any_bad_row_rejects_the_whole_file(client, db, admin, dispatcher):
    before = await count_students(db)
    rows = [
        student_row(birth_cert_no="BC-SAME-0001"),
        student_row(birth_cert_no="BC-SAME-0001"),  # duplicate in file
        student_row(guardian_phone="12345"),  # bad phone
        student_row(class_code="F9"),  # unknown class
        student_row(data_processing_consent="NO"),  # PDPA consent missing
        student_row(date_of_birth="2025-01-01"),
    ]  # too young
    response = await upload(client, admin, "students", csv_file("students", rows))
    assert await run_queued(dispatcher) == ["failed"]
    job = (await client.get(f"{API}/jobs/{response.json()['id']}", headers=admin)).json()
    assert job["status"] == "FAILED" and job["error_count"] == 5 and job["result_url"] is None
    assert await count_students(db) == before  # nothing written
    errors = load_workbook(io.BytesIO((await client.get(job["error_report_url"], headers=admin)).content)).worksheets[0]
    found = {(r[0], r[1], r[2]) for r in errors.iter_rows(min_row=2, values_only=True)}
    assert found == {
        (3, "birth_cert_no", "duplicate_in_file"),
        (4, "guardian_phone", "invalid_phone"),
        (5, "class_code", "unknown_class"),
        (6, "data_processing_consent", "required"),
        (7, "date_of_birth", "student_age"),
    }


async def test_capacity_and_school_duplicates_are_checked_before_writing(client, db, admin, dispatcher):
    await as_school(db, SCHOOL_A, ADMIN_A)
    db.add(Stream(school_id=SCHOOL_A, class_id=F1, name="Z", capacity=1, created_by=ADMIN_A))
    await db.commit()
    first = student_row(birth_cert_no="BC-KEEP-0001", stream_name="Z")
    await upload(client, admin, "students", csv_file("students", [first]), key="capacity-0001")
    assert await run_queued(dispatcher) == ["succeeded"]
    rows = [student_row(stream_name="Z"), student_row(birth_cert_no="BC-KEEP-0001")]
    response = await upload(client, admin, "students", csv_file("students", rows), key="capacity-0002")
    assert await run_queued(dispatcher) == ["failed"]
    job = (await client.get(f"{API}/jobs/{response.json()['id']}", headers=admin)).json()
    errors = load_workbook(io.BytesIO((await client.get(job["error_report_url"], headers=admin)).content)).worksheets[0]
    assert {(r[0], r[2]) for r in errors.iter_rows(min_row=2, values_only=True)} == {
        (2, "stream_full"),
        (3, "duplicate_in_school"),
    }


async def test_guardians_import(client, admin, dispatcher):
    row = {
        "admission_no": "MF-2025-0040",
        "first_name": "Zuhura",
        "last_name": "Kombo",
        "gender": "F",
        "phone": "0699123123",
        "relationship": "MOTHER",
        "is_primary": "NO",
        "sms_consent": "YES",
    }
    await upload(client, admin, "guardians", csv_file("guardians", [row]), key="guardians-0001")
    assert await run_queued(dispatcher) == ["succeeded"]
    links = (await client.get(f"{API}/students/{u(6, 15)}/guardians", headers=admin)).json()
    assert "Zuhura Kombo" in {g["full_name"] for g in links}
    await upload(
        client,
        admin,
        "guardians",
        csv_file("guardians", [{**row, "admission_no": "XX-2020-0001"}]),
        key="guardians-0002",
    )
    assert await run_queued(dispatcher) == ["failed"]


async def test_staff_import_sends_account_sms_after_commit(client, admin, dispatcher):
    rows = [
        {
            "first_name": "Faraji",
            "last_name": "Msuya",
            "gender": "M",
            "phone": "0688200300",
            "staff_no": "MF-STF-201",
            "department_code": "SCI",
            "designation_code": "SUBJECT_TEACHER",
        },
        {
            "first_name": "Lucy",
            "last_name": "Temba",
            "gender": "F",
            "phone": "0688200301",
            "staff_no": "MF-STF-202",
            "roles": "teacher,librarian",
        },
    ]
    response = await upload(client, admin, "staff", csv_file("staff", rows), key="staff-0001")
    assert await run_queued(dispatcher) == ["succeeded"]
    assert len(dispatcher.take("sms.send")) == 2
    job = (await client.get(f"{API}/jobs/{response.json()['id']}", headers=admin)).json()
    result = load_workbook(io.BytesIO((await client.get(job["result_url"], headers=admin)).content)).worksheets[0]
    assert [r[2] for r in result.iter_rows(min_row=2, values_only=True)] == ["f.msuya", "l.temba"]

    taken = {**rows[0], "staff_no": "MF-STF-001", "phone": "0688200399"}
    await upload(client, admin, "staff", csv_file("staff", [taken]), key="staff-0002")
    assert await run_queued(dispatcher) == ["failed"] and dispatcher.take("sms.send") == []


async def test_failure_while_writing_rolls_back_every_row(client, db, admin, dispatcher, monkeypatch):
    original = staff_service.create_staff
    calls = {"n": 0}

    async def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise AppError(409, "DUPLICATE")
        return await original(*args, **kwargs)

    monkeypatch.setattr(staff_service, "create_staff", flaky)
    rows = [
        {"first_name": "Ana", "last_name": "Moshi", "gender": "F", "phone": "0688300001", "staff_no": "MF-STF-301"},
        {"first_name": "Ben", "last_name": "Moshi", "gender": "M", "phone": "0688300002", "staff_no": "MF-STF-302"},
    ]
    await upload(client, admin, "staff", csv_file("staff", rows), key="staff-rollback")
    assert await run_queued(dispatcher) == ["failed"]
    await as_school(db, SCHOOL_A)
    assert (await db.execute(select(Staff.id).where(Staff.staff_no == "MF-STF-301"))).scalar() is None
    assert dispatcher.take("sms.send") == []


async def test_jobs_are_private_to_their_owner(client, admin, dispatcher):
    response = await upload(client, admin, "students", csv_file("students", [student_row()]), key="private-0001")
    teacher = bearer(await login(client, username="tch.salma"))
    assert (await client.get(f"{API}/jobs/{response.json()['id']}", headers=teacher)).status_code == 404


async def test_audit_log_api(client, admin):
    await client.post(f"{API}/departments", headers=admin, json={"code": "ART", "name_en": "Arts", "name_sw": "Sanaa"})
    page = (await client.get(f"{API}/audit-logs?action=LOGIN&limit=1", headers=admin)).json()
    assert page["items"][0]["action"] == "LOGIN" and page["items"][0]["actor_user_id"] == str(ADMIN_A)
    users = (await client.get(f"{API}/audit-logs?entity=users&limit=2", headers=admin)).json()
    assert len(users["items"]) == 2 and users["next_cursor"]
    following = (
        await client.get(f"{API}/audit-logs?entity=users&limit=2&cursor={users['next_cursor']}", headers=admin)
    ).json()
    assert users["items"][-1]["occurred_at"] >= following["items"][0]["occurred_at"]
    assert not {i["id"] for i in users["items"]} & {i["id"] for i in following["items"]}
    teacher = bearer(await login(client, username="tch.salma"))
    assert (await client.get(f"{API}/audit-logs", headers=teacher)).status_code == 403
