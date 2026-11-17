"""Academic configuration: years, terms, classes, streams, curriculum, rooms, grading schemes, components."""

import pytest

from tests.helpers import (
    A_LEVEL,
    AMATH,
    BMATH,
    CHEM_A,
    ENG,
    F1,
    F2,
    F2_A,
    F5,
    O_LEVEL,
    PHY_A,
    ROOM_F1A,
    STAFF_SALMA,
    TERM1,
    YEAR_2026,
    bearer,
    login,
)

API = "/api/v1"
O_BANDS = [
    {"letter": "A", "min_score": 75, "max_score": 100, "points": 1, "remark_en": "Excellent", "remark_sw": "Bora"},
    {
        "letter": "B",
        "min_score": 65,
        "max_score": 74,
        "points": 2,
        "remark_en": "Very good",
        "remark_sw": "Vizuri sana",
    },
    {"letter": "C", "min_score": 45, "max_score": 64, "points": 3, "remark_en": "Good", "remark_sw": "Vizuri"},
    {
        "letter": "D",
        "min_score": 30,
        "max_score": 44,
        "points": 4,
        "remark_en": "Satisfactory",
        "remark_sw": "Inaridhisha",
    },
    {"letter": "F", "min_score": 0, "max_score": 29, "points": 5, "remark_en": "Fail", "remark_sw": "Hafifu"},
]
O_DIVISIONS = [
    {"division": d, "min_points": lo, "max_points": hi}
    for d, lo, hi in (("I", 7, 17), ("II", 18, 21), ("III", 22, 25), ("IV", 26, 33), ("0", 34, 35))
]


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


@pytest.fixture
async def teacher(client) -> dict:
    return bearer(await login(client, username="tch.salma"))


async def test_everyone_reads_only_configurers_write(client, admin, teacher):
    for path in (
        "/subjects",
        "/rooms",
        "/classes",
        "/streams",
        "/terms",
        "/education-levels",
        "/combinations",
        "/grading-schemes",
        f"/assessment-components?term_id={TERM1}",
        "/public-holidays?year=2026",
    ):
        assert (await client.get(API + path, headers=teacher)).status_code == 200, path
    denied = await client.post(
        f"{API}/subjects", headers=teacher, json={"code": "AGRI", "name_en": "Agriculture", "name_sw": "Kilimo"}
    )
    assert denied.status_code == 403
    assert (
        await client.get(f"{API}/assessment-components/weight-check?term_id={TERM1}", headers=teacher)
    ).status_code == 403


async def test_only_one_current_year(client, admin):
    created = await client.post(
        f"{API}/academic-years",
        headers=admin,
        json={"name": "2027", "start_date": "2027-01-01", "end_date": "2027-12-31", "is_current": True},
    )
    assert created.status_code == 201
    years = (await client.get(f"{API}/academic-years", headers=admin)).json()
    assert [y["name"] for y in years if y["is_current"]] == ["2027"]
    back = await client.patch(f"{API}/academic-years/{YEAR_2026}", headers=admin, json={"is_current": True})
    assert back.json()["is_current"]
    years = (await client.get(f"{API}/academic-years", headers=admin)).json()
    assert [y["name"] for y in years if y["is_current"]] == ["2026"]
    in_use = await client.delete(f"{API}/academic-years/{YEAR_2026}?reason=Mistake", headers=admin)
    assert in_use.status_code == 409


async def test_terms_stay_inside_the_year_and_do_not_overlap(client, admin):
    base = {"academic_year_id": str(YEAR_2026), "name_en": "Term Three", "name_sw": "Muhula wa Tatu"}
    outside = await client.post(
        f"{API}/terms", headers=admin, json={**base, "term_no": 3, "start_date": "2026-12-01", "end_date": "2027-01-10"}
    )
    assert outside.status_code == 422 and outside.json()["details"][0]["code"] == "outside_year"
    overlap = await client.post(
        f"{API}/terms", headers=admin, json={**base, "term_no": 3, "start_date": "2026-06-01", "end_date": "2026-06-30"}
    )
    assert overlap.status_code == 409
    ok = await client.post(
        f"{API}/terms", headers=admin, json={**base, "term_no": 3, "start_date": "2026-06-08", "end_date": "2026-07-03"}
    )
    assert ok.status_code == 201
    moved = await client.patch(f"{API}/terms/{ok.json()['id']}", headers=admin, json={"end_date": "2027-02-01"})
    assert moved.status_code == 422


