"""Building blocks shared by users, staff, students and guardians (all in the caller's school context)."""

import logging
import re
import uuid
from datetime import UTC, datetime

from cryptography.exceptions import InvalidTag
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.crypto import CryptoNotConfigured, get_cipher
from app.core.errors import AppError
from app.core.phone import mask_phone
from app.core.security import temporary_password
from app.models import MessageTemplate, RefreshToken, Role, School, User, UserRole
from app.models.enums import UserStatus
from app.services import audit, sms
from app.services.onboarding import TEMPLATES

log = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now(UTC)


def display_phone(phone_enc: bytes | None, phone_last4: str | None, reveal: bool) -> str | None:
    """Full number for callers allowed to contact the person, otherwise ****1234."""
    if not phone_last4:
        return None
    if reveal:
        try:
            return get_cipher().decrypt(phone_enc, sms.PHONE_FIELD)
        except (ValueError, InvalidTag, CryptoNotConfigured):  # unreadable (old key, bad data): never fail a page
            log.warning("phone could not be decrypted; returned masked")
    return mask_phone(phone_last4)


def decrypt_phone(user: User) -> str | None:
    """The phone in clear, or None when there is none or it cannot be decrypted."""
    if not user.phone_enc:
        return None
    try:
        return get_cipher().decrypt(user.phone_enc, sms.PHONE_FIELD)
    except (ValueError, InvalidTag, CryptoNotConfigured):
        log.warning("phone could not be decrypted")
        return None


def set_phone(user: User, phone: str | None) -> None:
    cipher = get_cipher()
    user.phone_enc = cipher.encrypt(phone, sms.PHONE_FIELD) if phone else None
    user.phone_hash = cipher.blind_index(phone, sms.PHONE_FIELD) if phone else None
    user.phone_last4 = phone[-4:] if phone else None


def new_user(
    principal: Principal,
    *,
    first_name: str,
    last_name: str,
    gender: str,
    middle_name: str | None = None,
    date_of_birth=None,
    phone: str | None = None,
    email: str | None = None,
    username: str | None = None,
    password_hash: str | None = None,  # a temporary password, hashed by the caller off the event loop
    status: UserStatus = UserStatus.ACTIVE,
    language: str = "sw",
) -> User:
    user = User(
        school_id=principal.school_id,
        first_name=first_name,
        middle_name=middle_name,
        last_name=last_name,
        gender=gender,
        date_of_birth=date_of_birth,
        email=email,
        username=username,
        password_hash=password_hash,
        must_change_password=bool(password_hash),
        preferred_language=language,
        status=status,
        created_by=principal.user_id,
    )
    set_phone(user, phone)
    return user


async def find_user_by_phone(session: AsyncSession, phone: str) -> User | None:
    phone_hash = get_cipher().blind_index(phone, sms.PHONE_FIELD)
    return (
        await session.execute(select(User).where(User.phone_hash == phone_hash, User.deleted_at.is_(None)))
    ).scalar_one_or_none()


async def unique_username(session: AsyncSession, first_name: str, last_name: str) -> str:
    """e.g. Daudi Mwita -> d.mwita, then d.mwita2, d.mwita3 ..."""
    base = re.sub(r"[^a-z0-9.]", "", f"{first_name[:1]}.{last_name}".lower())[:40] or "user"
    taken = set(
        (
            await session.execute(
                select(func.lower(User.username)).where(
                    func.lower(User.username).like(f"{base}%"), User.deleted_at.is_(None)
                )
            )
        ).scalars()
    )
    if base not in taken:
        return base
    return next(f"{base}{n}" for n in range(2, 10_000) if f"{base}{n}" not in taken)


async def role_ids(session: AsyncSession, codes: list[str]) -> dict[str, uuid.UUID]:
    found = dict((await session.execute(select(Role.code, Role.id).where(Role.code.in_(codes)))).all())
    missing = [c for c in codes if c not in found]
    if missing:
        raise AppError(
            422, "INVALID_REFERENCE", [{"field": "roles", "code": "invalid_value", "value": c} for c in missing]
        )
    return found


async def grant_role(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID, role_code: str, *, if_missing: bool = False
) -> None:
    role_id = (await role_ids(session, [role_code]))[role_code]
    exists = (
        await session.execute(
            select(UserRole.id).where(
                UserRole.user_id == user_id, UserRole.role_id == role_id, UserRole.revoked_at.is_(None)
            )
        )
    ).scalar()
    if exists:
        if if_missing:
            return
        raise AppError(409, "DUPLICATE", [{"field": "role_code", "code": "duplicate_in_school"}])
    session.add(UserRole(school_id=principal.school_id, user_id=user_id, role_id=role_id, created_by=principal.user_id))
    await audit.record(session, "ROLE_GRANT", "users", user_id, {"role": role_code})


async def revoke_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now())
    )


async def account_sms(session: AsyncSession, principal: Principal, user: User, phone: str, password: str) -> dict:
    """Queue the 'account created' SMS (password masked in the database) and return the send-task call."""
    language = user.preferred_language
    template = (
        await session.execute(
            select(MessageTemplate.body).where(
                MessageTemplate.key == "account_created",
                MessageTemplate.language == language,
                MessageTemplate.is_active.is_(True),
                MessageTemplate.deleted_at.is_(None),
            )
        )
    ).scalar()
    template = template or TEMPLATES["account_created"][0 if language == "sw" else 1]
    school = (await session.execute(select(School.name).where(School.id == principal.school_id))).scalar()
    fields = {"school": school[:40], "username": user.username}
    message = await sms.queue_sms(
        session,
        school_id=principal.school_id,
        phone=phone,
        to_user_id=user.id,
        language=language,
        body=template.format(password="********", **fields),
        template_key="account_created",
        idempotency_key=f"account:{user.id}:{uuid.uuid4().hex[:12]}",
        related_entity="users",
        related_id=user.id,
    )
    return {
        "sms_id": str(message.id),
        "school_id": str(principal.school_id),
        "text": template.format(password=password, **fields),
    }


def new_temporary_password() -> str:
    return temporary_password()


async def flush_or_rule(session: AsyncSession) -> None:
    """Flush, turning the capacity trigger's check_violation into 409 STREAM_FULL."""
    try:
        await session.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23514" and "is full" in str(exc.orig):
            raise AppError(409, "STREAM_FULL") from None
        raise
