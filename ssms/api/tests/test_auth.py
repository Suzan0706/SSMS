"""Authentication: password login, lockout, refresh rotation and reuse detection, logout, password change,
parent OTP login (one and several schools), rate limits, audit events. All through the API as ssms_app."""

from sqlalchemy import func, select, text, update

from app.models import AuditLog, SmsMessage, User
from app.services import auth as auth_service
from app.tasks.handlers import sms_send
from tests.helpers import (
    ADMIN_A,
    GUARDIAN_A,
    GUARDIAN_B,
    PASSWORD,
    SCHOOL_A,
    SCHOOL_B,
    SHARED_PHONE,
    as_school,
    bearer,
    login,
    rekey_phone,
)

LOGIN = "/api/v1/auth/login"


async def test_runtime_role_is_ssms_app_without_bypass(db):
    """Rule: every RLS test runs as SET ROLE ssms_app; neither role is a superuser or bypasses RLS."""
    rows = (
        await db.execute(
            text(
                "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname IN (current_user, session_user)"
                " ORDER BY rolname"
            )
        )
    ).all()
    assert [tuple(r) for r in rows] == [("ssms_app", False, False), ("ssms_tester", False, False)]
    assert (await db.execute(text("SELECT current_user"))).scalar() == "ssms_app"


async def test_login_returns_token_profile_and_refresh_cookie(client):
    response = await client.post(LOGIN, json={"school_code": "MFANO-SEC", "username": "Admin", "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 900
    assert body["school"]["code"] == "mfano-sec"
    assert "school_admin" in body["roles"] and "students.create" in body["permissions"]
    cookie = response.headers["set-cookie"]
    assert "ssms_rt=" in cookie and "HttpOnly" in cookie and "Path=/api/v1/auth" in cookie
    assert "samesite=strict" in cookie.lower()

    me = await client.get("/api/v1/auth/me", headers=bearer(body))
    assert me.status_code == 200 and me.json()["user"]["id"] == str(ADMIN_A)


async def test_wrong_password_unknown_user_and_unknown_school_look_the_same(client):
    for payload in (
        {"school_code": "mfano-sec", "username": "admin", "password": "wrong-password"},
        {"school_code": "mfano-sec", "username": "nobody", "password": PASSWORD},
        {"school_code": "no-such-school", "username": "admin", "password": PASSWORD},
    ):
        response = await client.post(LOGIN, json=payload)
        assert response.status_code == 401
        assert response.json() == {
            "error_code": "INVALID_CREDENTIALS",
            "message": "Jina la mtumiaji au nenosiri si sahihi.",
            "details": [],
        }


async def test_error_message_follows_accept_language(client):
    response = await client.post(
        LOGIN,
        json={"school_code": "mfano-sec", "username": "admin", "password": "x"},
        headers={"Accept-Language": "en"},
    )
    assert response.json()["message"] == "Invalid username or password."


async def test_lockout_after_five_failures_then_even_the_right_password_is_refused(client, db):
    for _ in range(4):
        assert (
            await client.post(LOGIN, json={"school_code": "mfano-sec", "username": "bursar", "password": "bad"})
        ).status_code == 401
    fifth = await client.post(LOGIN, json={"school_code": "mfano-sec", "username": "bursar", "password": "bad"})
    assert fifth.status_code == 423 and fifth.json()["error_code"] == "ACCOUNT_LOCKED"
    right = await client.post(LOGIN, json={"school_code": "mfano-sec", "username": "bursar", "password": PASSWORD})
    assert right.status_code == 423

    await as_school(db, SCHOOL_A)
    reasons = (
        (
            await db.execute(
                select(AuditLog.after_data["reason"].astext).where(
                    AuditLog.action == "LOGIN_FAILED",
                    AuditLog.entity_id == (select(User.id).where(User.username == "bursar").scalar_subquery()),
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(reasons) == ["locked", "locked_now", "password", "password", "password", "password"]


async def test_login_rate_limit(client):
    codes = [
        (
            await client.post(LOGIN, json={"school_code": "mfano-sec", "username": "tch.mwita", "password": "bad"})
        ).status_code
        for _ in range(12)
    ]
    assert codes[-1] == 429


async def test_login_writes_audit_event_but_no_row_audit_for_bookkeeping(client, db):
    await as_school(db, SCHOOL_A)
    before = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.entity_type == "users", AuditLog.action == "UPDATE")
        )
    ).scalar()
    await login(client)
    events = (await db.execute(select(AuditLog.action, AuditLog.actor_user_id).where(AuditLog.action == "LOGIN"))).all()
    assert ("LOGIN", ADMIN_A) in [tuple(e) for e in events]
    after = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.entity_type == "users", AuditLog.action == "UPDATE")
        )
    ).scalar()
    assert after == before


