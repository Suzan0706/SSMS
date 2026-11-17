"""School settings, users and roles, staff, students, guardians, consent. All requests as ssms_app under RLS."""

import re
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, ConsentRecord, Enrolment, Stream
from tests.helpers import ADMIN_A, SCHOOL_A, as_school, bearer, login, rekey_phone, u

API = "/api/v1"
F1, F1_A, F2_A = u(16, 1), u(19, 1), u(19, 2)
STUDENT_B = u(6, 111)


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


@pytest.fixture
async def teacher(client) -> dict:
    return bearer(await login(client, username="tch.mwita"))  # teacher + department head


def new_student(**overrides) -> dict:
    body = {
        "first_name": "Upendo",
        "last_name": "Mushi",
        "gender": "F",
        "date_of_birth": str(date.today().replace(year=date.today().year - 13)),
        "birth_cert_no": "BC-1100-2213",
        "stream_id": str(F1_A),
        "consent_data_processing": True,
        "guardians": [
            {
                "first_name": "Anna",
                "last_name": "Mushi",
                "gender": "F",
                "phone": "0767111222",
                "relationship": "MOTHER",
                "is_primary": True,
                "sms_consent": True,
            }
        ],
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------- isolation and permissions


async def test_other_schools_records_are_not_found(client, admin):
    assert (await client.get(f"{API}/students/{STUDENT_B}", headers=admin)).status_code == 404
    page = (await client.get(f"{API}/students?limit=50", headers=admin)).json()
    assert page["items"] and all(s["admission_no"].startswith("MF-") for s in page["items"])


async def test_permissions_are_enforced(client, teacher):
    assert (await client.get(f"{API}/students", headers=teacher)).status_code == 200
    denied = await client.post(f"{API}/students", json=new_student(), headers=teacher)
    assert denied.status_code == 403 and denied.json()["error_code"] == "FORBIDDEN"
    assert (await client.patch(f"{API}/school", json={"motto": "x"}, headers=teacher)).status_code == 403


# ---------------------------------------------------------------- students


async def test_admit_student_into_stream(client, db, admin):
    response = await client.post(f"{API}/students", json=new_student(), headers=admin)
    assert response.status_code == 201, response.text
    body = response.json()
    assert re.fullmatch(rf"TZ-{date.today().year}-\d{{4}}", body["admission_no"])
    assert body["status"] == "ACTIVE" and body["enrolment"]["class_code"] == "F1"
    assert body["has_birth_cert_no"] and not body["has_nida"]
    [guardian] = body["guardians"]
    assert guardian["is_primary"] and guardian["receives_sms"] and guardian["phone"] == "255767111222"

    await as_school(db, SCHOOL_A)
    purposes = (
        (await db.execute(select(ConsentRecord.purpose).where(ConsentRecord.student_id == body["id"]))).scalars().all()
    )
    assert sorted(purposes) == ["DATA_PROCESSING", "SMS"]
    audited = (
        await db.execute(
            select(AuditLog.actor_user_id, AuditLog.after_data).where(
                AuditLog.entity_type == "students", AuditLog.entity_id == body["id"]
            )
        )
    ).one()
    assert audited.actor_user_id == ADMIN_A
    assert not any(k.endswith(("_enc", "_hash")) for k in audited.after_data)  # identifiers redacted


async def test_guardian_is_reused_by_phone_and_phone_masked_for_teachers(client, admin, teacher):
    first = (await client.post(f"{API}/students", json=new_student(), headers=admin)).json()
    sibling = new_student(
        first_name="Baraka",
        gender="M",
        birth_cert_no="BC-1100-9999",
        stream_id=None,
        guardians=[
            {
                "first_name": "Anna",
                "last_name": "Mushi",
                "gender": "F",
                "phone": "+255767111222",
                "relationship": "MOTHER",
                "is_primary": True,
            }
        ],
    )
    second = (await client.post(f"{API}/students", json=sibling, headers=admin)).json()
    assert second["status"] == "APPLICANT" and second["enrolment"] is None
    assert second["guardians"][0]["guardian_id"] == first["guardians"][0]["guardian_id"]
    assert second["guardians"][0]["receives_sms"] is False  # no SMS consent given here

    seen = (await client.get(f"{API}/students/{first['id']}", headers=teacher)).json()
    assert seen["guardians"][0]["phone"] == "****1222"


@pytest.mark.parametrize(
    "change, error_code, field_code",
    [
        (
            {
                "guardians": [
                    {
                        "first_name": "A",
                        "last_name": "B",
                        "gender": "M",
                        "phone": "0767000001",
                        "relationship": "FATHER",
                        "is_primary": False,
                    }
                ]
            },
            "ONE_PRIMARY_GUARDIAN",
            None,
        ),
        ({"date_of_birth": str(date.today() - timedelta(days=365))}, "VALIDATION_ERROR", "student_age"),
        ({"date_of_birth": str(date.today() + timedelta(days=3))}, "VALIDATION_ERROR", "future_date"),
        ({"consent_data_processing": False}, "VALIDATION_ERROR", "required"),
        ({"nida": "123"}, "VALIDATION_ERROR", "invalid_nida"),
        ({"guardians": []}, "VALIDATION_ERROR", None),
    ],
)
async def test_admission_validation(client, admin, change, error_code, field_code):
    response = await client.post(f"{API}/students", json=new_student(**change), headers=admin)
    assert response.status_code == 422 and response.json()["error_code"] == error_code
    if field_code:
        assert field_code in {d["code"] for d in response.json()["details"]}


async def test_duplicate_birth_certificate(client, admin):
    assert (await client.post(f"{API}/students", json=new_student(), headers=admin)).status_code == 201
    again = await client.post(
        f"{API}/students",
        json=new_student(first_name="Other", guardians=[{**new_student()["guardians"][0], "phone": "0767999888"}]),
        headers=admin,
    )
    assert again.status_code == 409 and again.json()["error_code"] == "DUPLICATE"


async def test_stream_full(client, db, admin):
    await as_school(db, SCHOOL_A, ADMIN_A)
    tiny = Stream(school_id=SCHOOL_A, class_id=F1, name="Z", capacity=1, created_by=ADMIN_A)
    db.add(tiny)
    await db.commit()
    ok = await client.post(f"{API}/students", json=new_student(stream_id=str(tiny.id)), headers=admin)
    assert ok.status_code == 201
    full = await client.post(
        f"{API}/students", json=new_student(stream_id=str(tiny.id), birth_cert_no="BC-7777-0001"), headers=admin
    )
    assert full.status_code == 409 and full.json()["error_code"] == "STREAM_FULL"


async def test_list_search_and_cursor(client, admin):
    response = await client.get(f"{API}/students?q=lyimo", headers=admin)
    assert response.status_code == 200, response.text
    found = response.json()["items"]
    assert {s["admission_no"] for s in found} >= {"MF-2026-0003"}
    page1 = (await client.get(f"{API}/students?limit=2", headers=admin)).json()
    second = await client.get(f"{API}/students?limit=2&cursor={page1['next_cursor']}", headers=admin)
    assert second.status_code == 200, second.text
    page2 = second.json()
    names1, names2 = [s["full_name"] for s in page1["items"]], [s["full_name"] for s in page2["items"]]
    assert len(names1) == 2 and not set(names1) & set(names2)
    in_f2 = (await client.get(f"{API}/students?stream_id={F2_A}", headers=admin)).json()["items"]
    assert in_f2 and all(s["class_code"] == "F2" for s in in_f2)


async def test_status_changes(client, db, admin):
    student = (await client.post(f"{API}/students", json=new_student(), headers=admin)).json()
    url = f"{API}/students/{student['id']}/status"
    future = await client.post(
        url,
        headers=admin,
        json={
            "new_status": "SUSPENDED",
            "reason": "Discipline",
            "effective_date": str(date.today() + timedelta(days=1)),
        },
    )
    assert future.status_code == 422
    left = await client.post(
        url,
        headers=admin,
        json={"new_status": "TRANSFERRED", "reason": "Moved to Arusha", "effective_date": str(date.today())},
    )
    assert left.status_code == 200 and left.json()["old_status"] == "ACTIVE"
    await as_school(db, SCHOOL_A)
    enrolment = (
        await db.execute(select(Enrolment.status, Enrolment.ended_on).where(Enrolment.student_id == student["id"]))
    ).one()
    assert tuple(enrolment) == ("TRANSFERRED_OUT", date.today())
    wrong = await client.post(
        url,
        headers=admin,
        json={"new_status": "GRADUATED", "reason": "Not possible", "effective_date": str(date.today())},
    )
    assert wrong.status_code == 409 and wrong.json()["error_code"] == "STATUS_TRANSITION"


async def test_identifiers_are_audited(client, db, admin, teacher):
    student = (
        await client.post(f"{API}/students", json=new_student(nida="19900101-12345-00001-27"), headers=admin)
    ).json()
    url = f"{API}/students/{student['id']}/identifiers"
    assert (await client.get(url, headers=teacher)).status_code == 403
    assert (await client.get(url, headers=admin)).json() == {
        "birth_cert_no": "BC-1100-2213",
        "nida": "19900101123450000127",
    }
    await as_school(db, SCHOOL_A)
    assert (
        await db.execute(
            select(AuditLog.action).where(AuditLog.action == "VIEW_SENSITIVE", AuditLog.entity_id == student["id"])
        )
    ).scalar()


async def test_update_student(client, admin):
    student = (await client.post(f"{API}/students", json=new_student(), headers=admin)).json()
    changed = await client.patch(
        f"{API}/students/{student['id']}", json={"middle_name": "Grace", "prem_number": "P-1"}, headers=admin
    )
    assert changed.status_code == 200 and changed.json()["full_name"] == "Upendo Grace Mushi"


async def test_guardian_links_and_consent_withdrawal(client, admin):
    student = (await client.post(f"{API}/students", json=new_student(), headers=admin)).json()
    primary = student["guardians"][0]["guardian_id"]
    url = f"{API}/students/{student['id']}/guardians"
    blocked = await client.delete(f"{url}/{primary}?reason=Wrong person", headers=admin)
    assert blocked.status_code == 409 and blocked.json()["error_code"] == "ONE_PRIMARY_GUARDIAN"
    added = await client.post(
        url,
        headers=admin,
        json={
            "first_name": "Joseph",
            "last_name": "Mushi",
            "gender": "M",
            "phone": "0767333444",
            "relationship": "FATHER",
        },
    )
    assert added.status_code == 201 and len(added.json()) == 2
    father = next(g for g in added.json() if g["relationship"] == "FATHER")["guardian_id"]
    assert (await client.delete(f"{url}/{father}?reason=Entered twice", headers=admin)).status_code == 204

    withdrawn = await client.post(
        f"{API}/guardians/{primary}/consents",
        headers=admin,
        json={"purpose": "SMS", "granted": False, "channel": "IN_PERSON"},
    )
    assert withdrawn.status_code == 201
    links = (await client.get(url, headers=admin)).json()
    assert links[0]["receives_sms"] is False
    history = (await client.get(f"{API}/guardians/{primary}/consents", headers=admin)).json()
    assert [c["granted"] for c in history if c["purpose"] == "SMS"] == [False, True]


# ---------------------------------------------------------------- users and roles


async def test_reset_password_forces_change(client, db, admin, dispatcher):
    await rekey_phone(db, SCHOOL_A, u(2, 5), "255754000005")  # seed phones are fake ciphertext
    users = (await client.get(f"{API}/users?role=teacher&q=kimaro", headers=admin)).json()["items"]
    [kimaro] = users
    assert kimaro["roles"] == ["teacher"]
    reset = await client.post(f"{API}/users/{kimaro['id']}/reset-password", headers=admin)
    temp = reset.json()["temporary_password"]
    assert reset.status_code == 200 and len(dispatcher.take("sms.send")) == 1
    session = await login(client, username="tch.kimaro", password=temp)
    blocked = await client.get(f"{API}/students", headers=bearer(session))
    assert blocked.status_code == 403 and blocked.json()["error_code"] == "PASSWORD_CHANGE_REQUIRED"
    changed = await client.post(
        f"{API}/auth/change-password",
        headers=bearer(session),
        json={"current_password": temp, "new_password": "Mwalimu2026kimaro"},
    )
    assert changed.status_code == 204
    assert (await client.get(f"{API}/students", headers=bearer(session))).status_code == 200


async def test_disable_user_and_role_rules(client, admin, teacher):
    users = (await client.get(f"{API}/users?q=mwita", headers=admin)).json()["items"]
    mwita = users[0]["id"]
    assert (await client.patch(f"{API}/users/{ADMIN_A}", json={"status": "DISABLED"}, headers=admin)).status_code == 409
    assert (await client.delete(f"{API}/users/{ADMIN_A}/roles/school_admin", headers=admin)).status_code == 409

    roles = await client.post(f"{API}/users/{mwita}/roles", json={"role_code": "bursar"}, headers=admin)
    assert roles.status_code == 201 and "bursar" in roles.json()
    again = await client.post(f"{API}/users/{mwita}/roles", json={"role_code": "bursar"}, headers=admin)
    assert again.status_code == 409
    unknown = await client.post(f"{API}/users/{mwita}/roles", json={"role_code": "wizard"}, headers=admin)
    assert unknown.status_code == 422
    assert (await client.delete(f"{API}/users/{mwita}/roles/bursar", headers=admin)).status_code == 204

    assert (await client.patch(f"{API}/users/{mwita}", json={"status": "DISABLED"}, headers=admin)).status_code == 204
    assert (await client.get(f"{API}/auth/me", headers=teacher)).status_code == 401


# ---------------------------------------------------------------- staff

STAFF = {
    "person": {"first_name": "Rose", "last_name": "Mbwambo", "gender": "F", "phone": "0688123456"},
    "staff_no": "MF-STF-100",
    "employment_type": "CONTRACT",
    "salary_tzs": "900000.00",
    "department_id": str(u(9, 1)),
    "designation_id": str(u(10, 3)),
}


async def test_create_staff_account(client, admin, teacher, dispatcher):
    response = await client.post(f"{API}/staff", json=STAFF, headers=admin)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["username"] == "r.mbwambo" and body["roles"] == ["teacher"] and body["salary_tzs"] == "900000.00"
    [call] = dispatcher.take("sms.send")
    assert body["temporary_password"] in call["text"]
    as_hod = (await client.get(f"{API}/staff/{body['id']}", headers=teacher)).json()
    assert as_hod["salary_tzs"] is None and as_hod["phone"] == "****3456"  # no payroll.read / staff.manage
    first = await login(client, username="r.mbwambo", password=body["temporary_password"])
    assert first["user"]["must_change_password"]

    duplicate = await client.post(
        f"{API}/staff", json={**STAFF, "person": {**STAFF["person"], "phone": "0688000111"}}, headers=admin
    )
    assert duplicate.status_code == 409


async def test_staff_lifecycle(client, admin):
    staff = (await client.post(f"{API}/staff", json=STAFF, headers=admin)).json()
    url = f"{API}/staff/{staff['id']}"
    qualification = await client.post(
        f"{url}/qualifications",
        headers=admin,
        json={"level": "DEGREE", "title": "BEd Science", "institution": "University of Dodoma", "year_awarded": 2019},
    )
    assert qualification.status_code == 201
    assert (await client.delete(f"{url}/qualifications/{qualification.json()['id']}", headers=admin)).status_code == 204
    retired = await client.patch(url, json={"status": "RETIRED"}, headers=admin)
    assert retired.status_code == 200 and retired.json()["status"] == "RETIRED"
    locked_out = await client.post(
        f"{API}/auth/login",
        json={"school_code": "mfano-sec", "username": "r.mbwambo", "password": staff["temporary_password"]},
    )
    assert locked_out.status_code == 401
    assert (await client.delete(f"{url}?reason=Left the school", headers=admin)).status_code == 204
    assert (await client.get(url, headers=admin)).status_code == 404
    listed = (await client.get(f"{API}/staff?q=mbwambo", headers=admin)).json()["items"]
    assert listed == []


async def test_departments(client, admin):
    created = await client.post(
        f"{API}/departments", headers=admin, json={"code": "ICT", "name_en": "ICT", "name_sw": "TEHAMA"}
    )
    assert created.status_code == 201
    dup = await client.post(f"{API}/departments", headers=admin, json={"code": "ICT", "name_en": "x1", "name_sw": "x1"})
    assert dup.status_code == 409
    renamed = await client.patch(
        f"{API}/departments/{created.json()['id']}", headers=admin, json={"name_en": "Computing"}
    )
    assert renamed.json()["name_en"] == "Computing"
    in_use = await client.delete(f"{API}/departments/{u(9, 1)}?reason=Merge", headers=admin)
    assert in_use.status_code == 409
    assert (
        await client.delete(f"{API}/departments/{created.json()['id']}?reason=Not needed", headers=admin)
    ).status_code == 204
    designations = (await client.get(f"{API}/designations", headers=admin)).json()
    assert "HEAD_TEACHER" in {d["code"] for d in designations}


# ---------------------------------------------------------------- school and reference data


async def test_school_settings(client, admin):
    school = (await client.get(f"{API}/school", headers=admin)).json()
    assert school["code"] == "mfano-sec" and school["settings"]["admission_prefix"] == "TZ"
    changed = await client.patch(
        f"{API}/school",
        headers=admin,
        json={"admission_prefix": "MF", "sms_sender_id": "MFANO-SS", "phone": "0262321000"},
    )
    assert changed.status_code == 200 and changed.json()["settings"]["admission_prefix"] == "MF"
    admitted = (await client.post(f"{API}/students", json=new_student(), headers=admin)).json()
    assert admitted["admission_no"].startswith("MF-")
    bad = await client.patch(f"{API}/school", headers=admin, json={"admission_prefix": "toolong"})
    assert bad.status_code == 422


async def test_reference_lists(client, teacher):
    classes = (await client.get(f"{API}/classes", headers=teacher)).json()
    assert [c["code"] for c in classes][:4] == ["F1", "F2", "F3", "F4"]
    streams = (await client.get(f"{API}/streams?class_id={u(16, 2)}", headers=teacher)).json()
    assert {s["name"] for s in streams} == {"A", "B"}
    years = (await client.get(f"{API}/academic-years", headers=teacher)).json()
    assert years[0]["is_current"]
