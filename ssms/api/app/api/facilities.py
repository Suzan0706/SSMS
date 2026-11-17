"""/hostels, /hostel-rooms, /accommodation-requests, /buses, /routes, /transport-assignments, /venues, /venue-events."""

import uuid
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.db.session import get_session
from app.models import Bus, Hostel, HostelRoom, Route, Venue, VenueEvent
from app.schemas.facilities import (
    AccommodationIn,
    AccommodationOut,
    AssignmentIn,
    AssignmentOut,
    BusIn,
    BusOut,
    BusSeats,
    BusUpdate,
    DecisionIn,
    EventIn,
    EventOut,
    EventUpdate,
    HostelIn,
    HostelOut,
    HostelUpdate,
    OccupancyOut,
    RoomIn,
    RoomOut,
    RoomUpdate,
    RouteIn,
    RouteOut,
    RouteUpdate,
    VenueIn,
    VenueOut,
)
from app.services import crud, hostel, transport, venues
from app.services.people import now

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
Signed = Annotated[Principal, Depends(active_principal)]
HostelOffice = Annotated[Principal, require_permission("hostel.manage")]
TransportOffice = Annotated[Principal, require_permission("transport.manage")]
VenueOffice = Annotated[Principal, require_permission("venues.manage")]
RequestStatusQ = Literal["PENDING", "APPROVED", "REJECTED", "CANCELLED"]


# ---------------------------------------------------------------- hostels


@router.get("/hostels", response_model=list[HostelOut], tags=["hostel"])
async def list_hostels(_: Signed, session: Session):
    return [await hostel.hostel_out(session, h) for h in await crud.list_live(session, Hostel, Hostel.name)]


@router.post("/hostels", response_model=HostelOut, status_code=201, tags=["hostel"])
async def create_hostel(body: HostelIn, principal: HostelOffice, session: Session):
    return await hostel.hostel_out(session, await crud.create(session, principal, Hostel, body.model_dump()))


@router.patch("/hostels/{hostel_id}", response_model=HostelOut, tags=["hostel"])
async def update_hostel(hostel_id: uuid.UUID, body: HostelUpdate, _: HostelOffice, session: Session):
    item = await crud.update(session, Hostel, hostel_id, body.model_dump(exclude_unset=True))
    return await hostel.hostel_out(session, item)


@router.get("/hostel-rooms", response_model=list[RoomOut], tags=["hostel"])
async def list_rooms(hostel_id: uuid.UUID, _: HostelOffice, session: Session):
    return await crud.list_live(session, HostelRoom, HostelRoom.name, where=[HostelRoom.hostel_id == hostel_id])


@router.post("/hostel-rooms", response_model=RoomOut, status_code=201, tags=["hostel"])
async def create_room(body: RoomIn, principal: HostelOffice, session: Session):
    await crud.get_live(session, Hostel, body.hostel_id)
    item = await crud.create(session, principal, HostelRoom, body.model_dump(), commit=False)
    await crud.flush_checked(session, "name", "room_full")
    await session.commit()
    return item


@router.patch("/hostel-rooms/{room_id}", response_model=RoomOut, tags=["hostel"])
async def update_room(room_id: uuid.UUID, body: RoomUpdate, _: HostelOffice, session: Session):
    return await crud.update(session, HostelRoom, room_id, body.model_dump(exclude_unset=True))


@router.get("/hostels/{hostel_id}/occupancy", response_model=OccupancyOut, tags=["hostel"])
async def occupancy(hostel_id: uuid.UUID, term_id: uuid.UUID, _: HostelOffice, session: Session):
    return await hostel.occupancy(session, hostel_id, term_id)


@router.post(
    "/accommodation-requests",
    response_model=AccommodationOut,
    status_code=201,
    responses={409: {"description": "an open request already exists for the term"}},
    summary="A student (for themselves), a guardian (for their child) or the hostel office asks for a bed",
)
async def request_bed(body: AccommodationIn, principal: Signed, session: Session):
    return await hostel.request(session, principal, body)


@router.get("/accommodation-requests", response_model=list[AccommodationOut], tags=["hostel"])
async def list_requests(
    principal: Signed,
    session: Session,
    term_id: uuid.UUID | None = None,
    status: Annotated[RequestStatusQ | None, Query()] = None,
):
    return await hostel.requests(session, principal, term_id, status)


@router.post(
    "/accommodation-requests/{request_id}/decide",
    response_model=AccommodationOut,
    tags=["hostel"],
    responses={422: {"description": "FULL room_full, or wrong_gender"}},
    summary="Approve with a room (allocation + boarding fee on the invoice) or reject",
)
async def decide(request_id: uuid.UUID, body: DecisionIn, principal: HostelOffice, session: Session):
    return await hostel.decide(session, principal, request_id, body)


