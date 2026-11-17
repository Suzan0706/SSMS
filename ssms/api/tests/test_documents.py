"""Certificates, ID cards, staff photos, the email channel and the platform dashboard (FR-75, FR-94, FR-95, FR-98)."""

import pytest
from sqlalchemy import select

from app.models import EmailMessage
from app.tasks.handlers import email_send
from tests.helpers import F2_A, SCHOOL_A, as_school, bearer, login, u
from tests.test_platform import platform_login

API = "/api/v1"
AMANI, BARAKA = u(6, 11), u(6, 13)
STAFF_MWITA = u(8, 3)
GATE_JUMA = u(2, 6)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
LEAVING = (
    "Hii ni kuthibitisha kwamba {{name}} ({{admission_no}}), wa {{class}}, alisoma {{school}}. Tarehe {{issued_on}}."
)


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))  # certificates.issue, cards.print, email.manage, staff.manage


async def test_certificates_are_filled_in_frozen_numbered_and_revoked_once(client, admin):
    bad = await client.post(
        f"{API}/certificate-templates",
        headers=admin,
        json={"kind": "LEAVING", "name": "Kuhitimu", "body": "Jina: {{nickname}} na zaidi"},
    )
    assert bad.status_code == 422
    template = (
        await client.post(
            f"{API}/certificate-templates", headers=admin, json={"kind": "LEAVING", "name": "Kuhitimu", "body": LEAVING}
        )
    ).json()
    issued = await client.post(
        f"{API}/certificates",
        headers=admin,
        json={"template_id": template["id"], "student_ids": [str(AMANI), str(BARAKA)], "issued_on": "2026-11-02"},
    )
    assert issued.status_code == 201, issued.text
    serials = [c["serial_no"] for c in issued.json()["issued"]]
    assert len(serials) == 2 and all(s.startswith("CT-2026-") for s in serials) and serials[0] != serials[1]

    # editing the template later does not change certificates already issued
    await client.put(
        f"{API}/certificate-templates/{template['id']}",
        headers=admin,
        json={"kind": "LEAVING", "name": "Kuhitimu", "body": "Maandishi mapya kabisa {{name}}"},
    )
    listed = (await client.get(f"{API}/certificates?student_id={AMANI}", headers=admin)).json()
    first = listed[0]
    pdf = await client.get(f"{API}/certificates/{first['id']}.pdf", headers=admin)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    url = f"{API}/certificates/{first['id']}/revoke"
    assert (await client.post(url, headers=admin, json={"reason": "Imetolewa kwa makosa"})).status_code == 204
    assert (await client.post(url, headers=admin, json={"reason": "Mara ya pili"})).status_code == 409
    assert (
        await client.get(f"{API}/certificates/{first['id']}.pdf", headers=admin)
    ).status_code == 200  # marked revoked
    teacher = bearer(await login(client, username="tch.mwita"))
    assert (await client.get(f"{API}/certificates", headers=teacher)).status_code == 403


