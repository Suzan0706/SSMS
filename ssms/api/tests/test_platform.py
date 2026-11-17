"""Super-admin console: TOTP sign-in, token audiences, school registry, onboarding defaults, suspension."""

import pyotp
from sqlalchemy import func, select, update

from app.core.crypto import get_cipher
from app.db.session import provider
from app.models import AuditLog, GradeBand, PlatformAdmin, SchoolClass, SchoolSettings, SmsMessage, Stream, User
from app.services import platform as platform_service
from tests.helpers import PASSWORD, SCHOOL_A, as_school, bearer, login, u

OPS = {"email": "ops@ssms.co.tz", "password": PASSWORD}
NEW_SCHOOL = {
    "code": "tumaini-sec",
    "name": "Shule ya Sekondari Tumaini",
    "registration_no": "S.5120",
    "ownership": "PRIVATE",
    "levels": ["O_LEVEL", "A_LEVEL"],
    "admin": {
        "first_name": "Asha",
        "last_name": "Mwakyusa",
        "gender": "F",
        "phone": "0713555777",
        "email": "head@tumaini.sc.tz",
    },
}


async def school_body(client, headers) -> dict:
    regions = (await client.get("/api/v1/platform/regions", headers=headers)).json()
    morogoro = next(r for r in regions if r["name"] == "Morogoro")
    district = next(d for d in morogoro["districts"] if d["name"] == "Morogoro Municipal")
    return {**NEW_SCHOOL, "district_id": district["id"]}


async def platform_login(client) -> dict:
    response = await client.post("/api/v1/platform/auth/login", json=OPS)
    assert response.status_code == 200, response.text
    return response.json()


async def test_console_login_and_audiences(client):
    console = await platform_login(client)
    assert console["admin"]["email"] == "ops@ssms.co.tz"
    bad = await client.post("/api/v1/platform/auth/login", json={**OPS, "password": "wrong-one"})
    assert bad.status_code == 401
    school_token = await login(client)
    assert (await client.get("/api/v1/platform/schools", headers=bearer(school_token))).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=bearer(console))).status_code == 401


