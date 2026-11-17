"""Firewall, publication, published results, report cards, comments, amendments (maker-checker), analytics."""

import pytest

from app.services import report_cards
from tests.helpers import (
    AMATH,
    CHEM_A,
    F1,
    F2,
    F2_A,
    F5,
    F5_PCM,
    GS,
    PHY,
    PHY_A,
    SCHOOL_A,
    TERM1,
    bearer,
    login,
    parent_login,
    rekey_phone,
    u,
)

API = "/api/v1"
LYIMO, LYIMO_ENROLMENT, LYIMO_GUARDIAN = u(6, 17), u(24, 17), u(2, 23)  # Form V PCM, father Joseph Lyimo
AMANI_ENROLMENT = u(24, 11)  # Form II A


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


async def complete_form_five(client, admin) -> None:
    """Enter every mark the firewall reports as missing for Form V (admin may enter any class)."""
    sheet = (
        await client.get(f"{API}/marks/sheet?term_id={TERM1}&stream_id={F5_PCM}&subject_id={GS}", headers=admin)
    ).json()
    comp = {c["code"]: c["id"] for c in sheet["components"]}
    items = [
        {
            "enrolment_id": str(LYIMO_ENROLMENT),
            "subject_id": str(GS),
            "component_id": comp["CA"],
            "score": "30",
            "version": 0,
        }
    ]
    items += [
        {
            "enrolment_id": str(LYIMO_ENROLMENT),
            "subject_id": str(s),
            "component_id": comp["TERMINAL"],
            "score": score,
            "version": 0,
        }
        for s, score in ((GS, "71"), (AMATH, "88"), (PHY_A, "64"), (CHEM_A, "52"))
    ]
    saved = (await client.put(f"{API}/marks/batch", headers=admin, json={"items": items})).json()
    assert saved["saved"] == 5, saved


async def test_firewall_lists_every_missing_mark_in_both_languages(client, admin):
    result = (await client.get(f"{API}/results/firewall?term_id={TERM1}&class_id={F5}", headers=admin)).json()
    assert result["ok"] is False and result["total"] == 5
    assert {p["problem"] for p in result["problems"]} == {"MISSING_MARK"}
    gs = next(p for p in result["problems"] if p["subject"] == "GS" and p["component"] == "CA")
    assert gs["admission_no"] == "MF-2026-0003" and gs["teacher"] == "Neema Laizer"
    assert gs["message_sw"] == "Alama haijaingizwa" and gs["message_en"] == "No mark entered"
    blocked = await client.post(
        f"{API}/results/publish",
        headers={**admin, "Idempotency-Key": "publish-f5-001"},
        json={"term_id": str(TERM1), "class_id": str(F5)},
    )
    assert blocked.status_code == 422 and blocked.json()["error_code"] == "INCOMPLETE_GRADES_BLOCK"
    assert len(blocked.json()["details"]) == 5 and "5" in blocked.json()["message"]
    teacher = bearer(await login(client, username="tch.salma"))
    assert (
        await client.get(f"{API}/results/firewall?term_id={TERM1}&class_id={F5}", headers=teacher)
    ).status_code == 403


