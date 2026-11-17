"""Authentication: password login with lockout, rotating refresh tokens, parent OTP login, password change.

Refresh tokens are opaque random strings; only their SHA-256 is stored. Each login starts a token family.
Refresh rotates the token inside the family. Presenting an already-rotated token after the grace period is
treated as theft: the whole family is revoked and a TOKEN_REUSE audit event is written.
"""

import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import jwt
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OPEN_SCHOOL_STATUSES, load_access
from app.core.config import get_settings
from app.core.crypto import get_cipher
from app.core.errors import AppError
from app.core.ratelimit import enforce
from app.core.security import (
    create_access_token,
    create_selection_token,
    decode_token,
    hash_password_async,
    is_strong_password,
    new_opaque_token,
    new_otp_code,
    otp_hash,
    sha256_hex,
    verify_password_async,
)
from app.db.session import DbContext, set_context
from app.models import OtpCode, RefreshToken, School, User
from app.models.enums import OtpPurpose, UserStatus
from app.services import audit, sms

log = logging.getLogger(__name__)
EAT = timezone(timedelta(hours=3), "EAT")  # Tanzania, no daylight saving
REUSE_GRACE_SECONDS = 10  # two tabs refreshing at the same moment is not theft
OTP_TEXT = {
    "sw": "SSMS: namba yako ya kuingia ni {code}. Itaisha baada ya dakika {minutes}. Usimpe mtu yeyote.",
    "en": "SSMS: your login code is {code}. It expires in {minutes} minutes. Do not share it.",
}


@dataclass
class SignIn:
    """Result of a successful sign-in: everything the API returns plus the refresh cookie value."""

    access_token: str
    refresh_token: str
    refresh_max_age: int
    user: User
    school: School
    roles: frozenset[str]
    permissions: frozenset[str]


@dataclass
class SchoolSelection:
    choices: list[tuple[uuid.UUID, str]]
    selection_token: str


def _now() -> datetime:
    return datetime.now(UTC)


