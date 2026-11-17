"""Request dependencies: who is calling, for which school, with which permissions.

The school always comes from the verified JWT claim `sch`, never from the URL or the body. The dependency sets
the per-transaction context (SET LOCAL app.school_id / app.user_id), so PostgreSQL RLS applies to every query
of the request. Permissions are loaded per request, so a revoked role takes effect immediately.
"""

import uuid
from dataclasses import dataclass, field

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, forbidden
from app.core.security import decode_token
from app.db.session import DbContext, get_session, set_context
from app.models import AcademicYear, Permission, Role, RolePermission, School, User, UserRole
from app.models.enums import SchoolStatus, UserStatus

bearer = HTTPBearer(auto_error=False)
OPEN_SCHOOL_STATUSES = (SchoolStatus.ONBOARDING, SchoolStatus.ACTIVE)


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    school_id: uuid.UUID
    language: str
    must_change_password: bool
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)

    def has(self, permission: str) -> bool:
        return permission in self.permissions


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def request_context(
    request: Request, school_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None
) -> DbContext:
    return DbContext(
        school_id=school_id,
        user_id=user_id,
        client_ip=client_ip(request),
        request_id=getattr(request.state, "request_id", None),
    )


async def load_access(session: AsyncSession, user_id: uuid.UUID) -> tuple[frozenset[str], frozenset[str]]:
    """(role codes, permission codes) of a user in the current school context."""
    rows = (
        await session.execute(
            select(Role.code, Permission.code)
            .select_from(UserRole)
            .join(Role, Role.id == UserRole.role_id)
            .outerjoin(RolePermission, RolePermission.role_id == Role.id)
            .outerjoin(Permission, Permission.id == RolePermission.permission_id)
            .where(UserRole.user_id == user_id, UserRole.revoked_at.is_(None))
        )
    ).all()
    return frozenset(r for r, _ in rows), frozenset(p for _, p in rows if p)


async def current_principal(
    request: Request,
    session: AsyncSession = Depends(get_session),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    if credentials is None:
        raise AppError(401, "NOT_AUTHENTICATED", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_token(credentials.credentials, "access")
        school_id, user_id = uuid.UUID(claims["sch"]), uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise AppError(401, "INVALID_TOKEN", headers={"WWW-Authenticate": "Bearer"}) from None
    await set_context(session, request_context(request, school_id, user_id))
    row = (
        await session.execute(
            select(
                User.status, User.preferred_language, User.must_change_password, School.status.label("school_status")
            )
            .join(School, School.id == User.school_id)
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
    ).one_or_none()
    if row is None or row.status != UserStatus.ACTIVE or row.school_status not in OPEN_SCHOOL_STATUSES:
        raise AppError(401, "INVALID_TOKEN", headers={"WWW-Authenticate": "Bearer"})
    roles, permissions = await load_access(session, user_id)
    if not request.state.lang_explicit:
        request.state.lang = row.preferred_language
    principal = Principal(
        user_id=user_id,
        school_id=school_id,
        language=row.preferred_language,
        must_change_password=row.must_change_password,
        roles=roles,
        permissions=permissions,
    )
    request.state.principal = principal
    await apply_viewing_year(request, session)
    return principal


YEAR_HEADER = "X-Academic-Year"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_ALWAYS_WRITABLE = ("/api/v1/auth/", "/api/v1/notifications")  # sign-in, password, inbox: not school records


async def apply_viewing_year(request: Request, session: AsyncSession) -> None:
    """The year chosen in the session selector (FR-72), sent as X-Academic-Year.

    Lists and totals read it with services.academics.viewing_year(). The year must belong to the caller's school (RLS
    hides other schools' years, so they are simply not found). While a past or future year is shown, nothing can be
    changed: every write is refused, so viewing history can never alter it.
    """
    raw = request.headers.get(YEAR_HEADER)
    if not raw:
        return
    try:
        year_id = uuid.UUID(raw)
    except ValueError:
        raise AppError(422, "VALIDATION_ERROR", [{"field": YEAR_HEADER, "code": "invalid_value"}]) from None
    is_current = (
        await session.execute(
            select(AcademicYear.is_current).where(AcademicYear.id == year_id, AcademicYear.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if is_current is None:
        raise AppError(422, "VALIDATION_ERROR", [{"field": YEAR_HEADER, "code": "not_found"}])
    session.info["viewing_year"] = year_id
    if not is_current and request.method not in _SAFE_METHODS and not request.url.path.startswith(_ALWAYS_WRITABLE):
        raise AppError(409, "YEAR_READ_ONLY")


async def active_principal(principal: Principal = Depends(current_principal)) -> Principal:
    """Any signed-in user who does not still have to replace a temporary password."""
    if principal.must_change_password:
        raise AppError(403, "PASSWORD_CHANGE_REQUIRED")
    return principal


def require_permission(*codes: str):
    """Allow the request when the caller holds at least one of the permission codes."""

    async def dependency(principal: Principal = Depends(active_principal)) -> Principal:
        if not any(principal.has(code) for code in codes):
            raise forbidden()
        return principal

    dependency.__name__ = "require_" + "_or_".join(c.replace(".", "_") for c in codes)
    return Depends(dependency)
