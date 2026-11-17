from sqlalchemy import select

from app.models import Student, invoice_balances
from tests.conftest import login

API = "/api/v1"
PDF = b"%PDF-1.7\n% test document\n"

# Seed: enrolment 3 = Baraka (student 3), Form V PCM, SUBMITTED.
# Documents 1, 2 are VALID; 3 (medical form) and 4 (CSEE results) are PENDING.


def test_full_enrolment_flow(client, db, as_registrar):
    teacher = login(client, "tch.kimaro")
    r = client.patch(f"{API}/enrolment-documents/3", headers=teacher, json={"status": "VALID"})
    assert r.status_code == 200 and r.json()["status"] == "SUBMITTED"        # one still pending
    r = client.patch(f"{API}/enrolment-documents/4", headers=teacher, json={"status": "VALID"})
    assert r.json()["status"] == "VALIDATED"

    r = client.post(f"{API}/enrolments/3/confirm", headers=as_registrar, json={"stream": "A"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enrolment"]["status"] == "CONFIRMED"
    assert body["schedules_linked"] == 2                  # PCM sessions 6 and 7 in the seed
    assert body["invoice_no"].startswith("INV-")

    student = db.get(Student, 3)
    db.refresh(student)
    assert student.current_status == "ACTIVE"
    invoice = db.execute(select(invoice_balances).where(invoice_balances.c.invoice_no == body["invoice_no"])
                         ).mappings().one()
    assert invoice["total_tzs"] == 790000                 # PCM tuition + meals + exam


def test_invalid_document_is_resubmitted(client, as_registrar):
    teacher = login(client, "tch.kimaro")
    client.patch(f"{API}/enrolment-documents/4", headers=teacher, json={"status": "VALID"})
    r = client.patch(f"{API}/enrolment-documents/3", headers=teacher,
                     json={"status": "INVALID", "remarks": "Medical form is not signed by a doctor"})
    assert r.json()["status"] == "INVALID"

    student = login(client, "s2026-0003")
    up = client.post(f"{API}/enrolments/3/documents", headers=student, data={"requirement_id": "3"},
                     files={"file": ("medical.pdf", PDF, "application/pdf")})
    assert up.status_code == 201, up.text
    assert client.post(f"{API}/enrolments/3/submit", headers=student).json()["status"] == "SUBMITTED"
    r = client.patch(f"{API}/enrolment-documents/3", headers=teacher, json={"status": "VALID"})
    assert r.json()["status"] == "VALIDATED"


def test_invalid_without_remarks_is_rejected(client):
    teacher = login(client, "tch.kimaro")
    r = client.patch(f"{API}/enrolment-documents/3", headers=teacher, json={"status": "INVALID"})
    assert r.status_code == 422


def test_application_upload_and_submit_rules(client, as_registrar):
    created = client.post(f"{API}/students", headers=as_registrar, json={
        "first_name": "Rose", "last_name": "Shirima", "gender": "F", "date_of_birth": "2013-05-05",
        "guardians": [{"first_name": "Anna", "last_name": "Shirima", "gender": "F", "phone": "0713000999",
                       "relationship": "MOTHER"}]}).json()
    r = client.post(f"{API}/enrolments", headers=as_registrar,
                    json={"offering_id": 1, "student_id": created["student_id"]})
    assert r.status_code == 201, r.text
    enrolment = r.json()
    assert {req["code"] for req in enrolment["requirements"]} >= {"BIRTH_CERT", "PSLE_RESULTS"}
    assert "CSEE_RESULTS" not in {req["code"] for req in enrolment["requirements"]}    # A-Level only
    eid = enrolment["enrolment_id"]

    exe = client.post(f"{API}/enrolments/{eid}/documents", headers=as_registrar, data={"requirement_id": "1"},
                      files={"file": ("cheti.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")})
    assert exe.status_code == 422                          # type checked from the bytes

    ok = client.post(f"{API}/enrolments/{eid}/documents", headers=as_registrar, data={"requirement_id": "1"},
                     files={"file": ("cheti.pdf", PDF, "application/pdf")})
    assert ok.status_code == 201 and ok.json()["sha256"]

    missing = client.post(f"{API}/enrolments/{eid}/submit", headers=as_registrar)
    assert missing.status_code == 422
    assert set(missing.json()["detail"]["missing"]) == {"PASSPORT_PHOTO", "MEDICAL_FORM", "PSLE_RESULTS"}

    cancelled = client.post(f"{API}/enrolments/{eid}/cancel", headers=as_registrar,
                            json={"reason": "Parent chose another school"})
    assert cancelled.json()["status"] == "CANCELLED"
    again = client.post(f"{API}/enrolments", headers=as_registrar,
                        json={"offering_id": 1, "student_id": created["student_id"]})
    assert again.status_code == 201                        # allowed after cancellation


def test_one_active_enrolment_per_year(client, as_registrar):
    # Amani (student 1) is already confirmed in Form II A for 2026
    r = client.post(f"{API}/enrolments", headers=as_registrar, json={"offering_id": 1, "student_id": 1})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "DUPLICATE"


def test_confirm_requires_validated(client, as_registrar):
    r = client.post(f"{API}/enrolments/3/confirm", headers=as_registrar, json={"stream": "A"})
    assert r.status_code == 409


def test_student_cannot_see_another_students_enrolment(client):
    headers = login(client, "s2026-0003")
    assert client.get(f"{API}/enrolments/1", headers=headers).status_code == 404
    assert client.get(f"{API}/enrolments/3", headers=headers).status_code == 200
