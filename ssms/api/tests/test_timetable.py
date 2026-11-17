"""Teaching assignments, timetable check/create/generate (with database EXCLUDE as final guard), exams."""

from collections import Counter
from itertools import combinations

import pytest

from tests.helpers import (
    AMATH,
    BIO,
    BMATH,
    ENG,
    F2,
    F2_A,
    F2_B,
    PHY,
    ROOM_F2A,
    ROOM_HALL,
    ROOM_LAB_PHY,
    STAFF_KIMARO,
    STAFF_LAIZER,
    STAFF_SALMA,
    TERM1,
    YEAR_2026,
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
        "day_of_week": 3,
        "time_start": "08:00",
        "time_end": "08:40",
    }
    body.update({k: str(v) if hasattr(v, "hex") else v for k, v in overrides.items()})
    return body


async def test_check_reports_clashes_and_free_periods(client, admin):
    result = (
        await client.post(
            f"{API}/timetable/check",
            headers=admin,
            json=slot(
                stream_id=F2_B,
                subject_id=ENG,
                staff_id=STAFF_SALMA,
                room_id=u(18, 2),
                day_of_week=1,
                time_start="08:40",
                time_end="09:20",
            ),
        )
    ).json()
    assert result["ok"] is False
    assert {c["kind"] for c in result["conflicts"]} == {"teacher", "stream", "room"}  # F2B Maths uses that room
    free = {(p["time_start"], p["time_end"]) for p in result["free_periods"]}
    assert ("08:00:00", "08:40:00") not in free and ("09:20:00", "10:00:00") in free


async def test_check_reports_rule_problems(client, admin):
    wrong_room = (
        await client.post(
            f"{API}/timetable/check", headers=admin, json=slot(subject_id=PHY, staff_id=STAFF_KIMARO, room_id=ROOM_F2A)
        )
    ).json()
    assert [p["code"] for p in wrong_room["problems"]] == ["room_type"]
    wrong_teacher = (
        await client.post(
            f"{API}/timetable/check",
            headers=admin,
            json=slot(subject_id=BIO, staff_id=STAFF_SALMA, room_id=ROOM_LAB_PHY),
        )
    ).json()
    assert [p["code"] for p in wrong_teacher["problems"]] == ["not_assigned", "not_qualified"]
    not_taught = (await client.post(f"{API}/timetable/check", headers=admin, json=slot(subject_id=AMATH))).json()
    assert {p["code"] for p in not_taught["problems"]} == {"not_assigned", "not_qualified", "not_in_curriculum"}
    assert (await client.post(f"{API}/timetable/check", headers=admin, json=slot())).json()["ok"] is True


async def test_create_update_delete_slot(client, admin):
    created = await client.post(f"{API}/timetable/slots", headers=admin, json=slot())
    assert created.status_code == 201
    clash = await client.post(f"{API}/timetable/slots", headers=admin, json=slot())
    assert clash.status_code == 409 and clash.json()["error_code"] == "TIMETABLE_CLASH"
    problem = await client.post(
        f"{API}/timetable/slots", headers=admin, json=slot(subject_id=PHY, staff_id=STAFF_KIMARO, day_of_week=4)
    )
    assert problem.status_code == 422 and problem.json()["error_code"] == "RULE_VIOLATION"
    moved = await client.patch(
        f"{API}/timetable/slots/{created.json()['id']}",
        headers=admin,
        json={"time_start": "08:20", "time_end": "09:00"},
    )  # overlaps only itself
    assert moved.status_code == 200 and moved.json()["time_start"] == "08:20:00"
    assert (
        await client.delete(f"{API}/timetable/slots/{created.json()['id']}?reason=Moved", headers=admin)
    ).status_code == 204


async def test_teacher_load_limit(client, admin):
    await client.patch(f"{API}/staff/{STAFF_LAIZER}", headers=admin, json={"max_periods_per_week": 1})
    assert (await client.post(f"{API}/timetable/slots", headers=admin, json=slot())).status_code == 201
    second = await client.post(f"{API}/timetable/slots", headers=admin, json=slot(day_of_week=4))
    assert second.status_code == 422 and second.json()["details"][0]["code"] == "teacher_load"


async def test_timetable_etag_and_permissions(client, admin):
    first = await client.get(f"{API}/timetable?term_id={TERM1}&stream_id={F2_A}", headers=admin)
    assert first.status_code == 200 and len(first.json()) == 3
    etag = first.headers["etag"]
    same = await client.get(
        f"{API}/timetable?term_id={TERM1}&stream_id={F2_A}", headers={**admin, "If-None-Match": etag}
    )
    assert same.status_code == 304
    await client.post(f"{API}/timetable/slots", headers=admin, json=slot())
    changed = await client.get(
        f"{API}/timetable?term_id={TERM1}&stream_id={F2_A}", headers={**admin, "If-None-Match": etag}
    )
    assert changed.status_code == 200 and changed.headers["etag"] != etag
    teacher = bearer(await login(client, username="tch.salma"))
    mine = await client.get(f"{API}/timetable?term_id={TERM1}&staff_id={STAFF_SALMA}", headers=teacher)
    assert mine.status_code == 200 and len(mine.json()) == 2
    assert (await client.post(f"{API}/timetable/check", headers=teacher, json=slot())).status_code == 403


