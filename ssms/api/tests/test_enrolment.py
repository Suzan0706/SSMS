"""Enrolment workflow (offerings, applications, documents, validation, decisions) and promotions."""

from datetime import date

import pytest
from sqlalchemy import select

from app.models import Enrolment, Student
from app.services import promotions
from tests.helpers import F1, F1_A, F2, F2_A, F5, SCHOOL_A, YEAR_2026, as_school, bearer, login, parent_login, u

API = "/api/v1"
SEED_APPLICATION = u(22, 1)
BIRTH_CERT, PHOTO, PSLE, TRANSFER = u(21, 1), u(21, 2), u(21, 3), u(21, 5)
PDF, JPG, PNG = b"%PDF-1.4\n% test\n", b"\xff\xd8\xff\xe0" + b"0" * 64, b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


@pytest.fixture
async def validator(client) -> dict:
    return bearer(await login(client, username="tch.salma"))  # teachers hold enrolment.validate


def application(**overrides) -> dict:
    body = {
        "class_id": str(F1),
        "academic_year_id": str(YEAR_2026),
        "consent_data_processing": True,
        "applicant": {
            "first_name": "Furaha",
            "last_name": "Mrema",
            "gender": "F",
            "date_of_birth": "2014-02-11",
            "birth_cert_no": "BC-8811-0001",
        },
        "guardians": [
            {
                "first_name": "Daniel",
                "last_name": "Mrema",
                "gender": "M",
                "phone": "0744123123",
                "relationship": "FATHER",
                "is_primary": True,
                "sms_consent": True,
            }
        ],
    }
    body.update(overrides)
    return body


async def upload(client, headers, app_id, requirement, data, name="file.pdf"):
    return await client.post(
        f"{API}/enrolment-applications/{app_id}/documents",
        headers=headers,
        data={"requirement_id": str(requirement)},
        files={"file": (name, data)},
    )


async def test_public_offerings(client):
    response = await client.get(f"{API}/enrolment/offerings?school_code=mfano-sec")
    assert response.status_code == 200
    body = response.json()
    assert body["open"] is True and body["academic_year"] == "2026"
    f1 = next(c for c in body["classes"] if c["code"] == "F1")
    assert f1["places_left"] == 45
    assert {r["name_en"] for r in f1["requirements"]} == {
        "Birth certificate (RITA)",
        "Passport-size photograph",
        "Standard VII (PSLE) results",
        "Transfer letter (if any)",
    }
    assert {c["code"] for c in body["combinations"]} == {"PCM"}
    assert (await client.get(f"{API}/enrolment/offerings?school_code=nope-school")).status_code == 404


