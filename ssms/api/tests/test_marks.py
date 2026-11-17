"""Mark sheets, offline batch sync with optimistic versions, locks after publication, Excel upload."""

import csv
import io

import pytest
from openpyxl import load_workbook

from app.services import marks as marks_service
from tests.helpers import AMATH, BMATH, F2_A, F5_PCM, PHY_A, TERM1, bearer, login, u

API = "/api/v1"
PCM_STUDENT = u(24, 17)  # Emmanuel Lyimo, Form V PCM: only CA entered so far
F2_STUDENT = u(24, 11)  # Form II: results published, marks locked


@pytest.fixture
async def mwita(client) -> dict:  # teaches Advanced Mathematics in Form V PCM
    return bearer(await login(client, username="tch.mwita"))


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


async def components(client, headers, stream=F5_PCM, subject=AMATH) -> dict:
    sheet = (
        await client.get(f"{API}/marks/sheet?term_id={TERM1}&stream_id={stream}&subject_id={subject}", headers=headers)
    ).json()
    return {c["code"]: c["id"] for c in sheet["components"]}


async def test_sheet_only_for_the_assigned_teacher(client, mwita, admin):
    url = f"{API}/marks/sheet?term_id={TERM1}&stream_id={F5_PCM}&subject_id={AMATH}"
    response = await client.get(url, headers=mwita)
    assert response.status_code == 200
    sheet = response.json()
    assert [c["code"] for c in sheet["components"]] == ["CA", "TERMINAL"] and sheet["locked"] is False
    [student] = sheet["students"]
    ca = sheet["components"][0]["id"]
    assert student["admission_no"] == "MF-2026-0003" and student["marks"][ca]["score"] == "36.00"
    assert (await client.get(url, headers={**mwita, "If-None-Match": response.headers["etag"]})).status_code == 304
    kimaro = bearer(await login(client, username="tch.kimaro"))
    assert (await client.get(url, headers=kimaro)).status_code == 403
    assert (await client.get(url, headers=admin)).status_code == 200
    locked = (
        await client.get(f"{API}/marks/sheet?term_id={TERM1}&stream_id={F2_A}&subject_id={BMATH}", headers=admin)
    ).json()
    assert locked["locked"] is True and len(locked["students"]) == 4


async def test_batch_versions_conflicts_and_errors(client, mwita, admin):
    comp = await components(client, mwita)
    o_level_ca = (await components(client, admin, F2_A, BMATH))["CA"]
    base = {"enrolment_id": str(PCM_STUDENT), "subject_id": str(AMATH)}
    first = (
        await client.put(
            f"{API}/marks/batch",
            headers=mwita,
            json={
                "items": [
                    {**base, "component_id": comp["TERMINAL"], "score": "70", "version": 0},
                    {**base, "component_id": comp["CA"], "score": "38", "version": 1},
                    {**base, "component_id": comp["TERMINAL"], "score": "150", "version": 1},
                    {**base, "subject_id": str(PHY_A), "component_id": comp["CA"], "score": "20", "version": 1},
                    {**base, "component_id": o_level_ca, "score": "20", "version": 0},
                    {
                        "enrolment_id": str(F2_STUDENT),
                        "subject_id": str(BMATH),
                        "component_id": o_level_ca,
                        "score": "1",
                        "version": 1,
                    },
                ]
            },
        )
    ).json()
    statuses = [(r["status"], r["error_code"]) for r in first["results"]]
    assert statuses == [
        ("ok", None),
        ("ok", None),
        ("error", "out_of_range"),
        ("error", "forbidden"),
        ("error", "not_applicable"),
        ("error", "locked"),
    ]  # he also teaches F2 Maths
    assert first["results"][1]["version"] == 2 and first["saved"] == 2

    stale = (
        await client.put(
            f"{API}/marks/batch",
            headers=mwita,
            json={
                "items": [
                    {**base, "component_id": comp["CA"], "score": "35", "version": 1},  # another device, old version
                    {
                        **base,
                        "component_id": comp["CA"],
                        "score": "38",
                        "version": 1,
                    },  # same value: nothing to fight about
                ]
            },
        )
    ).json()
    assert stale["results"][0]["status"] == "conflict"
    assert stale["results"][0]["server"] == {"score": "38.00", "is_absent": False, "version": 2}
    assert stale["results"][1]["status"] == "ok"

    locked = (
        await client.put(
            f"{API}/marks/batch",
            headers=admin,
            json={
                "items": [
                    {
                        "enrolment_id": str(F2_STUDENT),
                        "subject_id": str(BMATH),
                        "component_id": o_level_ca,
                        "score": "1",
                        "version": 1,
                    }
                ]
            },
        )
    ).json()
    assert locked["results"][0]["error_code"] == "locked"

    absent = await client.put(
        f"{API}/marks/batch",
        headers=mwita,
        json={"items": [{**base, "component_id": comp["TERMINAL"], "score": "10", "is_absent": True}]},
    )
    assert absent.status_code == 422


