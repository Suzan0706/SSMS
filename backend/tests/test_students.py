import re

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog, Guardian, Student, StudentStatusHistory, User
from tests.conftest import PASSWORD, login

API = "/api/v1"

NEW_STUDENT = {
    "first_name": "Neema", "middle_name": "Joseph", "last_name": "Mollel", "gender": "F",
    "date_of_birth": "2013-02-10", "region": "Arusha", "district": "Meru",
    "guardians": [{"first_name": "Joseph", "last_name": "Mollel", "gender": "M",
                   "phone": "0754 111 222", "relationship": "FATHER"}],
}


def test_registrar_registers_student_with_guardian(client, db, as_registrar):
    r = client.post(f"{API}/students", headers=as_registrar, json=NEW_STUDENT)
    assert r.status_code == 201, r.text
    body = r.json()
    assert re.fullmatch(r"S\d{4}-\d{4}", body["admission_no"])
    assert body["current_status"] == "APPLICANT"
    assert body["age"] >= 12                                    # computed from date_of_birth
    assert body["username"] == body["admission_no"].lower()
    user = db.scalar(select(User).where(User.username == body["username"]))
    assert user.password_hash.startswith("$argon2id$")
    guardian_user = db.scalar(select(User).join(Guardian, Guardian.user_id == User.user_id)
                              .where(User.phone == "255754111222"))
    assert guardian_user is not None and guardian_user.role == "PARENT"


def test_invalid_phone_is_rejected(client, as_registrar):
    bad = {**NEW_STUDENT, "guardians": [{**NEW_STUDENT["guardians"][0], "phone": "12345"}]}
    assert client.post(f"{API}/students", headers=as_registrar, json=bad).status_code == 422


def test_search_by_name(client, as_registrar):
    r = client.get(f"{API}/students", headers=as_registrar, params={"q": "massawe"})
    assert r.status_code == 200
    assert [s["admission_no"] for s in r.json()["items"]] == ["S2025-0014"]


def test_status_change_writes_history_and_audit(client, db, as_registrar):
    r = client.patch(f"{API}/students/2/status", headers=as_registrar,
                     json={"new_status": "SUSPENDED", "reason": "Discipline committee decision"})
    assert r.status_code == 200, r.text
    assert r.json()["old_status"] == "ACTIVE" and r.json()["new_status"] == "SUSPENDED"
    assert db.scalar(select(StudentStatusHistory).where(StudentStatusHistory.student_id == 2,
                                                        StudentStatusHistory.new_status == "SUSPENDED"))
    audit = db.scalars(select(AuditLog).where(AuditLog.entity_type == "students", AuditLog.entity_id == "2",
                                              AuditLog.action == "UPDATE")).all()
    assert any(a.actor_user_id == 2 and a.actor_role == "REGISTRAR"
               and a.new_values["current_status"] == "SUSPENDED" for a in audit)


def test_disallowed_transitions_are_rejected(client, as_registrar):
    # an applicant becomes ACTIVE only by enrolment confirmation
    r = client.patch(f"{API}/students/3/status", headers=as_registrar,
                     json={"new_status": "ACTIVE", "reason": "Trying to skip enrolment"})
    assert r.status_code == 422
    r = client.patch(f"{API}/students/3/status", headers=as_registrar,
                     json={"new_status": "GRADUATED", "reason": "Not allowed from applicant"})
    assert r.status_code == 422


def test_transfer_disables_student_login(client, as_registrar):
    r = client.patch(f"{API}/students/1/status", headers=as_registrar,
                     json={"new_status": "TRANSFERRED", "reason": "Transferred to Dodoma Sec."})
    assert r.status_code == 200
    denied = client.post(f"{API}/auth/login", data={"username": "s2025-0014", "password": PASSWORD})
    assert denied.status_code == 401


def test_parent_sees_only_own_child(client):
    headers = login(client, "p.massawe")
    assert client.get(f"{API}/students/1", headers=headers).status_code == 200
    assert client.get(f"{API}/students/2", headers=headers).status_code == 404


def test_audit_log_cannot_be_changed(db):
    with pytest.raises(DBAPIError, match="append-only"):
        with db.begin_nested():
            db.execute(text("UPDATE audit_logs SET action = 'LOGIN'"))
    assert db.scalar(select(Student).where(Student.student_id == 1)) is not None