async def test_missing_and_invalid_tokens(client):
    missing = await client.get("/api/v1/auth/me")
    assert missing.status_code == 401 and missing.json()["error_code"] == "NOT_AUTHENTICATED"
    invalid = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert invalid.status_code == 401 and invalid.json()["error_code"] == "INVALID_TOKEN"


async def test_disabled_user_token_stops_working(client, db):
    body = await login(client)
    await as_school(db, SCHOOL_A)
    await db.execute(update(User).where(User.id == ADMIN_A).values(status="DISABLED"))
    await db.commit()
    assert (await client.get("/api/v1/auth/me", headers=bearer(body))).status_code == 401


async def test_refresh_rotates_cookie(client):
    await login(client)
    first = client.cookies.get("ssms_rt")
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 200 and response.json()["access_token"]
    assert client.cookies.get("ssms_rt") not in (None, first)


async def test_reused_refresh_token_revokes_the_family(client, monkeypatch):
    await login(client)
    stolen = client.cookies.get("ssms_rt")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200
    current = client.cookies.get("ssms_rt")
    monkeypatch.setattr(auth_service, "REUSE_GRACE_SECONDS", -1)

    client.cookies.clear()
    reuse = await client.post("/api/v1/auth/refresh", headers={"Cookie": f"ssms_rt={stolen}"})
    assert reuse.status_code == 401 and reuse.json()["error_code"] == "INVALID_TOKEN"
    client.cookies.clear()
    assert (await client.post("/api/v1/auth/refresh", headers={"Cookie": f"ssms_rt={current}"})).status_code == 401


async def test_parallel_refresh_within_grace_does_not_revoke_the_family(client):
    await login(client)
    old = client.cookies.get("ssms_rt")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200
    current = client.cookies.get("ssms_rt")
    client.cookies.clear()
    assert (await client.post("/api/v1/auth/refresh", headers={"Cookie": f"ssms_rt={old}"})).status_code == 401
    client.cookies.clear()
    assert (await client.post("/api/v1/auth/refresh", headers={"Cookie": f"ssms_rt={current}"})).status_code == 200


async def test_logout_revokes_refresh_token(client):
    await login(client)
    token = client.cookies.get("ssms_rt")
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    client.cookies.clear()
    assert (await client.post("/api/v1/auth/refresh", headers={"Cookie": f"ssms_rt={token}"})).status_code == 401


async def test_change_password(client):
    body = await login(client)
    weak = await client.post(
        "/api/v1/auth/change-password",
        headers=bearer(body),
        json={"current_password": PASSWORD, "new_password": "short1"},
    )
    assert weak.status_code == 422 and weak.json()["error_code"] == "WEAK_PASSWORD"
    wrong = await client.post(
        "/api/v1/auth/change-password",
        headers=bearer(body),
        json={"current_password": "nope", "new_password": "Kilimanjaro2026"},
    )
    assert wrong.status_code == 401
    ok = await client.post(
        "/api/v1/auth/change-password",
        headers=bearer(body),
        json={"current_password": PASSWORD, "new_password": "Kilimanjaro2026"},
    )
    assert ok.status_code == 204
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200  # this device stays signed in
    await login(client, password="Kilimanjaro2026")


# ---------------------------------------------------------------- parent OTP


async def test_otp_for_unknown_phone_answers_the_same_and_sends_nothing(client, dispatcher):
    response = await client.post("/api/v1/auth/otp/request", json={"phone": "0700000099"})
    assert response.status_code == 200 and response.json()["sent"] is True
    assert dispatcher.sent == []


async def test_otp_rejects_malformed_phone(client):
    response = await client.post("/api/v1/auth/otp/request", json={"phone": "12345"})
    assert response.status_code == 422
    assert response.json()["details"][0]["field"] == "phone"
    assert response.json()["details"][0]["code"] == "invalid_phone"


