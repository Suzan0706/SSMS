"""Candidate numbers, admit cards, the exam timetable PDF and subject ranking (FR-84, FR-85, FR-86)."""

import pytest
from sqlalchemy import select

from app.models import ResultPublication
from tests.helpers import BMATH, F2, SCHOOL_A, as_school, bearer, login, u

API = "/api/v1"
MIDTERM = u(26, 1)  # Form II mid-term, March 2026: Basic Maths, English, Physics


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


@pytest.fixture
async def teacher(client) -> dict:
    return bearer(await login(client, username="tch.salma"))  # teacher only (Mwita is also head of department)


async def test_candidates_are_numbered_once_in_class_and_name_order(client, admin, teacher):
    before = (await client.get(f"{API}/exam-sessions/{MIDTERM}/candidates", headers=teacher)).json()
    assert before and all(c["candidate_no"] is None and c["class_code"] == "F2" for c in before)
    assert (await client.post(f"{API}/exam-sessions/{MIDTERM}/candidates", headers=teacher, json={})).status_code == 403
    early = await client.get(f"{API}/exam-sessions/{MIDTERM}/admit-cards.pdf", headers=admin)
    assert early.status_code == 409  # no numbers yet, no cards

    numbered = await client.post(f"{API}/exam-sessions/{MIDTERM}/candidates", headers=admin, json={})
    assert numbered.status_code == 200 and numbered.json()["numbered"] == len(before)
    after = (await client.get(f"{API}/exam-sessions/{MIDTERM}/candidates", headers=admin)).json()
    numbers = [c["candidate_no"] for c in after]
    assert numbers == sorted(numbers) and numbers[0] == "S.4521-0001" and len(set(numbers)) == len(numbers)
    again = await client.post(f"{API}/exam-sessions/{MIDTERM}/candidates", headers=admin, json={"prefix": "X-"})
    assert again.json()["numbered"] == 0  # numbers already given are kept

    cards = await client.get(f"{API}/exam-sessions/{MIDTERM}/admit-cards.pdf?class_id={F2}", headers=admin)
    assert cards.status_code == 200 and cards.content.startswith(b"%PDF")
    assert cards.headers["content-type"] == "application/pdf"
    assert (await client.get(f"{API}/exam-sessions/{MIDTERM}/admit-cards.pdf", headers=teacher)).status_code == 403


async def test_a_student_downloads_only_their_own_admit_card(client, db, dispatcher, admin):
    await client.post(f"{API}/exam-sessions/{MIDTERM}/candidates", headers=admin, json={})
    amani = bearer(await login(client, username="mf-2025-0014"))  # Form II
    own = await client.get(f"{API}/portal/admit-card.pdf?exam_session_id={MIDTERM}", headers=amani)
    assert own.status_code == 200 and own.content.startswith(b"%PDF")
    emmanuel = bearer(await login(client, username="mf-2026-0003"))  # Form V: no paper in this session
    assert (
        await client.get(f"{API}/portal/admit-card.pdf?exam_session_id={MIDTERM}", headers=emmanuel)
    ).status_code == 409
    assert (
        await client.get(f"{API}/portal/admit-card.pdf?exam_session_id={MIDTERM}", headers=admin)
    ).status_code == 403


async def test_the_exam_timetable_prints_in_either_language(client, teacher):
    for lang in ("sw", "en"):
        pdf = await client.get(f"{API}/exam-sessions/{MIDTERM}/timetable.pdf?lang={lang}", headers=teacher)
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and len(pdf.content) > 800
    assert (await client.get(f"{API}/exam-sessions/{u(26, 99)}/timetable.pdf", headers=teacher)).status_code == 404


async def test_subject_ranking_lists_a_subject_best_first(client, db, teacher):
    await as_school(db, SCHOOL_A)
    term = (await db.execute(select(ResultPublication.term_id).where(ResultPublication.class_id == F2))).scalar()
    ranking = (
        await client.get(
            f"{API}/results/subject-ranking?term_id={term}&class_id={F2}&subject_id={BMATH}", headers=teacher
        )
    ).json()
    assert ranking[0]["position"] == 1 and len(ranking) >= 5
    positions = [r["position"] for r in ranking]
    scores = [r["score"] for r in ranking]
    assert positions == sorted(positions) and scores == sorted(scores, reverse=True)
    amani = bearer(await login(client, username="mf-2025-0014"))
    blocked = await client.get(
        f"{API}/results/subject-ranking?term_id={term}&class_id={F2}&subject_id={BMATH}", headers=amani
    )
    assert blocked.status_code == 403


async def test_a_student_sees_the_sessions_with_an_admit_card(client, admin):
    amani = bearer(await login(client, username="mf-2025-0014"))
    assert (await client.get(f"{API}/portal/exam-sessions", headers=amani)).json() == []
    await client.post(f"{API}/exam-sessions/{MIDTERM}/candidates", headers=admin, json={})
    mine = (await client.get(f"{API}/portal/exam-sessions", headers=amani)).json()
    assert [s["id"] for s in mine] == [str(MIDTERM)] and mine[0]["candidate_no"].startswith("S.4521-")
    assert (await client.get(f"{API}/portal/exam-sessions", headers=admin)).status_code == 403
