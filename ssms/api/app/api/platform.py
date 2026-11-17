"""/platform: super-admin console (separate token audience, BYPASSRLS database role ssms_platform)."""

import uuid
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import bearer, client_ip
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.pagination import Cursor, Limit, Page, paginate
from app.core.security import PLATFORM_AUDIENCE, decode_token
from app.db.session import DbContext, get_platform_session, set_context
from app.models import District, PlatformAdmin, Region, School, SmsCreditTransaction
from app.models.enums import CreditKind, SchoolStatus
from app.schemas.communication import CreditOut, TopUpIn
from app.schemas.platform import (
    PlatformAdminOut,
    PlatformLoginIn,
    PlatformTokenOut,
    RegionOut,
    SchoolCreatedOut,
    SchoolCreateIn,
    SchoolOut,
    SchoolStatusIn,
)
from app.services import communication, geography, platform
from app.tasks.dispatch import get_dispatcher

router = APIRouter(prefix="/platform", tags=["platform"])


def _context(request: Request, admin_id: uuid.UUID | None = None) -> DbContext:
    return DbContext(
        platform_admin_id=admin_id, client_ip=client_ip(request), request_id=getattr(request.state, "request_id", None)
    )


async def current_platform_admin(
    request: Request,
    session: AsyncSession = Depends(get_platform_session),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> DbContext:
    if credentials is None:
        raise AppError(401, "NOT_AUTHENTICATED", headers={"WWW-Authenticate": "Bearer"})
    try:
        admin_id = uuid.UUID(decode_token(credentials.credentials, "platform", PLATFORM_AUDIENCE)["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise AppError(401, "INVALID_TOKEN", headers={"WWW-Authenticate": "Bearer"}) from None
    active = (await session.execute(select(PlatformAdmin.is_active).where(PlatformAdmin.id == admin_id))).scalar()
    if not active:
        raise AppError(401, "INVALID_TOKEN")
    ctx = _context(request, admin_id)
    await set_context(session, ctx)
    return ctx


@router.post("/auth/login", response_model=PlatformTokenOut, summary="Console sign-in (password + TOTP)")
async def login(body: PlatformLoginIn, request: Request, session: AsyncSession = Depends(get_platform_session)):
    token, admin = await platform.login(session, _context(request), body.email, body.password, body.totp)
    return PlatformTokenOut(
        access_token=token,
        expires_in=get_settings().access_token_minutes * 60,
        admin=PlatformAdminOut.model_validate(admin),
    )


async def _school_out(session: AsyncSession, school: School) -> SchoolOut:
    region, district = await geography.names(session, school.district_id)
    return SchoolOut(
        id=school.id,
        code=school.code,
        name=school.name,
        registration_no=school.registration_no,
        ownership=school.ownership,
        region=region,
        district=district,
        status=school.status,
        created_at=school.created_at,
    )


@router.get("/regions", response_model=list[RegionOut], summary="Regions of Tanzania, each with its districts")
async def list_regions(
    _: DbContext = Depends(current_platform_admin), session: AsyncSession = Depends(get_platform_session)
):
    return await geography.regions(session)


@router.get("/schools", response_model=Page[SchoolOut], summary="Registered schools")
async def list_schools(
    status_filter: Annotated[SchoolStatus | None, Query(alias="status")] = None,
    limit: Limit = 50,
    cursor: Cursor = None,
    _: DbContext = Depends(current_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
):
    stmt = (
        select(
            School.id,
            School.code,
            School.name,
            School.registration_no,
            School.ownership,
            Region.name.label("region"),
            District.name.label("district"),
            School.status,
            School.created_at,
        )
        .join(District, District.id == School.district_id)
        .join(Region, Region.id == District.region_id)
        .where(School.deleted_at.is_(None))
    )
    if status_filter:
        stmt = stmt.where(School.status == status_filter)
    rows, next_cursor = await paginate(session, stmt, [School.id], limit, cursor)
    return Page[SchoolOut](items=[SchoolOut.model_validate(r) for r in rows], next_cursor=next_cursor)


@router.post(
    "/schools",
    response_model=SchoolCreatedOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "DUPLICATE code or registration number"}},
    summary="Register a school: settings, admin account and onboarding defaults in one transaction",
)
async def create_school(
    body: SchoolCreateIn,
    ctx: DbContext = Depends(current_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
):
    school, admin, password, counts, sms_call = await platform.create_school(session, ctx, body)
    get_dispatcher().send("sms.send", **sms_call)
    return SchoolCreatedOut(
        school=await _school_out(session, school),
        admin_user_id=admin.id,
        admin_username=admin.username,
        temporary_password=password,
        defaults=counts,
    )


@router.patch(
    "/schools/{school_id}",
    response_model=SchoolOut,
    responses={404: {"description": "NOT_FOUND"}, 409: {"description": "STATUS_TRANSITION"}},
    summary="Activate, suspend or close a school (audited with the reason)",
)
async def update_school(
    school_id: uuid.UUID,
    body: SchoolStatusIn,
    ctx: DbContext = Depends(current_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
):
    school = await platform.set_status(session, ctx, school_id, body.status, body.reason)
    return await _school_out(session, school)


@router.post(
    "/schools/{school_id}/sms-credit",
    response_model=CreditOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add SMS credit after the school paid for a bundle (TOPUP row, audited by the console context)",
)
async def top_up(
    school_id: uuid.UUID,
    body: TopUpIn,
    ctx: DbContext = Depends(current_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
):
    if (await session.execute(select(School.id).where(School.id == school_id))).first() is None:
        raise AppError(404, "NOT_FOUND")
    await set_context(session, DbContext(**{**vars(ctx), "school_id": school_id}))
    session.add(SmsCreditTransaction(school_id=school_id, kind=CreditKind.TOPUP, credits=body.credits, note=body.note))
    await session.commit()
    return await communication.credit(session, school_id)


@router.get("/dashboard", summary="Schools by status and, per school, active students, staff and SMS credit (FR-75)")
async def dashboard(
    _: DbContext = Depends(current_platform_admin),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    """Counts only: no names or other personal data leave the schools (the console role bypasses RLS)."""
    rows = (
        await session.execute(
            text(
                """
                SELECT s.id, s.code, s.name, s.status,
                       (SELECT count(*) FROM students st WHERE st.school_id = s.id AND st.status = 'ACTIVE'
                          AND st.deleted_at IS NULL) AS students,
                       (SELECT count(*) FROM staff f WHERE f.school_id = s.id AND f.status = 'ACTIVE'
                          AND f.deleted_at IS NULL) AS staff,
                       (SELECT coalesce(sum(b.credits_left), 0) FROM v_sms_credit_balance b WHERE b.school_id = s.id)
                          AS sms_credit
                FROM schools s WHERE s.deleted_at IS NULL ORDER BY s.name
                """
            )
        )
    ).all()
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1
    return {
        "schools": len(rows),
        "by_status": by_status,
        "students": sum(r.students for r in rows),
        "staff": sum(r.staff for r in rows),
        "per_school": [
            {
                "id": r.id,
                "code": r.code,
                "name": r.name,
                "status": r.status,
                "students": r.students,
                "staff": r.staff,
                "sms_credit": int(r.sms_credit),
            }
            for r in rows
        ],
    }
