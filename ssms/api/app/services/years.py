"""The academic year a request looks at (FR-72)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AcademicYear


async def viewing_year(session: AsyncSession) -> uuid.UUID | None:
    """The year lists and totals show: the one chosen in the session selector (checked in api.deps), else the
    current year. Writes never use this; they keep working on the current year."""
    chosen = session.info.get("viewing_year")
    if chosen is not None:
        return chosen
    return (
        await session.execute(
            select(AcademicYear.id).where(AcademicYear.is_current.is_(True), AcademicYear.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