async def test_classes_promotion_path_and_in_use(client, admin):
    cross_level = await client.post(
        f"{API}/classes",
        headers=admin,
        json={
            "education_level_id": str(O_LEVEL),
            "code": "BRIDGE",
            "name_en": "Bridging class",
            "name_sw": "Darasa la maandalizi",
            "sort_order": 10,
            "next_class_id": str(F5),
        },
    )
    assert cross_level.status_code == 422
    bridge = await client.post(
        f"{API}/classes",
        headers=admin,
        json={
            "education_level_id": str(O_LEVEL),
            "code": "BRIDGE",
            "name_en": "Bridging class",
            "name_sw": "Darasa la maandalizi",
            "sort_order": 10,
        },
    )
    assert bridge.status_code == 201
    linked = await client.patch(f"{API}/classes/{F2}", headers=admin, json={"next_class_id": bridge.json()["id"]})
    assert linked.json()["next_class_id"] == bridge.json()["id"]
    assert (await client.delete(f"{API}/classes/{F2}?reason=Merge", headers=admin)).status_code == 409
    url = f"{API}/classes/{bridge.json()['id']}?reason=Not used"
    assert (await client.delete(url, headers=admin)).status_code == 409  # F2 still promotes into it
    await client.patch(f"{API}/classes/{F2}", headers=admin, json={"next_class_id": None})
    assert (await client.delete(url, headers=admin)).status_code == 204


async def test_streams_counts_capacity_and_class_teacher(client, admin):
    streams = {s["id"]: s for s in (await client.get(f"{API}/streams?class_id={F2}", headers=admin)).json()}
    assert streams[str(F2_A)]["enrolled"] == 4
    too_small = await client.patch(f"{API}/streams/{F2_A}", headers=admin, json={"capacity": 3})
    assert too_small.status_code == 422
    new = await client.post(
        f"{API}/streams",
        headers=admin,
        json={"class_id": str(F1), "name": "B", "capacity": 40, "home_room_id": str(ROOM_F1A)},
    )
    assert new.status_code == 201
    teacher = await client.put(
        f"{API}/streams/{new.json()['id']}/class-teacher",
        headers=admin,
        json={"academic_year_id": str(YEAR_2026), "staff_id": str(STAFF_SALMA)},
    )
    assert teacher.status_code == 200 and teacher.json()["staff_id"] == str(STAFF_SALMA)
    duplicate = await client.post(
        f"{API}/streams", headers=admin, json={"class_id": str(F1), "name": "B", "capacity": 40}
    )
    assert duplicate.status_code == 409
    assert (await client.delete(f"{API}/streams/{F2_A}?reason=Merge", headers=admin)).status_code == 409


async def test_class_curriculum_is_replaced(client, admin):
    url = f"{API}/classes/{F1}/subjects"
    assert len((await client.get(url, headers=admin)).json()) == 9
    two = await client.put(
        url,
        headers=admin,
        json=[{"subject_id": str(BMATH), "periods_per_week": 6}, {"subject_id": str(ENG), "is_compulsory": False}],
    )
    assert two.status_code == 200 and {s["code"]: s["is_compulsory"] for s in two.json()} == {
        "BMATH": True,
        "ENG": False,
    }
    again = await client.put(url, headers=admin, json=[{"subject_id": str(BMATH)}])
    assert [s["code"] for s in again.json()] == ["BMATH"]
    readd = await client.put(url, headers=admin, json=[{"subject_id": str(BMATH)}, {"subject_id": str(ENG)}])
    assert len(readd.json()) == 2
    dup = await client.put(url, headers=admin, json=[{"subject_id": str(BMATH)}, {"subject_id": str(BMATH)}])
    assert dup.status_code == 422


async def test_combinations(client, admin):
    created = await client.post(
        f"{API}/combinations",
        headers=admin,
        json={
            "education_level_id": str(A_LEVEL),
            "code": "PCB",
            "name_en": "Physics, Chemistry, Biology",
            "name_sw": "Fizikia, Kemia, Biolojia",
            "subjects": [{"subject_id": str(PHY_A)}, {"subject_id": str(CHEM_A)}, {"subject_id": str(AMATH)}],
        },
    )
    assert created.status_code == 201 and len(created.json()["subjects"]) == 3
    trimmed = await client.patch(
        f"{API}/combinations/{created.json()['id']}",
        headers=admin,
        json={"subjects": [{"subject_id": str(PHY_A)}, {"subject_id": str(CHEM_A)}]},
    )
    assert {s["subject_id"] for s in trimmed.json()["subjects"]} == {str(PHY_A), str(CHEM_A)}
    restored = await client.patch(
        f"{API}/combinations/{created.json()['id']}",
        headers=admin,
        json={"subjects": [{"subject_id": str(AMATH), "is_principal": False}]},
    )
    assert restored.json()["subjects"] == [{"subject_id": str(AMATH), "is_principal": False}]


