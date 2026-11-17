from sqlalchemy import select

from app.models import AuditLog, User
from tests.conftest import PASSWORD, login

API = "/api/v1"


def test_login_returns_tokens_and_profile(client):
    r = client.post(f"{API}/auth/login", data={"username": "REGISTRAR", "password": PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 15 * 60
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["role"] == "REGISTRAR"
    assert "password_hash" not in me.json()


def test_wrong_password_and_unknown_user_give_the_same_generic_401(client):
    wrong = client.post(f"{API}/auth/login", data={"username": "registrar", "password": "nope-12345"})
    unknown = client.post(f"{API}/auth/login", data={"username": "ghost", "password": "nope-12345"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert unknown.json()["detail"]["message_sw"] == "Jina la mtumiaji au nenosiri si sahihi"


def test_account_locks_after_five_failures(client):
    for _ in range(5):
        assert client.post(f"{API}/auth/login", data={"username": "bursar", "password": "bad-pass-123"}).status_code == 401
    locked = client.post(f"{API}/auth/login", data={"username": "bursar", "password": PASSWORD})
    assert locked.status_code == 423
    assert "locked_until" in locked.json()["detail"]


def test_refresh_rotates_and_reuse_revokes_the_family(client):
    first = client.post(f"{API}/auth/login", data={"username": "admin", "password": PASSWORD}).json()
    second = client.post(f"{API}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    # the old token is replayed (e.g. stolen): it fails and the new one is revoked too
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401
    assert client.post(f"{API}/auth/refresh",
                       json={"refresh_token": second.json()["refresh_token"]}).status_code == 401


def test_student_cannot_register_students(client):
    headers = login(client, "s2026-0003")
    r = client.post(f"{API}/students", headers=headers, json={})
    assert r.status_code == 403


def test_missing_token_is_401(client):
    assert client.get(f"{API}/students").status_code == 401


def test_login_and_failure_are_audited(client, db):
    client.post(f"{API}/auth/login", data={"username": "tch.mwita", "password": "bad-pass-123"})
    login(client, "tch.mwita")
    user = db.scalar(select(User).where(User.username == "tch.mwita"))
    actions = db.scalars(select(AuditLog.action).where(AuditLog.actor_user_id == user.user_id,
                                                       AuditLog.action.in_(["LOGIN", "LOGIN_FAILED"]))).all()
    assert "LOGIN" in actions and "LOGIN_FAILED" in actions
