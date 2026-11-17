"""Announcements (audiences, SMS job, credit), inbox, templates, SMS log and credit, console top-up."""

import pytest
from sqlalchemy import select

from app.models import BackgroundJob, SmsMessage
from app.services import communication
from tests.helpers import SCHOOL_A, SCHOOL_B, as_school, bearer, login, parent_login, rekey_phone, u
from tests.test_platform import platform_login

API = "/api/v1"
F2_A = u(19, 2)
LYIMO, LYIMO_PHONE = u(2, 23), "255765000023"  # father of Baraka (Form II A)
SAID, SAID_PHONE = u(2, 26), "255713000026"  # father of Mariam (Form II B)


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


def notice(**fields) -> dict:
    return {"title": "Siku ya michezo", "body": "Wanafunzi walete nguo za michezo Ijumaa.", **fields}


async def test_stream_announcement_with_sms_job(client, db, admin, dispatcher):
    await rekey_phone(db, SCHOOL_A, LYIMO, LYIMO_PHONE)
    body = notice(audience="STREAM", stream_id=str(F2_A), send_sms=True)
    assert (await client.post(f"{API}/announcements", headers=admin, json=body)).status_code == 422  # key needed
    headers = {**admin, "Idempotency-Key": "ann-sports-f2a"}
    created = await client.post(f"{API}/announcements", headers=headers, json=body)
    assert created.status_code == 201, created.text
    out = created.json()
    assert out["sms_recipients"] == 4 and out["sms_job_id"]  # the four Form II A guardians who receive SMS
    replay = await client.post(f"{API}/announcements", headers=headers, json=body)
    assert replay.json()["id"] == out["id"] and replay.json()["sms_job_id"] == out["sms_job_id"]

    calls = dispatcher.take("announcements.sms")
    assert len(calls) == 1
    assert await communication.run_sms(**calls[0]) == "1 sent"  # other seed phones are not real ciphertext
    assert await communication.run_sms(**calls[0]) == "skipped"
    await as_school(db, SCHOOL_A)
    job = (await db.execute(select(BackgroundJob).where(BackgroundJob.id == out["sms_job_id"]))).scalar_one()
    assert (job.status, job.processed_items, job.error_count) == ("SUCCEEDED", 1, 3)
    message = (await db.execute(select(SmsMessage).where(SmsMessage.related_id == out["id"]))).scalar_one()
    assert message.body.startswith("Shule ya Sekondari Mfano: Siku ya michezo.") and message.to_user_id == LYIMO

    bad = await client.post(f"{API}/announcements", headers=admin, json=notice(audience="CLASS"))
    assert bad.status_code == 422
    teacher = bearer(await login(client, username="tch.salma"))
    assert (
        await client.post(f"{API}/announcements", headers=teacher, json=notice(audience="SCHOOL"))
    ).status_code == 403


async def test_no_credit_refuses_before_saving(client, db, dispatcher):
    admin_b = bearer(await login(client, school="upendo-pri", username="admin"))
    headers = {**admin_b, "Idempotency-Key": "ann-b-no-credit"}
    refused = await client.post(f"{API}/announcements", headers=headers, json=notice(audience="PARENTS", send_sms=True))
    assert refused.status_code == 422 and refused.json()["error_code"] == "NO_SMS_CREDIT"
    assert (await client.get(f"{API}/announcements", headers=admin_b)).json() == []
    without_sms = await client.post(f"{API}/announcements", headers=admin_b, json=notice(audience="PARENTS"))
    assert without_sms.status_code == 201