@router.post("/accommodation-requests/{request_id}/cancel", response_model=AccommodationOut, tags=["hostel"])
async def cancel(request_id: uuid.UUID, principal: Signed, session: Session):
    return await hostel.cancel(session, principal, request_id)


@router.post("/hostel-allocations/{allocation_id}/vacate", status_code=204, tags=["hostel"])
async def vacate(allocation_id: uuid.UUID, _: HostelOffice, session: Session):
    await hostel.vacate(session, allocation_id)


# ---------------------------------------------------------------- transport


@router.get("/buses", response_model=list[BusSeats], tags=["transport"], summary="Buses with seats taken this term")
async def list_buses(term_id: uuid.UUID, _: TransportOffice, session: Session):
    return await transport.bus_seats(session, term_id)


@router.post("/buses", response_model=BusOut, status_code=201, tags=["transport"])
async def create_bus(body: BusIn, principal: TransportOffice, session: Session):
    item = await crud.create(session, principal, Bus, body.model_dump(), commit=False)
    await crud.flush_checked(session, "bus_no", "bus_full")
    await session.commit()
    return item


@router.patch("/buses/{bus_id}", response_model=BusOut, tags=["transport"])
async def update_bus(bus_id: uuid.UUID, body: BusUpdate, _: TransportOffice, session: Session):
    return await crud.update(session, Bus, bus_id, body.model_dump(exclude_unset=True))


@router.get("/routes", response_model=list[RouteOut], tags=["transport"])
async def list_routes(_: Signed, session: Session):
    return [await transport.route_out(session, r) for r in await crud.list_live(session, Route, Route.name)]


@router.post("/routes", response_model=RouteOut, status_code=201, tags=["transport"])
async def create_route(body: RouteIn, principal: TransportOffice, session: Session):
    return await transport.create_route(session, principal, body)


@router.patch("/routes/{route_id}", response_model=RouteOut, tags=["transport"])
async def update_route(route_id: uuid.UUID, body: RouteUpdate, principal: TransportOffice, session: Session):
    return await transport.update_route(session, principal, route_id, body)


@router.get("/transport-assignments", response_model=list[AssignmentOut], tags=["transport"])
async def list_assignments(
    term_id: uuid.UUID,
    _: TransportOffice,
    session: Session,
    bus_id: uuid.UUID | None = None,
    route_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
):
    return await transport.assignments(session, term_id, bus_id, route_id, student_id)


@router.post(
    "/transport-assignments",
    response_model=AssignmentOut,
    status_code=201,
    tags=["transport"],
    responses={422: {"description": "FULL bus_full"}, 409: {"description": "already assigned for the term"}},
    summary="Put a student on a bus and stop for a term; the route fee goes on the term's invoice",
)
async def assign(body: AssignmentIn, principal: TransportOffice, session: Session):
    return await transport.assign(session, principal, body)


@router.post("/transport-assignments/{assignment_id}/end", response_model=AssignmentOut, tags=["transport"])
async def end_assignment(assignment_id: uuid.UUID, _: TransportOffice, session: Session):
    return await transport.end(session, assignment_id)


# ---------------------------------------------------------------- venues


@router.get("/venues", response_model=list[VenueOut], tags=["venues"])
async def list_venues(_: Signed, session: Session):
    return await crud.list_live(session, Venue, Venue.name)


@router.post("/venues", response_model=VenueOut, status_code=201, tags=["venues"])
async def create_venue(body: VenueIn, principal: VenueOffice, session: Session):
    return await crud.create(session, principal, Venue, body.model_dump())


@router.get("/venue-events", response_model=list[EventOut], tags=["venues"], summary="Bookings in a date range")
async def list_events(
    _: Signed,
    session: Session,
    venue_id: uuid.UUID | None = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
):
    first = start or now().date()
    return await venues.calendar(session, venue_id, first, end or first + timedelta(days=90))


@router.post(
    "/venue-events",
    response_model=EventOut,
    status_code=201,
    tags=["venues"],
    responses={409: {"description": "VENUE_CLASH"}, 422: {"description": "FULL too_many_seats"}},
)
async def book(body: EventIn, principal: VenueOffice, session: Session):
    return await venues.book(session, principal, body)


@router.patch("/venue-events/{event_id}", response_model=EventOut, tags=["venues"])
async def change_event(event_id: uuid.UUID, body: EventUpdate, _: VenueOffice, session: Session):
    return await venues.change(session, event_id, body)


@router.delete("/venue-events/{event_id}", status_code=204, tags=["venues"])
async def cancel_event(event_id: uuid.UUID, _: VenueOffice, session: Session):
    await crud.soft_delete(session, VenueEvent, event_id, "cancelled")
