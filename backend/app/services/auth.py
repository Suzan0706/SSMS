"""Login with lockout, refresh-token rotation with reuse detection, logout, password change."""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, rule_violation
from app.core.security import (DUMMY_HASH, create_access_token, hash_password, is_strong_password,
                               new_refresh_token, sha256_hex, verify_password)
from app.db import set_audit_context
from app.models import RefreshToken, User
from app.schemas.auth import TokenPair
from app.services.common import RequestMeta, record_event

INVALID_LOGIN = AppError(401, "INVALID_CREDENTIALS", "Invalid username or password",
                         "Jina la mtumiaji au nenosiri si sahihi")
INVALID_TOKEN = AppError(401, "INVALID_TOKEN", "Session expired, please log in again",
                         "Muda wa kuingia umeisha, tafadhali ingia tena")


def _issue_tokens(db: Session, user: User, family_id: uuid.UUID, meta: RequestMeta) -> TokenPair:
    settings = get_settings()
    raw, digest = new_refresh_token()
    db.add(RefreshToken(
        user_id=user.user_id, token_hash=digest, family_id=family_id,
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        user_agent=(meta.user_agent or "")[:255] or None, ip_address=meta.ip,
    ))
    return TokenPair(access_token=create_access_token(user.user_id, user.role.value), refresh_token=raw,
                     expires_in=settings.access_token_minutes * 60)


def login(db: Session, username: str, password: str, meta: RequestMeta) -> TokenPair:
    settings = get_settings()
    name = username.strip().lower()
    user = db.scalar(select(User).where(or_(func.lower(User.username) == name, func.lower(User.email) == name)))
    now = datetime.now(UTC)

    if user is None or not user.is_active:
        verify_password(password, DUMMY_HASH)                 # same cost as a real check
        record_event(db, "LOGIN_FAILED", meta, details={"username": name[:50], "reason": "unknown_or_inactive"})
        db.commit()
        raise INVALID_LOGIN

    set_audit_context(db, user_id=user.user_id, user_role=user.role.value,
                      client_ip=meta.ip, request_id=meta.request_id)

    if user.locked_until and user.locked_until > now:
        record_event(db, "LOGIN_FAILED", meta, actor=user, entity_id=user.user_id, details={"reason": "locked"})
        db.commit()
        raise AppError(423, "ACCOUNT_LOCKED", "Account locked after too many failed attempts",
                       "Akaunti imefungwa kwa majaribio mengi yasiyo sahihi",
                       {"locked_until": user.locked_until.isoformat()})

    valid, new_hash = verify_password(password, user.password_hash)
    if not valid:
        user.failed_login_count += 1
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_login_count = 0
        record_event(db, "LOGIN_FAILED", meta, actor=user, entity_id=user.user_id, details={"reason": "password"})
        db.commit()
        raise INVALID_LOGIN

    if new_hash:                                              # Argon2 parameters were upgraded
        user.password_hash = new_hash
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    tokens = _issue_tokens(db, user, uuid.uuid4(), meta)
    record_event(db, "LOGIN", meta, actor=user, entity_id=user.user_id)
    db.commit()
    return tokens


def refresh(db: Session, raw_token: str, meta: RequestMeta) -> TokenPair:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw_token))
                      .with_for_update())
    now = datetime.now(UTC)
    if token is None:
        raise INVALID_TOKEN
    user = db.get(User, token.user_id)
    if token.revoked_at is not None:
        # A rotated token was used again: assume theft and end every session in this chain.
        db.execute(update(RefreshToken)
                   .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
                   .values(revoked_at=now))
        record_event(db, "TOKEN_REUSE", meta, actor=user, entity_id=token.user_id,
                     details={"family_id": str(token.family_id)})
        db.commit()
        raise INVALID_TOKEN
    if token.expires_at <= now or user is None or not user.is_active:
        raise INVALID_TOKEN
    token.revoked_at = now
    tokens = _issue_tokens(db, user, token.family_id, meta)
    record_event(db, "TOKEN_REFRESH", meta, actor=user, entity_id=user.user_id)
    db.commit()
    return tokens


def logout(db: Session, raw_token: str, user: User, meta: RequestMeta) -> None:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw_token),
                                                 RefreshToken.user_id == user.user_id))
    if token is not None:
        db.execute(update(RefreshToken)
                   .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
                   .values(revoked_at=datetime.now(UTC)))
    record_event(db, "LOGOUT", meta, actor=user, entity_id=user.user_id)
    db.commit()


def revoke_all_tokens(db: Session, user_id: int) -> None:
    db.execute(update(RefreshToken)
               .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=datetime.now(UTC)))


def change_password(db: Session, user: User, current: str, new: str, meta: RequestMeta) -> None:
    valid, _ = verify_password(current, user.password_hash)
    if not valid:
        raise INVALID_LOGIN
    if not is_strong_password(new):
        raise rule_violation("Password must be at least 10 characters with letters and digits",
                             "Nenosiri liwe na herufi 10 au zaidi, zikiwemo herufi na tarakimu")
    user.password_hash = hash_password(new)
    revoke_all_tokens(db, user.user_id)
    record_event(db, "PASSWORD_CHANGE", meta, actor=user, entity_id=user.user_id)
    db.commit()