async def test_full_workflow_from_application_to_admission(client, db, admin, validator, dispatcher):
    created = await client.post(f"{API}/enrolment-applications", headers=admin, json=application())
    assert created.status_code == 201, created.text
    body = created.json()
    app_id = body["id"]
    assert body["status"] == "REQUIREMENTS_PENDING" and body["application_no"].startswith("APP-2026-")
    assert {i["status"] for i in body["checklist"]} == {"MISSING"}

    wrong_type = await upload(client, admin, app_id, BIRTH_CERT, b"just text", "cheti.txt")
    assert wrong_type.status_code == 422 and wrong_type.json()["error_code"] == "FILE_TYPE"
    too_big = await upload(client, admin, app_id, BIRTH_CERT, PDF + b"0" * (5 * 1024 * 1024))
    assert too_big.status_code == 413
    assert (await upload(client, admin, app_id, BIRTH_CERT, PDF)).status_code == 201

    early = await client.post(f"{API}/enrolment-applications/{app_id}/submit", headers=admin)
    assert early.status_code == 422
    assert {d["name_en"] for d in early.json()["details"]} == {
        "Passport-size photograph",
        "Standard VII (PSLE) results",
    }
    photo = await upload(client, admin, app_id, PHOTO, JPG, "picha.jpg")
    assert photo.json()["mime_type"] == "image/jpeg"
    await upload(client, admin, app_id, PSLE, PNG, "psle.png")
    submitted = await client.post(f"{API}/enrolment-applications/{app_id}/submit", headers=admin)
    assert submitted.json()["status"] == "UNDER_REVIEW"

    no_comment = await client.patch(
        f"{API}/enrolment-documents/{photo.json()['id']}", headers=validator, json={"status": "INVALID"}
    )
    assert no_comment.status_code == 422
    back = await client.patch(
        f"{API}/enrolment-documents/{photo.json()['id']}",
        headers=validator,
        json={"status": "INVALID", "comment": "Picha haionekani / blurred"},
    )
    assert back.json()["status"] == "REQUIREMENTS_PENDING"
    photo2 = await upload(client, admin, app_id, PHOTO, JPG, "picha2.jpg")
    await client.post(f"{API}/enrolment-applications/{app_id}/submit", headers=admin)

    early_approve = await client.post(
        f"{API}/enrolment-applications/{app_id}/approve", headers=admin, json={"stream_id": str(F1_A)}
    )
    assert early_approve.status_code == 422 and early_approve.json()["details"][0]["code"] == "documents_not_valid"
    current = (await client.get(f"{API}/enrolment-applications/{app_id}", headers=validator)).json()
    for item in current["checklist"]:
        if item["document_id"]:
            await client.patch(
                f"{API}/enrolment-documents/{item['document_id']}", headers=validator, json={"status": "VALID"}
            )
    assert (
        await client.post(
            f"{API}/enrolment-applications/{app_id}/approve", headers=validator, json={"stream_id": str(F1_A)}
        )
    ).status_code == 403
    wrong_stream = await client.post(
        f"{API}/enrolment-applications/{app_id}/approve", headers=admin, json={"stream_id": str(F2_A)}
    )
    assert wrong_stream.status_code == 422
    approved = await client.post(
        f"{API}/enrolment-applications/{app_id}/approve", headers=admin, json={"stream_id": str(F1_A)}
    )
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
    assert len(dispatcher.take("sms.send")) == 1  # guardian gave SMS consent

    student_id = body["student"]["id"]
    student = (await client.get(f"{API}/students/{student_id}", headers=admin)).json()
    assert student["status"] == "ACTIVE" and student["enrolment"]["class_code"] == "F1"
    again = await client.post(
        f"{API}/enrolment-applications/{app_id}/approve", headers=admin, json={"stream_id": str(F1_A)}
    )
    assert again.status_code == 409
    download = await client.get(f"{API}/enrolment-documents/{photo2.json()['id']}/download", headers=validator)
    assert download.status_code == 200 and download.content == JPG


async def test_reject_and_list(client, admin, validator):
    listed = (await client.get(f"{API}/enrolment-applications?status=UNDER_REVIEW", headers=validator)).json()
    assert str(SEED_APPLICATION) in {a["id"] for a in listed["items"]}
    not_ready = await client.post(
        f"{API}/enrolment-applications/{SEED_APPLICATION}/approve", headers=admin, json={"stream_id": str(F1_A)}
    )
    assert not_ready.status_code == 422  # photo INVALID, PSLE PENDING
    rejected = await client.post(
        f"{API}/enrolment-applications/{SEED_APPLICATION}/reject",
        headers=admin,
        json={"reason": "Class is full for this year"},
    )
    assert rejected.json()["status"] == "REJECTED" and rejected.json()["decision_reason"]
    assert (
        await client.post(
            f"{API}/enrolment-applications/{SEED_APPLICATION}/cancel", headers=admin, json={"reason": "Too late"}
        )
    ).status_code == 409