async def test_feed_follows_the_audience(client, db, admin, dispatcher):
    stream_note = await client.post(
        f"{API}/announcements", headers=admin, json=notice(audience="STREAM", stream_id=str(F2_A))
    )
    later = notice(audience="SCHOOL", title="Ratiba mpya", publish_at="2030-01-01T08:00:00+03:00")
    assert (await client.post(f"{API}/announcements", headers=admin, json=later)).status_code == 201
    staff_note = await client.post(f"{API}/announcements", headers=admin, json=notice(audience="STAFF", title="Kikao"))

    def titles(feed) -> set[str]:
        return {a["title"] for a in feed}

    lyimo = await parent_login(client, db, dispatcher, SCHOOL_A, LYIMO, LYIMO_PHONE)
    seen = titles((await client.get(f"{API}/announcements", headers=lyimo)).json())
    assert (
        {"Mkutano wa wazazi", stream_note.json()["title"]} <= seen and "Ratiba mpya" not in seen and "Kikao" not in seen
    )
    said = await parent_login(client, db, dispatcher, SCHOOL_A, SAID, SAID_PHONE)
    assert stream_note.json()["id"] not in {
        a["id"] for a in (await client.get(f"{API}/announcements", headers=said)).json()
    }
    teacher = bearer(await login(client, username="tch.salma"))
    staff_feed = (await client.get(f"{API}/announcements", headers=teacher)).json()
    assert staff_note.json()["id"] in {a["id"] for a in staff_feed} and "Mkutano wa wazazi" not in titles(staff_feed)
    assert "Ratiba mpya" in titles((await client.get(f"{API}/announcements", headers=admin)).json())  # authors see all
    assert (await client.delete(f"{API}/announcements/{staff_note.json()['id']}", headers=admin)).status_code == 204
    assert staff_note.json()["id"] not in {
        a["id"] for a in (await client.get(f"{API}/announcements", headers=teacher)).json()
    }


async def test_individual_message_reaches_the_inbox(client, admin):
    teacher = bearer(await login(client, username="tch.salma"))
    direct = notice(audience="INDIVIDUAL", target_user_id=str(u(2, 4)), title="Tafadhali onana nami")
    assert (await client.post(f"{API}/announcements", headers=admin, json=direct)).status_code == 201
    inbox = (await client.get(f"{API}/notifications", headers=teacher)).json()
    assert inbox["unread"] == 1 and inbox["items"][0]["title"] == "Tafadhali onana nami"
    item = inbox["items"][0]["id"]
    assert (await client.post(f"{API}/notifications/{item}/read", headers=teacher)).status_code == 204
    assert (await client.get(f"{API}/notifications", headers=teacher)).json()["unread"] == 0
    assert (await client.post(f"{API}/notifications/{item}/read", headers=admin)).status_code == 404  # not mine
    assert (await client.post(f"{API}/notifications/read-all", headers=teacher)).status_code == 204


async def test_templates_log_credit_and_top_up(client, db, admin, dispatcher):
    listed = (await client.get(f"{API}/message-templates", headers=admin)).json()
    assert len(listed) == 16
    absence = next(t for t in listed if t["key"] == "absence_alert" and t["language"] == "sw")
    assert absence["placeholders"] == ["date", "school", "student"]
    url = f"{API}/message-templates/absence_alert/sw"
    bad = await client.put(url, headers=admin, json={"body": "{school}: {student} {amount}"})
    assert bad.status_code == 422 and bad.json()["details"][0]["code"] == "bad_placeholder"
    long = await client.put(url, headers=admin, json={"body": "{school} " + "neno " * 85})
    assert long.status_code == 422 and long.json()["details"][0]["code"] == "sms_too_long"
    saved = await client.put(url, headers=admin, json={"body": "{school}: {student} hayupo leo {date}."})
    assert saved.json()["customised"] is True and saved.json()["body"].endswith("hayupo leo {date}.")
    assert (
        await client.put(f"{API}/message-templates/otp_login/sw", headers=admin, json={"body": "x {code}"})
    ).status_code == 404

    log = (await client.get(f"{API}/sms?status=DELIVERED", headers=admin)).json()
    assert log and all(r["to"] == "****0023" and r["status"] == "DELIVERED" for r in log)
    credit = (await client.get(f"{API}/sms/credit", headers=admin)).json()
    assert credit["credits_left"] == 998 and credit["low"] is False
    assert (
        await client.get(f"{API}/sms/credit", headers=bearer(await login(client, username="tch.salma")))
    ).status_code == 403

    console = bearer(await platform_login(client))
    topped = await client.post(
        f"{API}/platform/schools/{SCHOOL_B}/sms-credit", headers=console, json={"credits": 500, "note": "Bundle INV-77"}
    )
    assert topped.status_code == 201 and topped.json()["credits_left"] == 500
    assert topped.json()["history"][0] == {**topped.json()["history"][0], "kind": "TOPUP", "credits": 500}
    assert (
        await client.post(
            f"{API}/platform/schools/{SCHOOL_B}/sms-credit", headers=admin, json={"credits": 5, "note": "self"}
        )
    ).status_code == 401