async def test_generator_fills_two_streams_without_clashes(client, admin):
    draft = (
        await client.post(
            f"{API}/timetable/generate",
            headers=admin,
            json={"term_id": str(TERM1), "stream_ids": [str(F2_A), str(F2_B)], "replace": True},
        )
    ).json()
    assert draft["persisted"] is False and draft["unplaced"] == []
    placed = draft["placed"]
    assert len(placed) == 64  # 32 periods per Form II stream
    per_subject = Counter((p["stream_id"], p["subject_id"]) for p in placed)
    assert per_subject[(str(F2_A), str(BMATH))] == 6 and per_subject[(str(F2_B), str(CIV))] == 2
    for a, b in combinations(placed, 2):
        if a["day_of_week"] == b["day_of_week"] and a["time_start"] == b["time_start"]:
            assert a["staff_id"] != b["staff_id"] and a["room_id"] != b["room_id"] and a["stream_id"] != b["stream_id"]
    lab = {p["room_id"] for p in placed if p["subject_id"] == str(PHY)}
    assert lab <= {str(ROOM_LAB_PHY), str(u(18, 5))}  # laboratory subjects go to laboratories

    saved = (
        await client.post(
            f"{API}/timetable/generate",
            headers=admin,
            json={"term_id": str(TERM1), "stream_ids": [str(F2_A), str(F2_B)], "replace": True, "persist": True},
        )
    ).json()
    assert saved["persisted"] is True
    stored = (await client.get(f"{API}/timetable?term_id={TERM1}&stream_id={F2_A}", headers=admin)).json()
    assert len(stored) == 32


async def test_generator_reports_what_it_cannot_place(client, admin):
    await client.put(
        f"{API}/teaching-assignments?academic_year_id={YEAR_2026}&stream_id={F2_A}",
        headers=admin,
        json=[{"subject_id": str(BMATH), "staff_id": str(u(8, 3))}],
    )
    draft = (
        await client.post(
            f"{API}/timetable/generate",
            headers=admin,
            json={"term_id": str(TERM1), "stream_ids": [str(F2_A)], "replace": True},
        )
    ).json()
    reasons = Counter(x["reason"] for x in draft["unplaced"])
    assert reasons == {"not_assigned": 8} and len(draft["placed"]) == 6


async def test_teaching_assignments(client, admin):
    listed = (
        await client.get(f"{API}/teaching-assignments?academic_year_id={YEAR_2026}&stream_id={F2_A}", headers=admin)
    ).json()
    assert len(listed) == 9 and {a["subject_code"] for a in listed} >= {"BMATH", "PHY"}
    kimaro = bearer(await login(client, username="tch.kimaro"))
    mine = (
        await client.get(f"{API}/teaching-assignments?academic_year_id={YEAR_2026}&mine=true", headers=kimaro)
    ).json()
    assert {a["subject_code"] for a in mine} == {"PHY", "CHEM", "BIO", "PHY-A", "CHEM-A"}
    await client.patch(f"{API}/staff/{STAFF_SALMA}", headers=admin, json={"status": "ON_LEAVE"})
    inactive = await client.put(
        f"{API}/teaching-assignments?academic_year_id={YEAR_2026}&stream_id={F2_A}",
        headers=admin,
        json=[{"subject_id": str(ENG), "staff_id": str(STAFF_SALMA)}],
    )
    assert inactive.status_code == 422


async def test_exam_sessions_and_papers(client, admin):
    outside = await client.post(
        f"{API}/exam-sessions",
        headers=admin,
        json={
            "term_id": str(TERM1),
            "name_en": "Terminal",
            "name_sw": "Muhula",
            "kind": "TERMINAL",
            "start_date": "2026-06-01",
            "end_date": "2026-06-20",
        },
    )
    assert outside.status_code == 422 and outside.json()["details"][0]["code"] == "outside_term"
    terminal = (
        await client.post(
            f"{API}/exam-sessions",
            headers=admin,
            json={
                "term_id": str(TERM1),
                "name_en": "Terminal exams",
                "name_sw": "Mitihani ya muhula",
                "kind": "TERMINAL",
                "start_date": "2026-05-25",
                "end_date": "2026-06-05",
            },
        )
    ).json()
    paper = {
        "exam_session_id": terminal["id"],
        "class_id": str(F2),
        "subject_id": str(BIO),
        "room_id": str(ROOM_HALL),
        "exam_date": "2026-05-25",
        "time_start": "08:00",
        "time_end": "10:30",
    }
    wrong_day = await client.post(f"{API}/exams", headers=admin, json={**paper, "exam_date": "2026-06-10"})
    assert wrong_day.status_code == 422 and wrong_day.json()["details"][0]["code"] == "outside_session"
    assert (await client.post(f"{API}/exams", headers=admin, json=paper)).status_code == 201
    clash = await client.post(
        f"{API}/exams",
        headers=admin,
        json={**paper, "subject_id": str(PHY), "time_start": "09:00", "time_end": "11:00"},
    )
    assert clash.status_code == 409
    listed = (await client.get(f"{API}/exams?exam_session_id={terminal['id']}", headers=admin)).json()
    assert len(listed) == 1
    teacher = bearer(await login(client, username="tch.salma"))
    assert (await client.get(f"{API}/exams?class_id={F2}", headers=teacher)).status_code == 200
    assert (await client.post(f"{API}/exams", headers=teacher, json=paper)).status_code == 403
