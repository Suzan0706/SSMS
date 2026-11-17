"""Front office (/inquiries, /events), staff attendance and leave (FR-77, FR-80, FR-81, FR-99)."""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.core.errors import forbidden
from app.core.pagination import Cursor, Limit, Page
from app.db.session import get_session
from app.models import LeaveType, SchoolEvent
from app.schemas.front_office import (
    ConvertIn,
    DecisionIn,
    EventIn,
    EventOut,
    InquiryIn,
    InquiryOut,
    InquiryUpdate,
    LeaveIn,
    LeaveOut,
    LeaveTypeIn,
    LeaveTypeOut,
    StaffDayIn,
    StaffDayRow,
    StaffMonthRow,
)
from app.services import calendar, crud
from app.services import front_office as service

router = APIRouter(tags=["front office"])
Session = Annotated[AsyncSession, Depends(get_session)]
Signed = Annotated[Principal, Depends(active_principal)]
Desk = Annotated[Principal, require_permission("inquiries.manage")]
Planner = Annotated[Principal, require_permission("calendar.manage")]
Taker = Annotated[Principal, require_permission("staff_attendance.take")]
Viewer = Annotated[Principal, require_permission("staff_attendance.read", "staff_attendance.take")]
Decider = Annotated[Principal, require_permission("leave.decide")]
Reason = Annotated[str, Query(min_length=3, max_length=300, description="Why it is removed (audited)")]


# ---------------------------------------------------------------- inquiries


@router.get("/inquiries", response_model=Page[InquiryOut], summary="Admission inquiries, newest first")
async def list_inquiries(
    _: Desk,
    session: Session,
    status_: Annotated[Literal["OPEN", "CONVERTED", "CLOSED"] | None, Query(alias="status")] = None,
    due: Annotated[bool, Query(description="Only open inquiries whose follow-up date has come")] = False,
    q: Annotated[str | None, Query(max_length=60)] = None,
    limit: Limit = 50,
    cursor: Cursor = None,
):
    items, next_cursor = await service.list_inquiries(session, status=status_, due=due, q=q, limit=limit, cursor=cursor)
    return Page(items=items, next_cursor=next_cursor)


@router.post("/inquiries", response_model=InquiryOut, status_code=status.HTTP_201_CREATED)
async def create_inquiry(body: InquiryIn, principal: Desk, session: Session):
    return service.inquiry_out(await service.create_inquiry(session, principal, body))


@router.patch("/inquiries/{inquiry_id}", response_model=InquiryOut, summary="Notes, follow-up date, close")
async def update_inquiry(inquiry_id: uuid.UUID, body: InquiryUpdate, _: Desk, session: Session):
    return service.inquiry_out(await service.update_inquiry(session, inquiry_id, body))


@router.post(
    "/inquiries/{inquiry_id}/convert",
    status_code=status.HTTP_201_CREATED,
    summary="Make an enrolment application from the inquiry; returns the application id",
)
async def convert_inquiry(inquiry_id: uuid.UUID, body: ConvertIn, principal: Desk, session: Session) -> dict:
    if not principal.has("enrolment.manage"):
        raise forbidden()
    return {"application_id": await service.convert_inquiry(session, principal, inquiry_id, body.application)}


# ---------------------------------------------------------------- calendar


@router.get("/events", response_model=list[EventOut], summary="School calendar for the caller's audience")
async def list_events(
    principal: Signed,
    session: Session,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
):
    start = date_from or calendar.today()
    return await service.list_events(session, principal, start, date_to or date(start.year + 1, start.month, 1))


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(body: EventIn, principal: Planner, session: Session):
    return await service.create_event(session, principal, body)


@router.put("/events/{event_id}", response_model=EventOut)
async def update_event(event_id: uuid.UUID, body: EventIn, _: Planner, session: Session):
    return await service.update_event(session, event_id, body)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(event_id: uuid.UUID, reason: Reason, _: Planner, session: Session):
    await crud.soft_delete(session, SchoolEvent, event_id, reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- staff attendance


@router.get("/staff-attendance", response_model=list[StaffDayRow], summary="Every active staff member on one day")
async def staff_day(on: date, _: Viewer, session: Session):
    return await service.staff_day(session, on)


@router.put("/staff-attendance", status_code=status.HTTP_204_NO_CONTENT, summary="Record or correct a day")
async def save_staff_day(on: date, body: StaffDayIn, principal: Taker, session: Session):
    await service.save_staff_day(session, principal, on, body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/staff-attendance/monthly", response_model=list[StaffMonthRow], summary="Counts per staff member")
async def staff_month(
    year: Annotated[int, Query(ge=2000, le=2100)],
    month: Annotated[int, Query(ge=1, le=12)],
    _: Viewer,
    session: Session,
):
    return await service.staff_month(session, year, month)


# ---------------------------------------------------------------- leave


@router.get("/leave-types", response_model=list[LeaveTypeOut])
async def list_leave_types(_: Signed, session: Session):
    return await crud.list_live(session, LeaveType, LeaveType.applies_to, LeaveType.name_en)


@router.post("/leave-types", response_model=LeaveTypeOut, status_code=status.HTTP_201_CREATED)
async def create_leave_type(body: LeaveTypeIn, principal: Decider, session: Session):
    return await service.create_leave_type(session, principal, body)


@router.get("/leave-requests", response_model=list[LeaveOut], summary="Your requests, or everyone's with leave.decide")
async def list_leave(
    principal: Signed,
    session: Session,
    scope: Literal["mine", "all"] = "mine",
    status_: Annotated[Literal["PENDING", "APPROVED", "REJECTED", "CANCELLED"] | None, Query(alias="status")] = None,
):
    if scope == "all" and not principal.has("leave.decide"):
        raise forbidden()
    return await service.list_leave(session, principal, status=status_, everyone=scope == "all")


@router.post("/leave-requests", status_code=status.HTTP_201_CREATED, summary="Ask for leave (yours or a student's)")
async def request_leave(body: LeaveIn, principal: Signed, session: Session) -> dict:
    if body.student_id is None and not principal.has("leave.request"):
        raise forbidden()
    return {"id": await service.request_leave(session, principal, body)}


@router.post("/leave-requests/{leave_id}/decide", status_code=status.HTTP_204_NO_CONTENT)
async def decide_leave(leave_id: uuid.UUID, body: DecisionIn, principal: Decider, session: Session):
    await service.decide_leave(session, principal, leave_id, body.approve, body.note)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/leave-requests/{leave_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_leave(leave_id: uuid.UUID, principal: Signed, session: Session):
    await service.cancel_leave(session, principal, leave_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
