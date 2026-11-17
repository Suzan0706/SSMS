from datetime import time
from itertools import combinations

from sqlalchemy import func, select

from app.models import EnrolmentSchedule
from app.models.enums import RoomType
from app.services.scheduling import (DEFAULT_PERIODS, Block, RoomInfo, generate_timetable)

API = "/api/v1"

# Seed: Mwita (instructor 1) teaches Form II A Basic Maths Mon 08:00-08:40 in room F2A (schedule 1).
BASE = {"offering_id": 1, "stream": "A", "term_id": 1, "subject_id": 9, "instructor_id": 1,
        "room_id": 1, "day_of_week": 1, "time_start": "08:20", "time_end": "09:00"}


def test_instructor_clash_is_409_and_names_the_session(client, as_admin):
    r = client.post(f"{API}/schedules", headers=as_admin, json=BASE)
    assert r.status_code == 409, r.text
    conflicts = r.json()["detail"]["conflicts"]
    assert {"kind": "INSTRUCTOR", "schedule_id": 1, "message": "Instructor already teaching"} in conflicts


def test_back_to_back_periods_do_not_clash(client, as_admin):
    # Mwita: Wed 08:00-08:40 (seed) then Wed 08:40-09:20 here
    r = client.post(f"{API}/schedules", headers=as_admin,
                    json={**BASE, "day_of_week": 3, "time_start": "08:40", "time_end": "09:20"})
    assert r.status_code == 201, r.text


def test_room_clash_reported_by_check(client, as_admin):
    r = client.post(f"{API}/schedules/check", headers=as_admin,
                    json={**BASE, "instructor_id": 2, "subject_id": 5, "room_id": 2, "time_start": "08:10",
                          "time_end": "08:30"})
    assert r.status_code == 200
    assert not r.json()["ok"]
    assert any(c["kind"] == "ROOM" for c in r.json()["conflicts"])


def test_unqualified_instructor_is_422(client, as_admin):
    # Salma (instructor 2) teaches English and Kiswahili, not Physics
    r = client.post(f"{API}/schedules", headers=as_admin,
                    json={**BASE, "instructor_id": 2, "subject_id": 6, "room_id": 4, "day_of_week": 4})
    assert r.status_code == 422
    assert "Instructor is not qualified for this subject" in r.json()["detail"]["problems"]


def test_laboratory_subject_needs_a_laboratory(client, as_admin):
    r = client.post(f"{API}/schedules", headers=as_admin,
                    json={**BASE, "instructor_id": 3, "subject_id": 6, "room_id": 1, "day_of_week": 4})
    assert r.status_code == 422
    assert any("LABORATORY" in p for p in r.json()["detail"]["problems"])


def test_new_session_links_the_streams_confirmed_students(client, db, as_admin):
    # Form II A (offering 2) has two confirmed students
    r = client.post(f"{API}/schedules", headers=as_admin,
                    json={"offering_id": 2, "stream": "A", "term_id": 1, "subject_id": 7, "instructor_id": 3,
                          "room_id": 5, "day_of_week": 4, "time_start": "08:00", "time_end": "09:20"})
    assert r.status_code == 201, r.text
    linked = db.scalar(select(func.count()).select_from(EnrolmentSchedule)
                       .where(EnrolmentSchedule.schedule_id == r.json()["schedule_id"]))
    assert linked == 2


def test_only_admin_schedules(client, as_registrar):
    assert client.post(f"{API}/schedules", headers=as_registrar, json=BASE).status_code == 403


# ---------- schedulingAlgo (pure function) ----------
def _blocks():
    blocks = []
    for offering in (1, 2):                      # two classes share two instructors and one lab
        blocks += [Block(offering, "A", 9, 101, 1, RoomType.CLASSROOM, 40, morning=True) for _ in range(6)]
        blocks += [Block(offering, "A", 5, 102, 1, RoomType.CLASSROOM, 40) for _ in range(5)]
        blocks += [Block(offering, "A", 6, 103, 2, RoomType.LABORATORY, 40) for _ in range(2)]
    return blocks


ROOMS = [RoomInfo(1, RoomType.CLASSROOM, 45), RoomInfo(2, RoomType.CLASSROOM, 45), RoomInfo(4, RoomType.LABORATORY, 40)]


def _cells(pl):
    return {(pl.day, p) for p in range(pl.first, pl.first + pl.block.length)}


def test_generator_places_everything_without_clashes():
    placed, unplaced = generate_timetable(_blocks(), ROOMS)
    assert unplaced == []
    assert len(placed) == len(_blocks())
    for a, b in combinations(placed, 2):
        if _cells(a) & _cells(b):
            assert a.block.instructor_id != b.block.instructor_id
            assert a.room_id != b.room_id
            assert a.block.class_key != b.block.class_key
    labs = [pl for pl in placed if pl.block.room_type == RoomType.LABORATORY]
    assert all(pl.room_id == 4 for pl in labs)
    # double periods never span the 10:00 break or lunch
    for pl in labs:
        assert DEFAULT_PERIODS[pl.first].end == DEFAULT_PERIODS[pl.first + 1].start


def test_generator_spreads_a_subject_over_the_week():
    placed, _ = generate_timetable(_blocks(), ROOMS)
    maths_days = [pl.day for pl in placed if pl.block.subject_id == 9 and pl.block.offering_id == 1]
    assert len(set(maths_days)) == 5                     # 6 periods over 5 days: every day used


def test_generator_reports_what_cannot_be_placed():
    no_lab = [r for r in ROOMS if r.room_type != RoomType.LABORATORY]
    placed, unplaced = generate_timetable(_blocks(), no_lab)
    assert {b.subject_id for b in unplaced} == {6}
    assert all(pl.block.subject_id != 6 for pl in placed)


def test_generate_endpoint_returns_a_clash_free_draft(client, as_admin):
    r = client.post(f"{API}/schedules/generate", headers=as_admin,
                    json={"term_id": 1, "offering_ids": [1], "streams": ["A"], "persist": False})
    assert r.status_code == 200, r.text
    placed = r.json()["placed"]
    assert placed and not r.json()["persisted"]
    slots = [(p["day_of_week"], p["time_start"]) for p in placed]
    assert len(slots) == len(set(slots))                 # one lesson per class per period
    assert all(time.fromisoformat(p["time_start"]) >= time(8, 0) for p in placed)