async def _upload(client, headers, dispatcher, rows: list[list[str]], key: str) -> dict:
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    response = await client.post(
        f"{API}/marks/upload",
        headers={**headers, "Idempotency-Key": key},
        data={"term_id": str(TERM1), "stream_id": str(F5_PCM), "subject_id": str(AMATH)},
        files={"file": ("marks.csv", out.getvalue().encode())},
    )
    assert response.status_code == 202, response.text
    [call] = dispatcher.take("marks.upload")
    await marks_service.run_upload(**call)
    return (await client.get(f"{API}/jobs/{response.json()['id']}", headers=headers)).json()


async def test_excel_template_and_all_or_nothing_upload(client, mwita, dispatcher):
    template = await client.get(
        f"{API}/marks/template?term_id={TERM1}&stream_id={F5_PCM}&subject_id={AMATH}", headers=mwita
    )
    sheet = load_workbook(io.BytesIO(template.content)).worksheets[0]
    assert [c.value for c in sheet[1]] == ["admission_no", "full_name", "CA", "TERMINAL"]
    assert [c.value for c in sheet[2]][2] == 36

    bad = await _upload(
        client,
        mwita,
        dispatcher,
        [["admission_no", "CA", "TERMINAL"], ["MF-2026-0003", "39", "abc"], ["MF-9999-0001", "1", "1"]],
        "marks-upload-1",
    )
    assert bad["status"] == "FAILED" and bad["error_count"] == 2
    comp = await components(client, mwita)
    sheet_after = (
        await client.get(f"{API}/marks/sheet?term_id={TERM1}&stream_id={F5_PCM}&subject_id={AMATH}", headers=mwita)
    ).json()
    assert sheet_after["students"][0]["marks"][comp["CA"]]["score"] == "36.00"  # nothing saved

    good = await _upload(
        client,
        mwita,
        dispatcher,
        [["admission_no", "CA", "TERMINAL"], ["MF-2026-0003", "39.5", "ABS"]],
        "marks-upload-2",
    )
    assert good["status"] == "SUCCEEDED" and good["processed_items"] == 2
    marks = (
        await client.get(f"{API}/marks/sheet?term_id={TERM1}&stream_id={F5_PCM}&subject_id={AMATH}", headers=mwita)
    ).json()["students"][0]["marks"]
    assert marks[comp["CA"]]["score"] == "39.50" and marks[comp["TERMINAL"]]["is_absent"] is True

    kimaro = bearer(await login(client, username="tch.kimaro"))
    other = await client.post(
        f"{API}/marks/upload",
        headers={**kimaro, "Idempotency-Key": "marks-upload-3"},
        data={"term_id": str(TERM1), "stream_id": str(F5_PCM), "subject_id": str(AMATH)},
        files={"file": ("marks.csv", b"admission_no,CA\n")},
    )
    assert other.status_code == 403