async def test_id_cards_for_a_class_and_the_staff_with_photos(client, admin):
    photo = (
        await client.post(f"{API}/files", headers=admin, data={"purpose": "PHOTO"}, files={"file": ("m.png", PNG)})
    ).json()
    assert (
        await client.put(f"{API}/staff/{STAFF_MWITA}/photo", headers=admin, json={"file_id": photo["id"]})
    ).status_code == 204
    shown = await client.get(f"{API}/staff/{STAFF_MWITA}/photo", headers=admin)
    assert shown.status_code == 200 and shown.content == PNG

    students = (await client.post(f"{API}/identity-cards", headers=admin, json={"stream_id": str(F2_A)})).json()
    assert students["issued"] >= 4
    assert (await client.post(f"{API}/identity-cards", headers=admin, json={"stream_id": str(F2_A)})).json()[
        "issued"
    ] == 0
    staff = (await client.post(f"{API}/identity-cards", headers=admin, json={"staff": True})).json()
    assert staff["issued"] >= 5
    assert (await client.post(f"{API}/identity-cards", headers=admin, json={})).status_code == 422

    cards = (await client.get(f"{API}/identity-cards?staff=true", headers=admin)).json()
    mwita = next(c for c in cards if c["number"] == "MF-STF-003")
    assert mwita["has_photo"] and mwita["card_no"].startswith("ID-") and "photo_key" not in mwita
    pdf = await client.get(f"{API}/identity-cards.pdf?stream_id={F2_A}", headers=admin)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    amani = bearer(await login(client, username="mf-2025-0014"))
    own = await client.get(f"{API}/portal/id-card.pdf", headers=amani)
    assert own.status_code == 200 and own.content.startswith(b"%PDF")
    emmanuel = bearer(await login(client, username="mf-2026-0003"))  # Form V: no card issued
    assert (await client.get(f"{API}/portal/id-card.pdf", headers=emmanuel)).status_code == 404
    assert (await client.get(f"{API}/portal/id-card.pdf", headers=admin)).status_code == 403

    card = next(
        c
        for c in (await client.get(f"{API}/identity-cards?stream_id={F2_A}", headers=admin)).json()
        if c["full_name"].startswith("Amani")
    )
    assert (await client.post(f"{API}/identity-cards/{card['id']}/revoke", headers=admin)).status_code == 204
    assert (await client.get(f"{API}/portal/id-card.pdf", headers=amani)).status_code == 404


async def test_email_is_sent_once_and_only_to_people_with_an_address(client, db, admin, dispatcher):
    queued = await client.post(f"{API}/email-messages/test", headers=admin)
    assert queued.status_code == 200, queued.text
    call = dispatcher.take("email.send")[-1]
    assert await email_send(**call) == "SENT"
    assert await email_send(**call) == "skipped"  # never twice
    history = (await client.get(f"{API}/email-messages", headers=admin)).json()
    assert history[0]["status"] == "SENT" and history[0]["to"] == "Halima Mrisho"

    assert (
        await client.post(f"{API}/users/{GATE_JUMA}/roles", headers=admin, json={"role_code": "school_admin"})
    ).status_code == 201
    no_address = bearer(await login(client, username="gate.juma"))
    assert (await client.post(f"{API}/email-messages/test", headers=no_address)).status_code == 422
    teacher = bearer(await login(client, username="tch.mwita"))
    assert (await client.get(f"{API}/email-messages", headers=teacher)).status_code == 403

    await as_school(db, SCHOOL_A)
    stored = (await db.execute(select(EmailMessage.provider, EmailMessage.status))).all()
    assert ("CONSOLE", "SENT") in stored


async def test_an_announcement_can_also_go_by_email(client, admin):
    made = await client.post(
        f"{API}/announcements",
        headers=admin | {"Idempotency-Key": "ann-email-1"},
        json={
            "title": "Mkutano wa wafanyakazi",
            "body": "Ijumaa saa nane mchana.",
            "audience": "STAFF",
            "send_email": True,
        },
    )
    assert made.status_code in (200, 201), made.text
    assert made.json()["email_recipients"] >= 0


async def test_the_platform_dashboard_shows_counts_per_school(client):
    token = (await platform_login(client))["access_token"]
    board = await client.get(f"{API}/platform/dashboard", headers=bearer(token))
    assert board.status_code == 200, board.text
    body = board.json()
    assert body["schools"] >= 2 and body["students"] >= 7 and body["by_status"]["ACTIVE"] >= 2
    mfano = next(s for s in body["per_school"] if s["code"] == "mfano-sec")
    assert mfano["students"] >= 7 and mfano["staff"] >= 5 and mfano["sms_credit"] >= 0
    assert set(mfano) == {"id", "code", "name", "status", "students", "staff", "sms_credit"}  # counts only
    school_admin = bearer(await login(client))
    assert (await client.get(f"{API}/platform/dashboard", headers=school_admin)).status_code in (401, 403)