async def _context(
    session: AsyncSession, base: DbContext, school_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> None:
    await set_context(
        session, DbContext(school_id=school_id, user_id=user_id, client_ip=base.client_ip, request_id=base.request_id)
    )


async def _issue(
    session: AsyncSession, base: DbContext, user: User, user_agent: str | None, family_id: uuid.UUID | None = None
) -> SignIn:
    """Create the refresh token row and the access token for a user in the current school context."""
    settings = get_settings()
    roles, permissions = await load_access(session, user.id)
    days = settings.parent_refresh_token_days if roles == {"parent"} else settings.refresh_token_days
    raw, digest = new_opaque_token()
    now = _now()
    session.add(
        RefreshToken(
            school_id=user.school_id,
            user_id=user.id,
            token_hash=digest,
            family_id=family_id or uuid.uuid4(),
            issued_at=now,
            expires_at=now + timedelta(days=days),
            user_agent=(user_agent or "")[:255] or None,
            ip_address=base.client_ip,
        )
    )
    school = (await session.execute(select(School).where(School.id == user.school_id))).scalar_one()
    return SignIn(
        access_token=create_access_token(user.id, user.school_id, sorted(roles)),
        refresh_token=raw,
        refresh_max_age=days * 86400,
        user=user,
        school=school,
        roles=roles,
        permissions=permissions,
    )


async def login(
    session: AsyncSession, base: DbContext, school_code: str, username: str, password: str, user_agent: str | None
) -> SignIn:
    settings = get_settings()
    username_key = username.strip().lower()
    await enforce(f"login:ip:{base.client_ip}", settings.login_attempts_per_minute * 3, 60)
    await enforce(f"login:user:{school_code.lower()}:{username_key}", settings.login_attempts_per_minute, 60)

    school_id = (await session.execute(select(func.resolve_school_by_code(school_code)))).scalar()
    if school_id is None:
        await verify_password_async(password, None)  # same timing as a wrong password
        raise AppError(401, "INVALID_CREDENTIALS")
    await _context(session, base, school_id)
    user = (
        await session.execute(
            select(User).where(func.lower(User.username) == username_key, User.deleted_at.is_(None)).with_for_update()
        )
    ).scalar_one_or_none()
    if user is None:
        await verify_password_async(password, None)
        await audit.record(
            session,
            "LOGIN_FAILED",
            "users",
            after={"username": username_key, "reason": "unknown"},
            user_agent=user_agent,
        )
        await session.commit()
        raise AppError(401, "INVALID_CREDENTIALS")

    now = _now()
    if user.locked_until and user.locked_until > now:
        await verify_password_async(password, None)
        await audit.record(session, "LOGIN_FAILED", "users", user.id, {"reason": "locked"}, user_agent, user.id)
        await session.commit()
        raise AppError(423, "ACCOUNT_LOCKED", until=user.locked_until.astimezone(EAT).strftime("%H:%M"))

    valid, new_hash = await verify_password_async(password, user.password_hash)
    if not valid or user.status != UserStatus.ACTIVE:
        reason = "password" if not valid else f"status_{user.status.lower()}"
        if not valid:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.max_failed_logins:
                user.failed_login_count = 0
                user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
                reason = "locked_now"
        await audit.record(session, "LOGIN_FAILED", "users", user.id, {"reason": reason}, user_agent, user.id)
        await session.commit()
        if reason == "locked_now":
            raise AppError(423, "ACCOUNT_LOCKED", until=user.locked_until.astimezone(EAT).strftime("%H:%M"))
        raise AppError(401, "INVALID_CREDENTIALS")

    user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now
    if new_hash:
        user.password_hash = new_hash  # Argon2 parameters were upgraded
    await _context(session, base, school_id, user.id)
    result = await _issue(session, base, user, user_agent)
    await audit.record(session, "LOGIN", "users", user.id, {"method": "password"}, user_agent)
    await session.commit()
    return result


async def _token_owner(session: AsyncSession, raw: str | None) -> tuple[uuid.UUID, uuid.UUID, str] | None:
    if not raw:
        return None
    digest = sha256_hex(raw)
    row = (
        await session.execute(
            select(func.resolve_refresh_token(digest).table_valued("school_id", "user_id", "family_id"))
        )
    ).first()
    return (row.school_id, row.user_id, digest) if row else None


async def refresh(session: AsyncSession, base: DbContext, raw: str | None, user_agent: str | None) -> SignIn:
    owner = await _token_owner(session, raw)
    if owner is None:
        raise AppError(401, "INVALID_TOKEN")
    school_id, user_id, digest = owner
    await _context(session, base, school_id, user_id)
    token = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == digest).with_for_update())
    ).scalar_one()
    now = _now()
    if token.revoked_at is not None:
        if now - token.revoked_at > timedelta(seconds=REUSE_GRACE_SECONDS):
            await _revoke_family(session, token.family_id, now)
            await audit.record(
                session, "TOKEN_REUSE", "refresh_tokens", token.id, {"family": str(token.family_id)}, user_agent
            )
            await session.commit()
        raise AppError(401, "INVALID_TOKEN")
    if token.expires_at <= now:
        raise AppError(401, "INVALID_TOKEN")
    user = (
        await session.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    ).scalar_one_or_none()
    school_status = (await session.execute(select(School.status).where(School.id == school_id))).scalar()
    if user is None or user.status != UserStatus.ACTIVE or school_status not in OPEN_SCHOOL_STATUSES:
        await _revoke_family(session, token.family_id, now)
        await session.commit()
        raise AppError(401, "INVALID_TOKEN")
    token.revoked_at = now
    result = await _issue(session, base, user, user_agent, family_id=token.family_id)
    await session.commit()
    return result


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def logout(session: AsyncSession, base: DbContext, raw: str | None, user_agent: str | None) -> None:
    owner = await _token_owner(session, raw)
    if owner is None:
        return
    school_id, user_id, digest = owner
    await _context(session, base, school_id, user_id)
    family_id = (
        await session.execute(select(RefreshToken.family_id).where(RefreshToken.token_hash == digest))
    ).scalar_one()
    await _revoke_family(session, family_id, _now())
    await audit.record(session, "LOGOUT", "users", user_id, None, user_agent)
    await session.commit()


