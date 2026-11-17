"""Transport: buses, routes with ordered stops, and one assignment per student and term.

The database refuses a full bus (fn_capacity_guard -> 422 FULL bus_full) and a second active assignment for the same
term (409). The route's term fee is added to the student's invoice for the term when it already exists, otherwise
invoice generation picks it up.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError
from app.models import Bus, Route, RouteStop, SchoolSettings, Staff, Student, Term, TransportAssignment, User
from app.models.enums import BusStatus
from app.schemas.facilities import (
    AssignmentIn,
    AssignmentOut,
    BusOut,
    BusSeats,
    RouteIn,
    RouteOut,
    RouteUpdate,
    StopIn,
    StopOut,
)
from app.services import crud, facility_fees, invoices
from app.services.people import decrypt_phone, now


async def route_out(session: AsyncSession, route: Route) -> RouteOut:
    stops = await crud.list_live(session, RouteStop, RouteStop.seq, where=[RouteStop.route_id == route.id])
    return RouteOut(
        id=route.id,
        name=route.name,
        description=route.description,
        term_fee_tzs=route.term_fee_tzs,
        stops=[StopOut.model_validate(s) for s in stops],
    )


def _stops(principal: Principal, route_id: uuid.UUID, stops: list[StopIn]) -> list[RouteStop]:
    if len({s.seq for s in stops}) != len(stops):
        raise AppError(422, "VALIDATION_ERROR", [{"field": "stops", "code": "duplicate_in_file", "row": 0}])
    return [
        RouteStop(school_id=principal.school_id, route_id=route_id, created_by=principal.user_id, **s.model_dump())
        for s in stops
    ]


async def create_route(session: AsyncSession, principal: Principal, body: RouteIn) -> RouteOut:
    route = Route(
        school_id=principal.school_id,
        name=body.name,
        description=body.description,
        term_fee_tzs=body.term_fee_tzs,
        created_by=principal.user_id,
    )
    session.add(route)
    await session.flush()
    session.add_all(_stops(principal, route.id, body.stops))
    await session.commit()
    return await route_out(session, route)


async def update_route(session: AsyncSession, principal: Principal, route_id: uuid.UUID, body: RouteUpdate) -> RouteOut:
    route = await crud.get_live(session, Route, route_id, lock=True)
    for field in ("name", "description", "term_fee_tzs"):
        value = getattr(body, field)
        if value is not None:
            setattr(route, field, value)
    if body.stops is not None:
        in_use = (
            await session.execute(
                select(TransportAssignment.id)
                .join(RouteStop, RouteStop.id == TransportAssignment.stop_id)
                .where(RouteStop.route_id == route.id, TransportAssignment.ended_at.is_(None))
            )
        ).first()
        if in_use:
            raise AppError(409, "NOT_ALLOWED", [{"field": "stops", "code": "in_use"}])
        await session.execute(
            update(RouteStop)
            .where(RouteStop.route_id == route.id, RouteStop.deleted_at.is_(None))
            .values(deleted_at=now())
        )
        await session.flush()
        session.add_all(_stops(principal, route.id, body.stops))
    await session.commit()
    return await route_out(session, route)


async def _rows(session: AsyncSession, *where) -> list[AssignmentOut]:
    rows = (
        await session.execute(
            select(
                TransportAssignment,
                Student.admission_no,
                User.first_name,
                User.middle_name,
                User.last_name,
                Route.name,
                Bus.bus_no,
                RouteStop.name,
                RouteStop.pickup_time,
                RouteStop.route_id,
            )
            .join(Student, Student.id == TransportAssignment.student_id)
            .join(User, User.id == Student.user_id)
            .join(RouteStop, RouteStop.id == TransportAssignment.stop_id)
            .join(Route, Route.id == RouteStop.route_id)
            .join(Bus, Bus.id == TransportAssignment.bus_id)
            .where(*where)
            .order_by(Route.name, RouteStop.seq, User.last_name)
            .limit(500)
        )
    ).all()
    return [
        AssignmentOut(
            id=a.id,
            student_id=a.student_id,
            admission_no=admission,
            full_name=" ".join(p for p in (first, middle, last) if p),
            route_id=route_id,
            route_name=route,
            bus_id=a.bus_id,
            bus_no=bus,
            stop_name=stop,
            pickup_time=pickup,
            term_id=a.term_id,
            ended_at=a.ended_at,
        )
        for a, admission, first, middle, last, route, bus, stop, pickup, route_id in rows
    ]


async def assignments(
    session: AsyncSession,
    term_id: uuid.UUID,
    bus_id: uuid.UUID | None = None,
    route_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    active: bool = True,
) -> list[AssignmentOut]:
    where = [TransportAssignment.term_id == term_id]
    if bus_id:
        where.append(TransportAssignment.bus_id == bus_id)
    if route_id:
        where.append(RouteStop.route_id == route_id)
    if student_id:
        where.append(TransportAssignment.student_id == student_id)
    if active:
        where.append(TransportAssignment.ended_at.is_(None))
    return await _rows(session, *where)


async def assign(session: AsyncSession, principal: Principal, body: AssignmentIn) -> AssignmentOut:
    await crud.get_live(session, Student, body.student_id)
    term = await crud.get_live(session, Term, body.term_id)
    bus = await crud.get_live(session, Bus, body.bus_id)
    await crud.get_live(session, RouteStop, body.stop_id)
    if bus.status != BusStatus.ACTIVE:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "bus_id", "code": "invalid_value"}])
    item = TransportAssignment(school_id=principal.school_id, created_by=principal.user_id, **body.model_dump())
    session.add(item)
    await crud.flush_checked(session, "bus_id", "bus_full")
    lang = (await session.execute(select(SchoolSettings.default_language))).scalar() or "sw"
    charges = await facility_fees.transport(session, body.student_id, term, lang)
    invoice_no = await invoices.add_charges(
        session, principal.school_id, body.student_id, body.term_id, charges, principal.user_id
    )
    await session.commit()
    out = (await _rows(session, TransportAssignment.id == item.id))[0]
    out.invoice_no = invoice_no
    return out


async def end(session: AsyncSession, assignment_id: uuid.UUID) -> AssignmentOut:
    item = await crud.get_live(session, TransportAssignment, assignment_id, lock=True)
    if item.ended_at is None:
        item.ended_at = now()
        await session.commit()
    return (await _rows(session, TransportAssignment.id == item.id))[0]


async def bus_seats(session: AsyncSession, term_id: uuid.UUID) -> list[BusSeats]:
    """Every bus with its seats taken for the term."""
    used = dict(
        (
            await session.execute(
                select(TransportAssignment.bus_id, func.count())
                .where(TransportAssignment.term_id == term_id, TransportAssignment.ended_at.is_(None))
                .group_by(TransportAssignment.bus_id)
            )
        ).all()
    )
    buses = await crud.list_live(session, Bus, Bus.bus_no)
    drivers = {
        staff_id: user
        for staff_id, user in (
            await session.execute(
                select(Staff.id, User)
                .join(User, User.id == Staff.user_id)
                .where(Staff.id.in_([b.driver_staff_id for b in buses if b.driver_staff_id]))
            )
        ).all()
    }
    out = []
    for b in buses:
        driver = drivers.get(b.driver_staff_id)
        out.append(
            BusSeats(
                **BusOut.model_validate(b).model_dump(),
                used=used.get(b.id, 0),
                free=max(b.capacity - used.get(b.id, 0), 0),
                driver_name=f"{driver.first_name} {driver.last_name}" if driver else None,
                driver_phone=decrypt_phone(driver) if driver else None,
            )
        )
    return out
