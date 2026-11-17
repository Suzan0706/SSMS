"""Super-admin console (role ssms_platform, BYPASSRLS): sign-in with TOTP, school registry, onboarding."""

import logging
import re
import uuid
from datetime import UTC, date, datetime

import pyotp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import get_cipher
from app.core.errors import AppError, not_found
from app.core.ratelimit import enforce
from app.core.security import create_platform_token, hash_password_async, temporary_password, verify_password_async
from app.db.session import DbContext, set_context
from app.models import PlatformAdmin, Role, School, SchoolSettings, User, UserRole
from app.models.enums import SchoolStatus, UserStatus
from app.schemas.platform import SchoolCreateIn
from app.services import audit, geography, onboarding, sms

log = logging.getLogger(__name__)
MFA_FIELD = "platform_admins.mfa_secret"
TRANSITIONS = {
    SchoolStatus.ONBOARDING: {SchoolStatus.ACTIVE, SchoolStatus.CLOSED},
    SchoolStatus.ACTIVE: {SchoolStatus.SUSPENDED, SchoolStatus.CLOSED},
    SchoolStatus.SUSPENDED: {SchoolStatus.ACTIVE, SchoolStatus.CLOSED},
    SchoolStatus.CLOSED: set(),
}


async def login(
    session: AsyncSession, base: DbContext, email: str, password: str, totp: str | None
) -> tuple[str, PlatformAdmin]:
    settings = get_settings()
    await enforce(f"platform:ip:{base.client_ip}", 20, 900)
    await enforce(f"platform:email:{email.lower()}", 5, 900)
    admin = (
        await session.execute(
            select(PlatformAdmin).where(
                func.lower(PlatformAdmin.email) == email.lower(), PlatformAdmin.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    valid, new_hash = await verify_password_async(password, admin.password_hash if admin else None)
    if admin is None or not valid:
        log.warning("platform login failed ip=%s", base.client_ip)
        raise AppError(401, "INVALID_CREDENTIALS")
    if admin.mfa_secret_enc:
        if not totp:
            raise AppError(401, "MFA_REQUIRED")
        secret = get_cipher().decrypt(admin.mfa_secret_enc, MFA_FIELD)
        if not pyotp.TOTP(secret).verify(totp, valid_window=1):
            raise AppError(401, "INVALID_CREDENTIALS")
    elif settings.is_production:
        raise AppError(403, "MFA_SETUP_REQUIRED")
    if new_hash:
        admin.password_hash = new_hash
    admin.last_login_at = datetime.now(UTC)
    await session.commit()
    log.info("platform login admin=%s ip=%s", admin.id, base.client_ip)
    return create_platform_token(admin.id), admin


async def create_admin(session: AsyncSession, full_name: str, email: str, password: str) -> tuple[PlatformAdmin, str]:
    """Used by the operator CLI. Returns the admin and the TOTP provisioning URI (shown once)."""
    secret = pyotp.random_base32()
    admin = PlatformAdmin(
        full_name=full_name,
        email=email.lower(),
        password_hash=await hash_password_async(password),
        mfa_secret_enc=get_cipher().encrypt(secret, MFA_FIELD),
    )
    session.add(admin)
    await session.commit()
    return admin, pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="SSMS Console")


def _prefix_from_code(code: str) -> str:
    letters = re.sub(r"[^a-z]", "", code).upper()
    return (letters[:3] or "TZ").ljust(2, "X")


async def create_school(
    session: AsyncSession, base: DbContext, body: SchoolCreateIn, today: date | None = None
) -> tuple[School, User, str, dict[str, int], dict]:
    """School + settings + admin account (temporary password) + defaults, in one transaction.
    Returns (school, admin user, temporary password, default counts, SMS task call)."""
    if not await geography.exists(session, body.district_id):
        raise AppError(422, "INVALID_REFERENCE", [{"field": "district_id", "code": "invalid_value"}])
    cipher = get_cipher()
    school = School(
        code=body.code,
        name=body.name,
        registration_no=body.registration_no,
        ownership=body.ownership,
        district_id=body.district_id,
        status=SchoolStatus.ONBOARDING,
        created_by=base.platform_admin_id,
    )
    session.add(school)
    await session.flush()
    await set_context(
        session,
        DbContext(
            school_id=school.id,
            platform_admin_id=base.platform_admin_id,
            client_ip=base.client_ip,
            request_id=base.request_id,
        ),
    )
    password = temporary_password()
    a = body.admin
    admin = User(
        school_id=school.id,
        first_name=a.first_name.strip(),
        middle_name=a.middle_name,
        last_name=a.last_name.strip(),
        gender=a.gender,
        email=a.email,
        username=a.username,
        phone_enc=cipher.encrypt(a.phone, sms.PHONE_FIELD),
        phone_hash=cipher.blind_index(a.phone, sms.PHONE_FIELD),
        phone_last4=a.phone[-4:],
        password_hash=await hash_password_async(password),
        must_change_password=True,
        status=UserStatus.ACTIVE,
    )
    session.add(admin)
    await session.flush()
    role_id = (await session.execute(select(Role.id).where(Role.code == "school_admin"))).scalar_one()
    session.add(UserRole(school_id=school.id, user_id=admin.id, role_id=role_id, created_by=admin.id))
    session.add(
        SchoolSettings(
            school_id=school.id,
            admission_prefix=body.admission_prefix or _prefix_from_code(body.code),
            created_by=admin.id,
        )
    )
    await session.flush()
    counts = await onboarding.apply_defaults(session, school.id, admin.id, body.levels, (today or date.today()).year)

    sw, _ = onboarding.TEMPLATES["account_created"]
    fields = {"school": body.name[:40], "username": a.username}
    message = await sms.queue_sms(
        session,
        school_id=school.id,
        phone=a.phone,
        to_user_id=admin.id,
        language="sw",
        body=sw.format(password="********", **fields),
        template_key="account_created",
        idempotency_key=f"account:{admin.id}",
        related_entity="users",
        related_id=admin.id,
    )
    await session.commit()
    call = {"sms_id": str(message.id), "school_id": str(school.id), "text": sw.format(password=password, **fields)}
    return school, admin, password, counts, call


async def set_status(
    session: AsyncSession, base: DbContext, school_id: uuid.UUID, new_status: SchoolStatus, reason: str
) -> School:
    school = (
        await session.execute(
            select(School).where(School.id == school_id, School.deleted_at.is_(None)).with_for_update()
        )
    ).scalar_one_or_none()
    if school is None:
        raise not_found()
    if new_status != school.status and new_status not in TRANSITIONS[school.status]:
        raise AppError(
            409, "STATUS_TRANSITION", [{"from": school.status, "to": new_status}], old=school.status, new=new_status
        )
    old = school.status
    school.status = new_status
    await set_context(
        session,
        DbContext(
            school_id=school.id,
            platform_admin_id=base.platform_admin_id,
            client_ip=base.client_ip,
            request_id=base.request_id,
        ),
    )
    await audit.record(
        session, "UPDATE", "schools", school.id, {"status": new_status, "previous": old, "reason": reason}
    )
    await session.commit()
    return school
