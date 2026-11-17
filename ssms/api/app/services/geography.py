"""Tanzania's regions and districts: national reference data, shared by every school (no school_id, no RLS)."""

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import District, Region
from app.schemas.platform import DistrictOut, RegionOut


async def names(session: AsyncSession, district_id: uuid.UUID) -> tuple[str, str]:
    """(region name, district name)."""
    row = (
        await session.execute(
            select(Region.name, District.name)
            .join(District, District.region_id == Region.id)
            .where(District.id == district_id)
        )
    ).one()
    return row[0], row[1]


async def exists(session: AsyncSession, district_id: uuid.UUID) -> bool:
    return (await session.execute(select(District.id).where(District.id == district_id))).first() is not None


async def regions(session: AsyncSession) -> list[RegionOut]:
    grouped: dict[uuid.UUID, list[DistrictOut]] = defaultdict(list)
    for district_id, region_id, name in await session.execute(
        select(District.id, District.region_id, District.name).order_by(District.name)
    ):
        grouped[region_id].append(DistrictOut(id=district_id, name=name))
    rows = await session.execute(select(Region.id, Region.name).order_by(Region.name))
    return [RegionOut(id=i, name=name, districts=grouped[i]) for i, name in rows.all()]