async def _request_code(client, dispatcher, phone: str = "0754000021") -> str:
    assert (await client.post("/api/v1/auth/otp/request", json={"phone": phone})).status_code == 200
    calls = dispatcher.take("sms.send")
    assert len(calls) == 1
    return (
        calls[0]["text"].split(" ni ")[1].split(".")[0]
        if " ni " in calls[0]["text"]
        else calls[0]["text"].split(" is ")[1].split(".")[0]
    )


async def test_otp_login_single_school(client, db, dispatcher):
    await rekey_phone(db, SCHOOL_A, GUARDIAN_A, SHARED_PHONE)
    code = await _request_code(client, dispatcher)
    assert len(code) == 6 and code.isdigit()

    await as_school(db, SCHOOL_A)
    stored = (await db.execute(select(SmsMessage.body, SmsMessage.to_phone_last4))).all()
    assert any("******" in b and code not in b and last4 == "0021" for b, last4 in stored)

    wrong = await client.post(
        "/api/v1/auth/otp/verify", json={"phone": "+255754000021", "code": "000000" if code != "000000" else "111111"}
    )
    assert wrong.status_code == 401 and wrong.json()["error_code"] == "OTP_INVALID"
    response = await client.post("/api/v1/auth/otp/verify", json={"phone": "255754000021", "code": code})
    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["parent"] and response.json()["permissions"] == ["portal.parent"]
    assert "Max-Age=2592000" in response.headers["set-cookie"]  # 30-day parent session
    again = await client.post("/api/v1/auth/otp/verify", json={"phone": "255754000021", "code": code})
    assert again.status_code == 401  # one-time code


async def test_otp_login_two_schools_requires_a_choice(client, db, dispatcher):
    await rekey_phone(db, SCHOOL_A, GUARDIAN_A, SHARED_PHONE)
    await rekey_phone(db, SCHOOL_B, GUARDIAN_B, SHARED_PHONE)
    code = await _request_code(client, dispatcher)
    response = await client.post("/api/v1/auth/otp/verify", json={"phone": SHARED_PHONE, "code": code})
    assert response.status_code == 200
    body = response.json()
    assert {c["school_id"] for c in body["choose"]} == {str(SCHOOL_A), str(SCHOOL_B)}

    bogus = await client.post(
        "/api/v1/auth/select-school", json={"selection_token": body["selection_token"], "school_id": str(ADMIN_A)}
    )
    assert bogus.status_code == 401
    chosen = await client.post(
        "/api/v1/auth/select-school", json={"selection_token": body["selection_token"], "school_id": str(SCHOOL_B)}
    )
    assert chosen.status_code == 200 and chosen.json()["school"]["code"] == "upendo-pri"
    assert chosen.json()["user"]["id"] == str(GUARDIAN_B)


async def test_otp_attempts_are_limited(client, db, dispatcher):
    await rekey_phone(db, SCHOOL_A, GUARDIAN_A, SHARED_PHONE)
    code = await _request_code(client, dispatcher)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert (
            await client.post("/api/v1/auth/otp/verify", json={"phone": SHARED_PHONE, "code": wrong})
        ).status_code == 401
    late = await client.post("/api/v1/auth/otp/verify", json={"phone": SHARED_PHONE, "code": code})
    assert late.status_code == 401


async def test_otp_request_rate_limit(client, db, dispatcher):
    await rekey_phone(db, SCHOOL_A, GUARDIAN_A, SHARED_PHONE)
    codes = [
        (await client.post("/api/v1/auth/otp/request", json={"phone": SHARED_PHONE})).status_code for _ in range(4)
    ]
    assert codes == [200, 200, 200, 429]


async def test_sms_task_sends_once(client, db, dispatcher):
    await rekey_phone(db, SCHOOL_A, GUARDIAN_A, SHARED_PHONE)
    await client.post("/api/v1/auth/otp/request", json={"phone": SHARED_PHONE})
    call = dispatcher.take("sms.send")[0]
    assert await sms_send(**call) == "sent"
    assert await sms_send(**call) == "skipped"  # idempotent retry
    await as_school(db, SCHOOL_A)
    status = (await db.execute(select(SmsMessage.status).where(SmsMessage.id == call["sms_id"]))).scalar()
    assert status == "SENT"