async def test_parent_applies_and_only_sees_own_application(client, db, admin, dispatcher):
    parent = await parent_login(client, db, dispatcher, SCHOOL_A, u(2, 22), "255715000022")
    body = application(
        guardians=[],
        relationship="MOTHER",
        applicant={"first_name": "Zuhura", "last_name": "Hassan", "gender": "F", "date_of_birth": "2014-07-01"},
    )
    created = await client.post(f"{API}/enrolment-applications", headers=parent, json=body)
    assert created.status_code == 201, created.text
    app_id = created.json()["id"]
    assert (await client.get(f"{API}/enrolment-applications/{app_id}", headers=parent)).status_code == 200
    assert (await client.get(f"{API}/enrolment-applications/{SEED_APPLICATION}", headers=parent)).status_code == 404
    assert (await client.get(f"{API}/enrolment-applications", headers=parent)).status_code == 403
    assert (await upload(client, parent, app_id, BIRTH_CERT, PDF)).status_code == 201
    cancelled = await client.post(
        f"{API}/enrolment-applications/{app_id}/cancel", headers=parent, json={"reason": "We moved to Arusha"}
    )
    assert cancelled.json()["status"] == "CANCELLED"

    await client.patch(f"{API}/school", headers=admin, json={"is_open_for_enrolment": False})
    closed = await client.post(f"{API}/enrolment-applications", headers=parent, json=body)
    assert closed.status_code == 409 and closed.json()["details"][0]["code"] == "enrolment_closed"


async def _promote(client, admin, dispatcher, key: str, **body) -> dict:
    response = await client.post(f"{API}/promotions", headers={**admin, "Idempotency-Key": key}, json=body)
    assert response.status_code == 202, response.text
    [call] = dispatcher.take("promotions.run")
    await promotions.run_job(**call)
    return (await client.get(f"{API}/jobs/{response.json()['id']}", headers=admin)).json()


async def test_promotion_moves_repeats_and_graduates(client, db, admin, dispatcher):
    year = (
        await client.post(
            f"{API}/academic-years",
            headers=admin,
            json={"name": "2027", "start_date": "2027-01-01", "end_date": "2027-12-31"},
        )
    ).json()
    base = {"academic_year_from": str(YEAR_2026), "academic_year_to": year["id"]}

    failed = await _promote(client, admin, dispatcher, "promote-0001", class_id=str(F2), **base)
    assert failed["status"] == "FAILED" and failed["error_count"] == 6  # Form III has no stream yet

    f3 = next(c for c in (await client.get(f"{API}/classes", headers=admin)).json() if c["code"] == "F3")
    await client.post(f"{API}/streams", headers=admin, json={"class_id": f3["id"], "name": "A", "capacity": 45})
    repeater = u(6, 11)
    done = await _promote(
        client, admin, dispatcher, "promote-0002", class_id=str(F2), repeaters=[str(repeater)], **base
    )
    assert done["status"] == "SUCCEEDED" and done["processed_items"] == 6

    await as_school(db, SCHOOL_A)
    new = dict(
        (
            await db.execute(
                select(Enrolment.student_id, Enrolment.stream_id).where(Enrolment.academic_year_id == year["id"])
            )
        ).all()
    )
    assert new[repeater] == F2_A and len(new) == 6
    assert len({s for sid, s in new.items() if sid != repeater}) == 1  # F2 A and F2 B both join F3 A
    old = dict(
        (
            await db.execute(
                select(Enrolment.student_id, Enrolment.status).where(
                    Enrolment.academic_year_id == YEAR_2026, Enrolment.student_id.in_(list(new))
                )
            )
        ).all()
    )
    assert old[repeater] == "REPEATED" and {v for k, v in old.items() if k != repeater} == {"PROMOTED"}

    await client.patch(f"{API}/classes/{F5}", headers=admin, json={"next_class_id": None})
    graduated = await _promote(client, admin, dispatcher, "promote-0003", class_id=str(F5), **base)
    assert graduated["status"] == "SUCCEEDED"
    status = (await db.execute(select(Student.status).where(Student.id == u(6, 17)))).scalar()
    assert status == "GRADUATED"

    replay = await client.post(
        f"{API}/promotions", headers={**admin, "Idempotency-Key": "promote-0003"}, json={**base, "class_id": str(F5)}
    )
    assert replay.json()["id"] == graduated["id"] and dispatcher.sent == []
    assert date.fromisoformat(year["start_date"]).year == 2027