async def test_console_totp(client):
    secret = pyotp.random_base32()
    async with provider.platform() as session:
        await session.execute(
            update(PlatformAdmin)
            .where(PlatformAdmin.id == u(50, 1))
            .values(mfa_secret_enc=get_cipher().encrypt(secret, platform_service.MFA_FIELD))
        )
        await session.commit()
    missing = await client.post("/api/v1/platform/auth/login", json=OPS)
    assert missing.status_code == 401 and missing.json()["error_code"] == "MFA_REQUIRED"
    wrong = await client.post("/api/v1/platform/auth/login", json={**OPS, "totp": "000000"})
    assert wrong.status_code == 401
    ok = await client.post("/api/v1/platform/auth/login", json={**OPS, "totp": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200


async def test_create_platform_admin_returns_provisioning_uri():
    async with provider.platform() as session:
        admin, uri = await platform_service.create_admin(session, "Second Operator", "Two@SSMS.co.tz", "Operator2026x")
    assert admin.email == "two@ssms.co.tz" and admin.mfa_secret_enc and uri.startswith("otpauth://totp/")


async def test_list_schools_with_cursor_and_filter(client):
    headers = bearer(await platform_login(client))
    first = (await client.get("/api/v1/platform/schools?limit=1", headers=headers)).json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    second = (
        await client.get(f"/api/v1/platform/schools?limit=1&cursor={first['next_cursor']}", headers=headers)
    ).json()
    assert second["items"][0]["id"] != first["items"][0]["id"]
    active = (await client.get("/api/v1/platform/schools?status=ACTIVE", headers=headers)).json()
    assert {s["code"] for s in active["items"]} >= {"mfano-sec", "upendo-pri"}
    bad = await client.get("/api/v1/platform/schools?cursor=not-a-cursor", headers=headers)
    assert bad.status_code == 422 and bad.json()["details"][0]["field"] == "cursor"
    too_big = await client.get("/api/v1/platform/schools?limit=500", headers=headers)
    assert too_big.status_code == 422


async def test_create_school_with_defaults_and_first_login(client, db, dispatcher):
    headers = bearer(await platform_login(client))
    response = await client.post("/api/v1/platform/schools", json=await school_body(client, headers), headers=headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["school"]["status"] == "ONBOARDING" and body["admin_username"] == "admin"
    assert body["school"]["region"] == "Morogoro" and body["school"]["district"] == "Morogoro Municipal"
    assert body["defaults"] == {
        "academic_years": 1,
        "terms": 2,
        "public_holidays": 11,
        "education_levels": 2,
        "assessment_components": 8,
        "classes": 6,
        "streams": 6,
        "grading_schemes": 2,
        "grade_bands": 12,
        "division_rules": 10,
        "departments": 5,
        "designations": 5,
        "ledger_accounts": 21,
        "fee_items": 7,
        "finance_categories": 7,
        "message_templates": 16,
    }
    school_id = body["school"]["id"]

    [call] = dispatcher.take("sms.send")
    assert body["temporary_password"] in call["text"]
    await as_school(db, school_id)
    stored = (await db.execute(select(SmsMessage.body))).scalars().all()
    assert len(stored) == 1 and body["temporary_password"] not in stored[0]
    assert (await db.execute(select(SchoolSettings.admission_prefix))).scalar() == "TUM"
    f1 = (await db.execute(select(SchoolClass.next_class_id).where(SchoolClass.code == "F1"))).scalar()
    f2 = (await db.execute(select(SchoolClass.id).where(SchoolClass.code == "F2"))).scalar()
    assert f1 == f2
    assert (await db.execute(select(func.count()).select_from(Stream))).scalar() == 6
    bands = (await db.execute(select(func.count()).select_from(GradeBand))).scalar()
    assert bands == 12
    actors = (
        (await db.execute(select(AuditLog.actor_platform_id).where(AuditLog.entity_type == "users"))).scalars().all()
    )
    assert actors == [u(50, 1)]  # row audit knows the console operator

    first = await login(client, school="tumaini-sec", password=body["temporary_password"])
    assert first["user"]["must_change_password"] is True and first["roles"] == ["school_admin"]

    duplicate = await client.post("/api/v1/platform/schools", json=await school_body(client, headers), headers=headers)
    assert duplicate.status_code == 409 and duplicate.json()["error_code"] == "DUPLICATE"


async def test_create_school_validation(client):
    headers = bearer(await platform_login(client))
    bad = {**NEW_SCHOOL, "code": "Bad Code", "levels": [], "admin": {**NEW_SCHOOL["admin"], "phone": "123"}}
    response = await client.post("/api/v1/platform/schools", json=bad, headers=headers)
    assert response.status_code == 422
    fields = {d["field"]: d["code"] for d in response.json()["details"]}
    assert fields["admin.phone"] == "invalid_phone" and "code" in fields and "levels" in fields


async def test_suspending_a_school_blocks_its_users(client, db):
    staff = await login(client)
    headers = bearer(await platform_login(client))
    response = await client.patch(
        f"/api/v1/platform/schools/{SCHOOL_A}",
        headers=headers,
        json={"status": "SUSPENDED", "reason": "Unpaid subscription"},
    )
    assert response.status_code == 200 and response.json()["status"] == "SUSPENDED"
    assert (await client.get("/api/v1/auth/me", headers=bearer(staff))).status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/login", json={"school_code": "mfano-sec", "username": "admin", "password": PASSWORD}
        )
    ).status_code == 401
    await as_school(db, SCHOOL_A)
    event = (await db.execute(select(AuditLog.after_data).where(AuditLog.entity_type == "schools"))).scalar()
    assert event == {"status": "SUSPENDED", "previous": "ACTIVE", "reason": "Unpaid subscription"}

    closed = await client.patch(
        f"/api/v1/platform/schools/{SCHOOL_A}", headers=headers, json={"status": "CLOSED", "reason": "School closed"}
    )
    assert closed.status_code == 200
    reopen = await client.patch(
        f"/api/v1/platform/schools/{SCHOOL_A}", headers=headers, json={"status": "ACTIVE", "reason": "Try to reopen"}
    )
    assert reopen.status_code == 409 and reopen.json()["error_code"] == "STATUS_TRANSITION"
    missing = await client.patch(
        f"/api/v1/platform/schools/{u(1, 99)}", headers=headers, json={"status": "ACTIVE", "reason": "No such school"}
    )
    assert missing.status_code == 404


async def test_new_users_are_invisible_to_other_schools(client, db, dispatcher):
    headers = bearer(await platform_login(client))
    body = await school_body(client, headers)
    school_id = (await client.post("/api/v1/platform/schools", json=body, headers=headers)).json()["school"]["id"]
    await as_school(db, SCHOOL_A)
    seen = (await db.execute(select(func.count()).select_from(User).where(User.school_id == school_id))).scalar()
    assert seen == 0