async def test_subjects_and_rooms(client, admin):
    subject = await client.post(
        f"{API}/subjects",
        headers=admin,
        json={
            "code": "AGRI",
            "necta_code": "051",
            "name_en": "Agriculture",
            "name_sw": "Kilimo",
            "room_type": "LABORATORY",
        },
    )
    assert subject.status_code == 201
    renamed = await client.patch(
        f"{API}/subjects/{subject.json()['id']}", headers=admin, json={"name_en": "Agricultural Science"}
    )
    assert renamed.json()["name_en"] == "Agricultural Science"
    assert (await client.delete(f"{API}/subjects/{BMATH}?reason=Old", headers=admin)).status_code == 409
    assert (await client.delete(f"{API}/subjects/{subject.json()['id']}?reason=Typo", headers=admin)).status_code == 204
    room = await client.post(
        f"{API}/rooms",
        headers=admin,
        json={"code": "ICT1", "name": "Computer room", "room_type": "ICT_LAB", "capacity": 30},
    )
    assert room.status_code == 201
    assert (await client.delete(f"{API}/rooms/{ROOM_F1A}?reason=Closed", headers=admin)).status_code == 409


async def test_grading_scheme_versions(client, admin):
    gap = [dict(b) for b in O_BANDS]
    gap[0]["min_score"] = 76
    bad = await client.post(
        f"{API}/grading-schemes",
        headers=admin,
        json={
            "education_level_id": str(O_LEVEL),
            "academic_year_id": str(YEAR_2026),
            "name": "Bad",
            "best_n_subjects": 7,
            "bands": gap,
            "divisions": O_DIVISIONS,
        },
    )
    assert bad.status_code == 422 and bad.json()["details"][0]["code"] == "bands_gap"
    saved = await client.post(
        f"{API}/grading-schemes",
        headers=admin,
        json={
            "education_level_id": str(O_LEVEL),
            "academic_year_id": str(YEAR_2026),
            "name": "NECTA CSEE 2026 v2",
            "best_n_subjects": 7,
            "bands": O_BANDS,
            "divisions": O_DIVISIONS,
        },
    )
    assert saved.status_code == 201 and saved.json()["version"] == 2 and saved.json()["is_active"]
    assert [b["letter"] for b in saved.json()["bands"]] == ["A", "B", "C", "D", "F"]
    every = (await client.get(f"{API}/grading-schemes?education_level_id={O_LEVEL}&active=false", headers=admin)).json()
    assert [(s["version"], s["is_active"]) for s in every] == [(2, True), (1, False)]


async def test_components_weights_and_guards(client, admin):
    check = (await client.get(f"{API}/assessment-components/weight-check?term_id={TERM1}", headers=admin)).json()
    assert {(r["education_level_id"], r["subject_id"]): r["ok"] for r in check} == {
        (str(O_LEVEL), None): True,
        (str(A_LEVEL), None): True,
    }
    components = (await client.get(f"{API}/assessment-components?term_id={TERM1}", headers=admin)).json()
    o_ca = next(c for c in components if c["education_level_id"] == str(O_LEVEL) and c["code"] == "CA")
    a_ca = next(c for c in components if c["education_level_id"] == str(A_LEVEL) and c["code"] == "CA")

    locked = await client.patch(f"{API}/assessment-components/{o_ca['id']}", headers=admin, json={"weight": "25"})
    assert locked.status_code == 409 and locked.json()["details"][0]["code"] == "results_published"
    renamed = await client.patch(f"{API}/assessment-components/{o_ca['id']}", headers=admin, json={"name_en": "CA"})
    assert renamed.status_code == 200
    too_low = await client.patch(f"{API}/assessment-components/{a_ca['id']}", headers=admin, json={"max_score": "30"})
    assert too_low.status_code == 422 and too_low.json()["details"][0]["code"] == "scores_exceed_max"
    in_use = await client.delete(f"{API}/assessment-components/{a_ca['id']}?reason=Wrong", headers=admin)
    assert in_use.status_code == 409

    project = await client.post(
        f"{API}/assessment-components",
        headers=admin,
        json={
            "term_id": str(TERM1),
            "education_level_id": str(A_LEVEL),
            "subject_id": str(AMATH),
            "code": "PROJECT",
            "name_en": "Project",
            "name_sw": "Mradi",
            "max_score": "20",
            "weight": "10",
        },
    )
    assert project.status_code == 201
    check = (await client.get(f"{API}/assessment-components/weight-check?term_id={TERM1}", headers=admin)).json()
    amath = next(r for r in check if r["subject_id"] == str(AMATH))
    assert amath["total_weight"] == "10.00" and amath["ok"] is False


async def test_holidays(client, admin):
    created = await client.post(
        f"{API}/public-holidays",
        headers=admin,
        json={"holiday_date": "2026-08-08", "name_en": "Farmers' Day", "name_sw": "Nane Nane"},
    )
    assert created.status_code == 201
    dup = await client.post(
        f"{API}/public-holidays",
        headers=admin,
        json={"holiday_date": "2026-08-08", "name_en": "Duplicate", "name_sw": "Nakala"},
    )
    assert dup.status_code == 409
    listed = (await client.get(f"{API}/public-holidays?year=2026", headers=admin)).json()
    assert "2026-08-08" in {h["holiday_date"] for h in listed}
