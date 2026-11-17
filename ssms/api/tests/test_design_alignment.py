"""Rules taken from the first design: page size, Saturday lessons, default CA/exam split, grades, qualified teachers,
the Registrar role."""

from collections import Counter

import psycopg
import pytest

from app.models.enums import EducationLevelCode
from app.services.onboarding import DEFAULT_COMPONENTS, GRADING
from tests.conftest import TESTER_URL
from tests.helpers import (
    BMATH,
    F2_A,
    F2_B,
    ROOM_F2A,
    SCHOOL_A,
    SCHOOL_B,
    STAFF_LAIZER,
    STAFF_SALMA,
    TERM1,
    bearer,
    login,
    u,
)

API = "/api/v1"
CIV = u(15, 1)


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


def slot(**overrides) -> dict:
    body = {
        "term_id": str(TERM1),
        "stream_id": str(F2_A),
        "subject_id": str(CIV),
        "staff_id": str(STAFF_LAIZER),
        "room_id": str(ROOM_F2A),
        "day_of_week": 6,
        "time_start": "08:00",
        "time_end": "08:40",
    }
    body.update(overrides)
    return body


async def test_page_size_is_at_most_50(client, admin):
    assert (await client.get(f"{API}/students?limit=50", headers=admin)).status_code == 200
    assert (await client.get(f"{API}/students?limit=51", headers=admin)).status_code == 422


async def test_saturday_opens_only_when_the_term_has_saturday_lessons(client, admin):
    saturday, sunday = "2026-03-07", "2026-03-08"  # both inside Term One
    register = f"{API}/attendance/register?stream_id={F2_A}&date="
    closed = (await client.get(register + saturday, headers=admin)).json()
    assert closed["school_day"] is False and closed["reason"] == "weekend"

    created = await client.post(f"{API}/timetable/slots", headers=admin, json=slot())
    assert created.status_code == 201, created.text
    assert (await client.get(register + saturday, headers=admin)).json()["school_day"] is True
    assert (await client.get(register + sunday, headers=admin)).json()["reason"] == "weekend"
    sunday_slot = await client.post(f"{API}/timetable/slots", headers=admin, json=slot(day_of_week=7))
    assert sunday_slot.status_code == 422


def test_default_components_add_up_to_one_hundred():
    assert {c.value: w for c, _, _, w in DEFAULT_COMPONENTS} == {"CA": 40, "TERMINAL": 60}


def test_default_o_level_grades_match_the_design():
    bands = {band[0]: (band[1], band[2]) for band in GRADING[EducationLevelCode.O_LEVEL][2]}
    assert bands == {"A": (75, 100), "B": (65, 74), "C": (45, 64), "D": (30, 44), "F": (0, 29)}


async def test_slot_needs_a_qualified_teacher(client, admin):
    subjects = f"{API}/staff/{STAFF_LAIZER}/subjects"
    before = (await client.get(subjects, headers=admin)).json()
    assert str(CIV) in {s["subject_id"] for s in before}

    kept = [s["subject_id"] for s in before if s["subject_id"] != str(CIV)]
    saved = await client.put(subjects, headers=admin, json={"subject_ids": kept})
    assert saved.status_code == 200 and str(CIV) not in {s["subject_id"] for s in saved.json()}

    refused = await client.post(f"{API}/timetable/slots", headers=admin, json=slot(day_of_week=3))
    assert refused.status_code == 422 and "not_qualified" in {d["code"] for d in refused.json()["details"]}

    draft = await client.post(
        f"{API}/timetable/generate",
        headers=admin,
        json={"term_id": str(TERM1), "stream_ids": [str(F2_A), str(F2_B)], "replace": True},
    )
    reasons = Counter((x["reason"], x["subject_id"]) for x in draft.json()["unplaced"])
    assert reasons[("not_qualified", str(CIV))] >= 1

    # Giving the subject back works after the soft delete, and repeating it changes nothing.
    for _ in range(2):
        again = await client.put(subjects, headers=admin, json={"subject_ids": [*kept, str(CIV)]})
        assert again.status_code == 200 and str(CIV) in {s["subject_id"] for s in again.json()}
    assert (await client.post(f"{API}/timetable/slots", headers=admin, json=slot(day_of_week=3))).status_code == 201


async def test_qualifications_validate_input_and_permissions(client, admin):
    subjects = f"{API}/staff/{STAFF_SALMA}/subjects"
    assert (await client.put(subjects, headers=admin, json={"subject_ids": [str(u(15, 9999))]})).status_code == 404
    bursar = bearer(await login(client, username="bursar"))
    assert (await client.put(subjects, headers=bursar, json={"subject_ids": []})).status_code == 403


async def test_other_school_cannot_reach_a_teacher(client):
    other = bearer(await login(client, school="upendo-pri"))
    assert (await client.get(f"{API}/staff/{STAFF_SALMA}/subjects", headers=other)).status_code == 404


def test_staff_subjects_rls_as_ssms_app(database):
    url = TESTER_URL.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        conn.execute("SET ROLE ssms_app")
        assert conn.execute("SELECT count(*) FROM staff_subjects").fetchone()[0] == 0  # no context: fail closed
        conn.execute(f"SET LOCAL app.school_id = '{SCHOOL_B}'")
        assert conn.execute(f"SELECT count(*) FROM staff_subjects WHERE school_id = '{SCHOOL_A}'").fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO staff_subjects (school_id, staff_id, subject_id) VALUES (%s, %s, %s)",
                (SCHOOL_A, STAFF_SALMA, BMATH),
            )
        conn.rollback()


async def test_registrar_handles_students_but_not_money_or_marks(client):
    registrar = bearer(await login(client, username="registrar"))
    assert (await client.get(f"{API}/students", headers=registrar)).status_code == 200
    assert (await client.get(f"{API}/enrolment-applications", headers=registrar)).status_code == 200
    assert (await client.get(f"{API}/invoices", headers=registrar)).status_code == 403
    assert (await client.get(f"{API}/audit-logs", headers=registrar)).status_code == 403