async def test_publish_report_cards_and_sms(client, db, admin, dispatcher):
    await rekey_phone(db, SCHOOL_A, LYIMO_GUARDIAN, "255765000023")
    await complete_form_five(client, admin)
    assert (await client.get(f"{API}/results/firewall?term_id={TERM1}&class_id={F5}", headers=admin)).json()["ok"]
    headers = {**admin, "Idempotency-Key": "publish-f5-002"}
    published = await client.post(
        f"{API}/results/publish", headers=headers, json={"term_id": str(TERM1), "class_id": str(F5)}
    )
    assert published.status_code == 201, published.text
    body = published.json()
    assert body["students"] == 1 and body["results"] == 4 and body["report_card_job_id"]
    again = await client.post(
        f"{API}/results/publish", headers=headers, json={"term_id": str(TERM1), "class_id": str(F5)}
    )
    assert again.json()["id"] == body["id"]  # idempotent replay

    [job_call] = dispatcher.take("report_cards.run")
    assert await report_cards.run_job(**job_call) == "succeeded"
    assert len(dispatcher.take("sms.send")) == 1  # father agreed to SMS
    bundle = await client.get(f"{API}/results/report-cards?term_id={TERM1}&class_id={F5}", headers=admin)
    assert bundle.status_code == 200 and bundle.content.startswith(b"%PDF")

    locked = (
        await client.put(
            f"{API}/marks/batch",
            headers=admin,
            json={
                "items": [
                    {
                        "enrolment_id": str(LYIMO_ENROLMENT),
                        "subject_id": str(AMATH),
                        "component_id": (
                            await client.get(
                                f"{API}/marks/sheet?term_id={TERM1}&stream_id={F5_PCM}&subject_id={AMATH}",
                                headers=admin,
                            )
                        ).json()["components"][0]["id"],
                        "score": "1",
                        "version": 2,
                    }
                ]
            },
        )
    ).json()
    assert locked["results"][0]["error_code"] == "locked"

    results = (await client.get(f"{API}/students/{LYIMO}/results?term_id={TERM1}", headers=admin)).json()
    amath = next(s for s in results["subjects"] if s["subject_code"] == "AMATH")
    assert (
        amath["final_score"] == "88.80" and amath["letter_grade"] == "A" and amath["out_of"] == 1
    )  # 36/40×40 + 88/100×60
    assert [c["code"] for c in amath["components"]] == ["CA", "TERMINAL"]
    assert results["summary"]["division"] is not None or results["summary"]["best_n_subjects"] == 3


async def test_class_results_pages_and_access(client, admin):
    page = (await client.get(f"{API}/results?term_id={TERM1}&class_id={F2}&limit=4", headers=admin)).json()
    assert page["publication"]["students"] == 6 and len(page["items"]) == 4 and page["next_cursor"]
    assert page["items"][0]["class_position"] == 1 and len(page["items"][0]["results"]) == 9
    rest = (
        await client.get(
            f"{API}/results?term_id={TERM1}&class_id={F2}&limit=4&cursor={page['next_cursor']}", headers=admin
        )
    ).json()
    assert len(rest["items"]) == 2
    only_a = (await client.get(f"{API}/results?term_id={TERM1}&class_id={F2}&stream_id={F2_A}", headers=admin)).json()
    assert len(only_a["items"]) == 4 and {i["stream_name"] for i in only_a["items"]} == {"A"}
    assert (await client.get(f"{API}/results?term_id={TERM1}&class_id={F1}", headers=admin)).status_code == 404


async def test_guardians_see_only_their_children(client, db, admin, dispatcher):
    amani = u(6, 11)
    father = await parent_login(client, db, dispatcher, SCHOOL_A, u(2, 21), "255754000021")  # John Massawe
    own = await client.get(f"{API}/students/{amani}/results?term_id={TERM1}", headers=father)
    assert own.status_code == 200 and own.json()["summary"]["class_size"] == 6
    pdf = await client.get(f"{API}/students/{amani}/report-card?term_id={TERM1}&lang=en", headers=father)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    stranger = await client.get(f"{API}/students/{u(6, 12)}/results?term_id={TERM1}", headers=father)
    assert stranger.status_code == 404
    assert (await client.get(f"{API}/results?term_id={TERM1}&class_id={F2}", headers=father)).status_code == 403


async def test_comments(client, admin):
    publication = (await client.get(f"{API}/results?term_id={TERM1}&class_id={F2}", headers=admin)).json()[
        "publication"
    ]
    url = f"{API}/publications/{publication['id']}/comments/{AMANI_ENROLMENT}"
    class_teacher = bearer(await login(client, username="tch.salma"))  # class teacher of F2 A
    ok = await client.put(url, headers=class_teacher, json={"class_teacher_comment": "Anajituma sana."})
    assert ok.status_code == 200 and ok.json()["class_teacher_comment"] == "Anajituma sana."
    other = bearer(await login(client, username="tch.mwita"))
    assert (await client.put(url, headers=other, json={"class_teacher_comment": "x"})).status_code == 403
    assert (await client.put(url, headers=class_teacher, json={"head_teacher_comment": "x"})).status_code == 403
    head = await client.put(url, headers=admin, json={"head_teacher_comment": "Hongera."})
    assert head.json() == {"class_teacher_comment": "Anajituma sana.", "head_teacher_comment": "Hongera."}


