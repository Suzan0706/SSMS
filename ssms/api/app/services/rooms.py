"""Rooms and what is in them. Equipment names are shared within a school, so a search finds every room that has it."""

import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.models import EquipmentItem, Room, RoomEquipment
from app.schemas.academics import EquipmentItemOut, RoomEquipmentIn, RoomEquipmentOut, RoomIn, RoomOut, RoomUpdate
from app.services import crud
from app.services.people import now


async def _out(session: AsyncSession, rooms: list[Room]) -> list[RoomOut]:
    rows = await session.execute(
        select(RoomEquipment.room_id, EquipmentItem.id, EquipmentItem.name, RoomEquipment.quantity)
        .join(EquipmentItem, EquipmentItem.id == RoomEquipment.equipment_id)
        .where(RoomEquipment.room_id.in_([r.id for r in rooms]), RoomEquipment.deleted_at.is_(None))
        .order_by(EquipmentItem.name)
    )
    by_room: dict[uuid.UUID, list[RoomEquipmentOut]] = defaultdict(list)
    for room_id, equipment_id, name, quantity in rows.all():
        by_room[room_id].append(RoomEquipmentOut(equipment_id=equipment_id, name=name, quantity=quantity))
    return [RoomOut.model_validate(r).model_copy(update={"equipment": by_room[r.id]}) for r in rooms]


async def list_rooms(session: AsyncSession, equipment_ids: list[uuid.UUID]) -> list[RoomOut]:
    """With equipment_ids, only rooms that have all of them."""
    where = [
        select(RoomEquipment.id)
        .where(
            RoomEquipment.room_id == Room.id,
            RoomEquipment.equipment_id == equipment_id,
            RoomEquipment.deleted_at.is_(None),
        )
        .exists()
        for equipment_id in equipment_ids
    ]
    return await _out(session, await crud.list_live(session, Room, Room.code, where=where))


async def _item(session: AsyncSession, principal: Principal, name: str) -> EquipmentItem:
    """The school's item of that name, whatever its case; created on first use."""
    item = (
        await session.execute(
            select(EquipmentItem).where(
                func.lower(EquipmentItem.name) == name.lower(), EquipmentItem.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if item is None:
        item = EquipmentItem(
            school_id=principal.school_id, name=name[0].upper() + name[1:], created_by=principal.user_id
        )
        session.add(item)
        await session.flush()
    return item


async def _replace(
    session: AsyncSession, principal: Principal, room_id: uuid.UUID, lines: list[RoomEquipmentIn]
) -> None:
    current = {
        row.equipment_id: row
        for row in (
            await session.execute(
                select(RoomEquipment).where(RoomEquipment.room_id == room_id, RoomEquipment.deleted_at.is_(None))
            )
        ).scalars()
    }
    wanted = {(await _item(session, principal, line.name)).id: line.quantity for line in lines}
    for equipment_id, row in current.items():
        if equipment_id not in wanted:
            row.deleted_at = now()
    for equipment_id, quantity in wanted.items():
        if equipment_id in current:
            current[equipment_id].quantity = quantity
        else:
            session.add(
                RoomEquipment(
                    school_id=principal.school_id,
                    room_id=room_id,
                    equipment_id=equipment_id,
                    quantity=quantity,
                    created_by=principal.user_id,
                )
            )
    await session.flush()


async def create_room(session: AsyncSession, principal: Principal, body: RoomIn) -> RoomOut:
    room = await crud.create(session, principal, Room, body.model_dump(exclude={"equipment"}), commit=False)
    await _replace(session, principal, room.id, body.equipment)
    [out] = await _out(session, [room])
    await session.commit()
    return out


async def update_room(session: AsyncSession, principal: Principal, room_id: uuid.UUID, body: RoomUpdate) -> RoomOut:
    data = body.model_dump(exclude_unset=True, exclude={"equipment"})
    room = await crud.update(session, Room, room_id, data, commit=False)
    if body.equipment is not None:
        await _replace(session, principal, room.id, body.equipment)
    [out] = await _out(session, [room])
    await session.commit()
    return out


async def list_items(session: AsyncSession) -> list[EquipmentItemOut]:
    rooms = func.count(RoomEquipment.id)
    rows = await session.execute(
        select(EquipmentItem.id, EquipmentItem.name, rooms)
        .outerjoin(RoomEquipment, (RoomEquipment.equipment_id == EquipmentItem.id) & RoomEquipment.deleted_at.is_(None))
        .where(EquipmentItem.deleted_at.is_(None))
        .group_by(EquipmentItem.id, EquipmentItem.name)
        .order_by(EquipmentItem.name)
        .limit(200)
    )
    return [EquipmentItemOut(id=i, name=name, rooms=count) for i, name, count in rows.all()]
