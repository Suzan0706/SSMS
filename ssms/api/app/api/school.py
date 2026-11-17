"""/school: profile and settings of the caller's school."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.db.session import get_session
from app.models import School, SchoolSettings
from app.schemas.people import SchoolOut, SchoolSettingsIn, SchoolSettingsOut
from app.services import geography

router = APIRouter(tags=["school"])


async def _school(session: AsyncSession, principal: Principal, lock: bool = False) -> tuple[School, SchoolSettings]:
    school = (await session.execute(select(School).where(School.id == principal.school_id))).scalar_one()
    stmt = select(SchoolSettings).where(SchoolSettings.school_id == principal.school_id)
    settings = (await session.execute(stmt.with_for_update() if lock else stmt)).scalar_one()
    return school, settings


async def _out(session: AsyncSession, school: School, settings: SchoolSettings) -> SchoolOut:
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
        settings=SchoolSettingsOut.model_validate(settings),
    )


@router.get("/school", response_model=SchoolOut, summary="This school's profile and settings")
async def get_school(principal: Principal = Depends(active_principal), session: AsyncSession = Depends(get_session)):
    return await _out(session, *await _school(session, principal))


@router.patch("/school", response_model=SchoolOut, summary="Update settings (only the fields sent are changed)")
async def update_school(
    body: SchoolSettingsIn,
    principal: Principal = require_permission("settings.update"),
    session: AsyncSession = Depends(get_session),
):
    school, settings = await _school(session, principal, lock=True)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)
    await session.commit()
    return await _out(session, school, settings)