async def change_password(
    session: AsyncSession, user_id: uuid.UUID, current: str, new: str, keep_refresh: str | None, user_agent: str | None
) -> None:
    """Runs in the caller's school context (set by current_principal). Other sessions are signed out."""
    await enforce(f"pwchange:{user_id}", 5, 900)
    user = (await session.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one()
    valid, _ = await verify_password_async(current, user.password_hash)
    if not valid:
        raise AppError(401, "INVALID_CREDENTIALS")
    if not is_strong_password(new) or new == current:
        raise AppError(422, "WEAK_PASSWORD", [{"field": "new_password", "code": "invalid_value"}])
    user.password_hash, user.must_change_password = await hash_password_async(new), False
    keep_family = None
    if keep_refresh:
        keep_family = (
            await session.execute(
                select(RefreshToken.family_id).where(
                    RefreshToken.token_hash == sha256_hex(keep_refresh), RefreshToken.user_id == user_id
                )
            )
        ).scalar()
    stmt = update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
    if keep_family:
        stmt = stmt.where(RefreshToken.family_id != keep_family)
    await session.execute(stmt.values(revoked_at=_now()))
    await audit.record(session, "PASSWORD_CHANGE", "users", user_id, None, user_agent)
    await session.commit()


# ---------------------------------------------------------------- parent OTP login


async def _guardian_accounts(session: AsyncSession, phone: str) -> tuple[bytes, list[tuple[uuid.UUID, uuid.UUID]]]:
    phone_hash = get_cipher().blind_index(phone, sms.PHONE_FIELD)
    rows = (
        await session.execute(select(func.resolve_users_by_phone(phone_hash).table_valued("school_id", "user_id")))
    ).all()
    return phone_hash, [(r.school_id, r.user_id) for r in rows]


async def request_otp(session: AsyncSession, base: DbContext, phone: str, user_agent: str | None) -> list[dict]:
    """Create one code per matching guardian account and queue one SMS. Returns the send-task calls to dispatch
    after commit. The caller always answers the same way, whether or not the phone is known."""
    settings = get_settings()
    await enforce(f"otp:req:ip:{base.client_ip}", settings.otp_requests_per_window * 5, settings.otp_window_seconds)
    phone_hash, accounts = await _guardian_accounts(session, phone)
    await enforce(f"otp:req:{phone_hash.hex()}", settings.otp_requests_per_window, settings.otp_window_seconds)
    if not accounts:
        return []
    code = new_otp_code()
    expires = _now() + timedelta(seconds=settings.otp_ttl_seconds)
    first_school, first_user = accounts[0]
    language = "sw"
    for school_id, user_id in accounts:
        await _context(session, base, school_id)
        await session.execute(
            delete(OtpCode).where(
                OtpCode.user_id == user_id, OtpCode.purpose == OtpPurpose.LOGIN, OtpCode.consumed_at.is_(None)
            )
        )
        session.add(
            OtpCode(
                school_id=school_id,
                user_id=user_id,
                code_hash=otp_hash(code, user_id),
                purpose=OtpPurpose.LOGIN,
                expires_at=expires,
            )
        )
        await audit.record(session, "OTP_SENT", "users", user_id, None, user_agent, user_id)
        if (school_id, user_id) == (first_school, first_user):
            language = (await session.execute(select(User.preferred_language).where(User.id == user_id))).scalar()
    await _context(session, base, first_school)
    minutes = max(1, settings.otp_ttl_seconds // 60)
    text = OTP_TEXT.get(language, OTP_TEXT["sw"])
    message = await sms.queue_sms(
        session,
        school_id=first_school,
        phone=phone,
        to_user_id=first_user,
        language=language,
        body=text.format(code="******", minutes=minutes),
        template_key="otp_login",
        idempotency_key=f"otp:{uuid.uuid4()}",
        related_entity="otp_codes",
    )
    await session.commit()
    return [
        {"sms_id": str(message.id), "school_id": str(first_school), "text": text.format(code=code, minutes=minutes)}
    ]


async def verify_otp(
    session: AsyncSession, base: DbContext, phone: str, code: str, user_agent: str | None
) -> SignIn | SchoolSelection:
    settings = get_settings()
    phone_hash, accounts = await _guardian_accounts(session, phone)
    await enforce(f"otp:verify:{phone_hash.hex()}", settings.otp_max_attempts * 2, settings.otp_window_seconds)
    now = _now()
    matched: list[tuple[uuid.UUID, uuid.UUID]] = []
    for school_id, user_id in accounts:
        await _context(session, base, school_id)
        otp = (
            await session.execute(
                select(OtpCode)
                .where(
                    OtpCode.user_id == user_id,
                    OtpCode.purpose == OtpPurpose.LOGIN,
                    OtpCode.consumed_at.is_(None),
                    OtpCode.expires_at > now,
                )
                .order_by(OtpCode.created_at.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if otp is None or otp.attempts >= settings.otp_max_attempts:
            continue
        otp.attempts += 1
        if hmac.compare_digest(otp.code_hash, otp_hash(code, user_id)):
            otp.consumed_at = now
            matched.append((school_id, user_id))
        else:
            await audit.record(session, "OTP_FAILED", "users", user_id, {"attempt": otp.attempts}, user_agent, user_id)
    if not matched:
        await session.commit()
        raise AppError(401, "OTP_INVALID")
    if len(matched) == 1:
        return await _finish_parent_login(session, base, *matched[0], user_agent)
    choices = []
    for school_id, _ in matched:
        await _context(session, base, school_id)
        choices.append((school_id, (await session.execute(select(School.name).where(School.id == school_id))).scalar()))
    await session.commit()
    return SchoolSelection(choices=choices, selection_token=create_selection_token(matched))


async def select_school(
    session: AsyncSession, base: DbContext, selection_token: str, school_id: uuid.UUID, user_agent: str | None
) -> SignIn:
    try:
        claims = decode_token(selection_token, "select")
    except jwt.PyJWTError:
        raise AppError(401, "INVALID_TOKEN") from None
    for chosen_school, user_id in claims.get("choices", []):
        if uuid.UUID(chosen_school) == school_id:
            return await _finish_parent_login(session, base, school_id, uuid.UUID(user_id), user_agent)
    raise AppError(401, "INVALID_TOKEN")


async def _finish_parent_login(
    session: AsyncSession, base: DbContext, school_id: uuid.UUID, user_id: uuid.UUID, user_agent: str | None
) -> SignIn:
    await _context(session, base, school_id, user_id)
    user = (
        await session.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if user is None or user.status != UserStatus.ACTIVE:
        raise AppError(401, "INVALID_TOKEN")
    user.last_login_at = _now()
    result = await _issue(session, base, user, user_agent)
    await audit.record(session, "LOGIN", "users", user.id, {"method": "otp"}, user_agent)
    await session.commit()
    return result
