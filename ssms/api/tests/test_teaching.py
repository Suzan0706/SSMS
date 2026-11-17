"""Study materials, homework and submissions, lesson attendance and the monthly sheet (FR-82, FR-83, FR-90..93)."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import (
    BMATH,
    ENG,
    F2_A,
    F2_B,
    F5_PCM,
    GUARDIAN_A,
    SCHOOL_A,
    SHARED_PHONE,
    bearer,
    login,
    parent_login,
    u,
)

API = "/api/v1"
AMANI, BARAKA, REHEMA = u(6, 11), u(6, 13), u(6, 14)
PDF = b"%PDF-1.4\n% notes\n"
MONDAY = "2026-03-02"  # F2A Basic Maths with Mwita, 08:00, Term One


@pytest.fixture
async def mwita(client) -> dict:
    return bearer(await login(client, username="tch.mwita"))  # Basic Maths in F2A and F2B


@pytest.fixture
async def salma(client) -> dict:
    return bearer(await login(client, username="tch.salma"))  # English, not Basic Maths


@pytest.fixture
async def amani(client) -> dict:
    return bearer(await login(client, username="mf-2025-0014"))  # student in F2A


async def upload(client, headers, purpose: str, name="notes.pdf", data=PDF) -> str:
    response = await client.post(
        f"{API}/files", headers=headers, data={"purpose": purpose}, files={"file": (name, data)}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def due(hours: int) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


# ---------------------------------------------------------------- materials


async def test_a_teacher_publishes_materials_only_to_classes_they_teach(client, mwita, salma, amani):
    file_id = await upload(client, mwita, "STUDY_MATERIAL")
    body = {"subject_id": str(BMATH), "stream_ids": [str(F2_A)], "title": "Fractions notes", "file_id": file_id}
    made = await client.post(f"{API}/materials", headers=mwita, json=body)
    assert made.status_code == 201, made.text
    link = {
        "subject_id": str(BMATH),
        "stream_ids": [str(F2_A), str(F2_B)],
        "title": "Video",
        "link_url": "https://example.org/v",
    }
    assert (await client.post(f"{API}/materials", headers=mwita, json=link)).status_code == 201

    not_his = await client.post(f"{API}/materials", headers=mwita, json={**body, "stream_ids": [str(F5_PCM)]})
    assert not_his.status_code == 403
    assert (
        await client.post(
            f"{API}/materials", headers=salma, json={**body, "file_id": None, "link_url": "https://x.org"}
        )
    ).status_code == 403
    both = await client.post(f"{API}/materials", headers=mwita, json={**body, "link_url": "https://example.org"})
    assert both.status_code == 422
    plain_http = await client.post(f"{API}/materials", headers=mwita, json={**link, "link_url": "http://example.org"})
    assert plain_http.status_code == 422
    salma_file = await upload(client, salma, "STUDY_MATERIAL")
    someone_elses = await client.post(f"{API}/materials", headers=mwita, json={**body, "file_id": salma_file})
    assert someone_elses.status_code == 422

    mine = (await client.get(f"{API}/materials/mine", headers=amani)).json()
    assert {m["title"] for m in mine} == {"Fractions notes", "Video"}
    notes = next(m for m in mine if m["title"] == "Fractions notes")
    assert notes["file_name"] == "notes.pdf" and notes["streams"] == ["F2 A"]
    got = await client.get(f"{API}/materials/{notes['id']}/file", headers=amani)
    assert got.status_code == 200 and got.content == PDF

    emmanuel = bearer(await login(client, username="mf-2026-0003"))  # F5: not a target
    assert (await client.get(f"{API}/materials/mine", headers=emmanuel)).json() == []
    assert (await client.get(f"{API}/materials/{notes['id']}/file", headers=emmanuel)).status_code == 404
    assert (await client.delete(f"{API}/materials/{notes['id']}", headers=salma)).status_code == 403
    assert (await client.delete(f"{API}/materials/{notes['id']}", headers=mwita)).status_code == 204
    assert len((await client.get(f"{API}/materials/mine", headers=amani)).json()) == 1


# ---------------------------------------------------------------- homework


async def test_homework_is_set_submitted_marked_and_seen_by_the_parent(client, db, dispatcher, mwita, salma, amani):
    # signing the parent in first gives the seeded guardian a real (encrypted) phone, so the SMS can be sent
    parent = await parent_login(client, db, dispatcher, SCHOOL_A, GUARDIAN_A, SHARED_PHONE)
    made = await client.post(
        f"{API}/homework",
        headers=mwita,
        json={
            "subject_id": str(BMATH),
            "stream_ids": [str(F2_A)],
            "title": "Exercise 4",
            "instructions": "Questions 1-10",
            "max_score": "10",
            "due_at": due(48),
            "notify_parents": True,
        },
    )
    assert made.status_code == 201, made.text
    homework_id = made.json()["id"]
    assert made.json()["sms_queued"] >= 1
    texts = [call["sms_id"] for call in dispatcher.take("sms.send")]
    assert len(texts) == made.json()["sms_queued"]

    todo = (await client.get(f"{API}/homework/mine", headers=amani)).json()
    assert todo[0]["title"] == "Exercise 4" and todo[0]["submission"] is None and todo[0]["overdue"] is False

    empty = await client.put(f"{API}/homework/{homework_id}/submission", headers=amani, json={"body": "  "})
    assert empty.status_code == 422
    answer_file = await upload(client, amani, "SUBMISSION", name="answers.pdf")
    handed = await client.put(
        f"{API}/homework/{homework_id}/submission", headers=amani, json={"body": "1) 3/4", "file_id": answer_file}
    )
    assert handed.status_code == 200 and handed.json()["is_late"] is False
    again = await client.put(f"{API}/homework/{homework_id}/submission", headers=amani, json={"body": "1) 3/4, 2) 1/2"})
    assert again.status_code == 200 and again.json()["id"] == handed.json()["id"]  # replaced, not duplicated

    roster = (await client.get(f"{API}/homework/{homework_id}/submissions", headers=mwita)).json()
    amani_row = next(r for r in roster if r["student_id"] == str(AMANI))
    assert amani_row["submission"]["body"] == "1) 3/4, 2) 1/2" and len(roster) >= 4
    assert (await client.get(f"{API}/homework/{homework_id}/submissions", headers=salma)).status_code == 403

    submission_id = amani_row["submission"]["id"]
    too_high = await client.patch(f"{API}/homework/submissions/{submission_id}", headers=mwita, json={"score": "11"})
    assert too_high.status_code == 422
    assert (
        await client.patch(f"{API}/homework/submissions/{submission_id}", headers=salma, json={"score": "5"})
    ).status_code == 403
    marked = await client.patch(
        f"{API}/homework/submissions/{submission_id}", headers=mwita, json={"score": "8.5", "feedback": "Vizuri"}
    )
    assert marked.status_code == 200 and marked.json()["score"] == "8.5"
    locked = await client.put(f"{API}/homework/{homework_id}/submission", headers=amani, json={"body": "late change"})
    assert locked.status_code == 409

    seen = (await client.get(f"{API}/homework/mine", headers=parent)).json()
    assert seen[0]["student_id"] == str(AMANI) and seen[0]["submission"]["feedback"] == "Vizuri"
    assert (
        await client.put(f"{API}/homework/{homework_id}/submission", headers=parent, json={"body": "x"})
    ).status_code == 403

    listed = (await client.get(f"{API}/homework", headers=mwita)).json()
    assert listed[0]["submitted"] == 1 and listed[0]["marked"] == 1 and listed[0]["expected"] >= 4


async def test_late_submissions_are_flagged_and_cannot_be_replaced(client, mwita, amani):
    made = await client.post(
        f"{API}/homework",
        headers=mwita,
        json={
            "subject_id": str(BMATH),
            "stream_ids": [str(F2_A)],
            "title": "Past due",
            "instructions": "Already due",
            "due_at": due(-1),
        },
    )
    homework_id = made.json()["id"]
    assert (await client.get(f"{API}/homework/mine", headers=amani)).json()[0]["overdue"] is True
    first = await client.put(f"{API}/homework/{homework_id}/submission", headers=amani, json={"body": "sorry, late"})
    assert first.status_code == 200 and first.json()["is_late"] is True
    second = await client.put(f"{API}/homework/{homework_id}/submission", headers=amani, json={"body": "changed"})
    assert second.status_code == 409


# ---------------------------------------------------------------- lesson attendance and the monthly sheet


async def test_the_lesson_teacher_takes_the_register_for_that_lesson_only(client, mwita, salma):
    lessons = (await client.get(f"{API}/attendance/lessons?on={MONDAY}", headers=mwita)).json()
    lesson = next(item for item in lessons if item["stream"] == "F2 A")
    assert lesson["marked"] == 0 and lesson["expected"] >= 4
    slot = lesson["slot_id"]
    roster = (await client.get(f"{API}/attendance/lessons/{slot}?on={MONDAY}", headers=mwita)).json()
    marks = [{"student_id": r["student_id"], "status": "PRESENT"} for r in roster]
    marks[0]["status"] = "ABSENT"
    assert (
        await client.put(f"{API}/attendance/lessons/{slot}?on={MONDAY}", headers=mwita, json={"marks": marks})
    ).status_code == 204
    marks[0]["status"] = "LATE"  # a correction updates the same record
    assert (
        await client.put(f"{API}/attendance/lessons/{slot}?on={MONDAY}", headers=mwita, json={"marks": marks})
    ).status_code == 204
    after = (await client.get(f"{API}/attendance/lessons/{slot}?on={MONDAY}", headers=mwita)).json()
    assert after[0]["status"] == "LATE" and all(r["status"] for r in after)
    assert next(
        i
        for i in (await client.get(f"{API}/attendance/lessons?on={MONDAY}", headers=mwita)).json()
        if i["slot_id"] == slot
    )["marked"] == len(after)

    assert (await client.get(f"{API}/attendance/lessons/{slot}?on={MONDAY}", headers=salma)).status_code == 403
    tuesday = await client.get(f"{API}/attendance/lessons/{slot}?on=2026-03-03", headers=mwita)
    assert tuesday.status_code == 422  # this slot is on Mondays
    stranger = [{"student_id": str(u(6, 17)), "status": "PRESENT"}]  # Emmanuel is in F5
    assert (
        await client.put(f"{API}/attendance/lessons/{slot}?on={MONDAY}", headers=mwita, json={"marks": stranger})
    ).status_code == 422


async def test_the_monthly_sheet_matches_the_class_register(client, mwita, amani):
    sheet = (
        await client.get(f"{API}/attendance/monthly-sheet?stream_id={F2_A}&year=2026&month=3", headers=mwita)
    ).json()
    assert sheet["stream"] == "F2 A" and sheet["days"] == [
        "2026-03-02",
        "2026-03-03",
        "2026-03-04",
        "2026-03-05",
        "2026-03-06",
    ]
    baraka = next(r for r in sheet["rows"] if r["student_id"] == str(BARAKA))
    rehema = next(r for r in sheet["rows"] if r["student_id"] == str(REHEMA))
    assert (baraka["absent"], baraka["present"]) == (3, 2) and baraka["marks"]["2026-03-02"] == "A"
    assert (rehema["late"], rehema["present"]) == (1, 4) and rehema["marks"]["2026-03-03"] == "L"
    assert (
        await client.get(f"{API}/attendance/monthly-sheet?stream_id={F2_A}&year=2026&month=3", headers=amani)
    ).status_code == 403


async def test_english_teacher_cannot_set_maths_homework(client, salma):
    body = {
        "subject_id": str(BMATH),
        "stream_ids": [str(F2_A)],
        "title": "Insha",
        "instructions": "Andika insha",
        "due_at": due(5),
    }
    assert (await client.post(f"{API}/homework", headers=salma, json=body)).status_code == 403
    assert (
        await client.post(f"{API}/homework", headers=salma, json={**body, "subject_id": str(ENG)})
    ).status_code == 201


async def test_homework_and_answer_files_reach_only_the_right_people(client, mwita, salma, amani):
    sheet = await upload(client, mwita, "HOMEWORK", name="sheet.pdf")
    made = await client.post(
        f"{API}/homework",
        headers=mwita,
        json={
            "subject_id": str(BMATH),
            "stream_ids": [str(F2_A)],
            "title": "Worksheet",
            "instructions": "Do the sheet",
            "file_id": sheet,
            "due_at": due(24),
        },
    )
    homework_id = made.json()["id"]
    assert (await client.get(f"{API}/homework/{homework_id}/file", headers=amani)).content == PDF
    emmanuel = bearer(await login(client, username="mf-2026-0003"))  # F5: not given this homework
    assert (await client.get(f"{API}/homework/{homework_id}/file", headers=emmanuel)).status_code == 404

    answer = await upload(client, amani, "SUBMISSION", name="answer.pdf")
    handed = await client.put(f"{API}/homework/{homework_id}/submission", headers=amani, json={"file_id": answer})
    submission_id = handed.json()["id"]
    assert handed.json()["file_name"] == "answer.pdf"
    assert (await client.get(f"{API}/homework/submissions/{submission_id}/file", headers=mwita)).content == PDF
    assert (await client.get(f"{API}/homework/submissions/{submission_id}/file", headers=amani)).status_code == 200
    assert (await client.get(f"{API}/homework/submissions/{submission_id}/file", headers=emmanuel)).status_code == 404
    assert (await client.get(f"{API}/homework/submissions/{submission_id}/file", headers=salma)).status_code == 404

    assert (await client.delete(f"{API}/homework/{homework_id}", headers=salma)).status_code == 403
    assert (await client.delete(f"{API}/homework/{homework_id}", headers=mwita)).status_code == 204
    assert all(h["id"] != homework_id for h in (await client.get(f"{API}/homework/mine", headers=amani)).json())