async def test_amendments_are_maker_checker(client, admin, dispatcher):
    row = next(
        i
        for i in (await client.get(f"{API}/results?term_id={TERM1}&class_id={F2}", headers=admin)).json()["items"]
        if i["enrolment_id"] == str(AMANI_ENROLMENT)
    )
    physics = next(r for r in row["results"] if r["subject_id"] == str(PHY))
    kimaro = bearer(await login(client, username="tch.kimaro"))  # teaches Form II Physics
    requested = await client.post(
        f"{API}/published-results/{physics['published_result_id']}/amendments",
        headers=kimaro,
        json={"new_score": "90", "reason": "Terminal paper re-marked"},
    )
    assert requested.status_code == 201 and requested.json()["status"] == "PENDING"
    assert requested.json()["old_score"] == physics["final_score"]
    duplicate = await client.post(
        f"{API}/published-results/{physics['published_result_id']}/amendments",
        headers=kimaro,
        json={"new_score": "91", "reason": "Second try"},
    )
    assert duplicate.status_code == 409
    mwita = bearer(await login(client, username="tch.mwita"))  # does not teach Physics
    assert (
        await client.post(
            f"{API}/published-results/{physics['published_result_id']}/amendments",
            headers=mwita,
            json={"new_score": "50", "reason": "Not my subject"},
        )
    ).status_code == 403

    own = await client.post(
        f"{API}/published-results/{row['results'][0]['published_result_id']}/amendments",
        headers=admin,
        json={"new_score": "60", "reason": "Admin's own request"},
    )
    self_approval = await client.post(f"{API}/amendments/{own.json()['id']}/approve", headers=admin, json={})
    assert self_approval.status_code == 403 and self_approval.json()["details"][0]["code"] == "maker_checker"

    approved = await client.post(
        f"{API}/amendments/{requested.json()['id']}/approve", headers=admin, json={"note": "Checked the script"}
    )
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
    assert dispatcher.take("report_cards.run")
    results = (await client.get(f"{API}/students/{u(6, 11)}/results?term_id={TERM1}", headers=admin)).json()
    new_physics = next(s for s in results["subjects"] if s["subject_code"] == "PHY")
    assert new_physics["final_score"] == "90.00" and new_physics["amended"] and results["amended_at"]
    stale = await client.post(
        f"{API}/published-results/{physics['published_result_id']}/amendments",
        headers=kimaro,
        json={"new_score": "80", "reason": "Against the old version"},
    )
    assert stale.status_code == 409 and stale.json()["details"][0]["code"] == "superseded"

    again = await client.post(
        f"{API}/published-results/{new_physics['published_result_id']}/amendments",
        headers=kimaro,
        json={"new_score": "95", "reason": "Another look"},
    )
    rejected = await client.post(
        f"{API}/amendments/{again.json()['id']}/reject", headers=admin, json={"note": "No new evidence"}
    )
    assert rejected.json()["status"] == "REJECTED"
    mine = (await client.get(f"{API}/amendments", headers=kimaro)).json()
    assert {a["status"] for a in mine} == {"APPROVED", "REJECTED"}
    pending = (await client.get(f"{API}/amendments?status=PENDING", headers=admin)).json()
    assert [a["id"] for a in pending] == [own.json()["id"]]


async def test_analytics(client, admin):
    stats = (await client.get(f"{API}/analytics/results?term_id={TERM1}&class_id={F2}", headers=admin)).json()
    assert stats["students"] == 6 and len(stats["subjects"]) == 9
    assert sum(stats["divisions"].values()) == 6
    physics = next(s for s in stats["subjects"] if s["subject_code"] == "PHY")
    assert sum(physics["grades"].values()) == 6 and physics["teacher"] == "Peter Kimaro"
    assert [t["position"] for t in stats["top_students"]][0] == 1
