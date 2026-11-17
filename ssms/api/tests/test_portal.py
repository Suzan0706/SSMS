"""Parent and student portals (/me), as ssms_app: own family only, small answers."""

from datetime import date

import pytest

from app.services import calendar
from tests.helpers import SCHOOL_A, bearer, login, parent_login, u

API = "/api/v1"
LYIMO, LYIMO_PHONE = u(2, 23), "255765000023"  # father of Baraka (Form II A) and Emmanuel (Form V PCM)
BARAKA, EMMANUEL, AMANI = u(6, 13), u(6, 17), u(6, 11)


@pytest.fixture(autouse=True)
def seeded_day(monkeypatch):
    monkeypatch.setattr(calendar, "today", lambda: date(2026, 3, 2))  # seed: registers and gate taps that Monday


async def test_parent_children_with_today_and_details(client, db, dispatcher):
    parent = await parent_login(client, db, dispatcher, SCHOOL_A, LYIMO, LYIMO_PHONE)
    response = await client.get(f"{API}/me/children", headers=parent)
    assert response.status_code == 200 and len(response.content) < 5_000
    children = {c["student_id"]: c for c in response.json()}
    assert set(children) == {str(BARAKA), str(EMMANUEL)}
    assert (children[str(BARAKA)]["today_status"], children[str(BARAKA)]["gate_in_at"]) == ("ABSENT", None)
    assert children[str(BARAKA)]["class_code"] == "F2" and children[str(BARAKA)]["stream_id"] == str(u(19, 2))

    month = await client.get(f"{API}/students/{BARAKA}/attendance?from=2026-03-01&to=2026-03-31", headers=parent)
    assert month.json()["absent"] == 3
    assert (
        await client.get(f"{API}/students/{AMANI}/attendance?from=2026-03-01&to=2026-03-31", headers=parent)
    ).status_code == 403
    assert (await client.get(f"{API}/me/student", headers=parent)).status_code == 403


async def test_student_home_and_timetable(client):
    emmanuel = bearer(await login(client, username="mf-2026-0003"))
    home = (await client.get(f"{API}/me/student", headers=emmanuel)).json()
    assert home["student_id"] == str(EMMANUEL) and home["class_code"] == "F5" and home["stream_name"] == "PCM"
    lessons = (await client.get(f"{API}/me/timetable", headers=emmanuel)).json()
    assert lessons and {lesson["subject_code"] for lesson in lessons} >= {"AMATH"}
    assert all(lesson["room"] and lesson["teacher"] for lesson in lessons)
    own = await client.get(f"{API}/students/{EMMANUEL}/attendance?from=2026-03-01&to=2026-03-31", headers=emmanuel)
    assert own.status_code == 200
    other = await client.get(f"{API}/students/{BARAKA}/attendance?from=2026-03-01&to=2026-03-31", headers=emmanuel)
    assert other.status_code == 403
