"""Venues and bookings. The database refuses overlapping bookings of one venue (EXCLUDE ex_ve_overlap -> 409
VENUE_CLASH) and more seats than the venue holds (fn_capacity_guard -> 422 FULL too_many_seats)."""

import uuid
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError
from app.models import Venue, VenueEvent
from app.schemas.facilities import EventIn, EventUpdate
from app.services import crud


async def _save(session: AsyncSession) -> None:
    try:
        await crud.flush_checked(session, "seats_occupied", "too_many_seats")
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23P01":
            raise AppError(409, "VENUE_CLASH", [{"field": "time_start", "code": "VENUE_CLASH"}]) from None
        raise
    await session.commit()


async def book(session: AsyncSession, principal: Principal, body: EventIn) -> VenueEvent:
    await crud.get_live(session, Venue, body.venue_id)
    event = VenueEvent(
        school_id=principal.school_id, organiser_id=principal.user_id, created_by=principal.user_id, **body.model_dump()
    )
    session.add(event)
    await _save(session)
    return event


async def change(session: AsyncSession, event_id: uuid.UUID, body: EventUpdate) -> VenueEvent:
    event = await crud.get_live(session, VenueEvent, event_id, lock=True)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(event, field, value)
    if event.time_end <= event.time_start:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "time_end", "code": "invalid_value"}])
    await _save(session)
    return event


async def calendar(
    session: AsyncSession, venue_id: uuid.UUID | None, date_from: date, date_to: date
) -> list[VenueEvent]:
    where = [VenueEvent.event_date.between(date_from, date_to)]
    if venue_id:
        where.append(VenueEvent.venue_id == venue_id)
    return await crud.list_live(session, VenueEvent, VenueEvent.event_date, VenueEvent.time_start, where=where)
