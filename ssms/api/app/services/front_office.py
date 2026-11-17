"""Admission inquiries, the school calendar, staff attendance and leave (FR-77, FR-80, FR-81, FR-99)."""

import uuid
from datetime import date

from sqlalchemy import and_, extract, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, forbidden, not_found
from app.core.pagination import paginate
from app.models import (
    AdmissionInquiry,
    LeaveRequest,
    LeaveType,
    SchoolEvent,
    Staff,
    StaffAttendance,
    Student,
    User,
)
from app.schemas.front_office import (
    EventIn,
    InquiryIn,
    InquiryOut,
    InquiryUpdate,
    LeaveIn,
    LeaveOut,
    LeaveTypeIn,
    StaffDayIn,
    StaffDayRow,
    StaffMonthRow,
)
from app.services import calendar, crud, enrolment
from app.services.people import now

FULL_NAME = func.concat_ws(" ", User.first_name, User.last_name)


# ---------------------------------------------------------------- inquiries


def inquiry_out(row: AdmissionInquiry) -> InquiryOut:
    return InquiryOut.model_validate(row, from_attributes=True)


async def list_inquiries(
    session: AsyncSession, *, status: str | None, due: bool, q: str | None, limit: int, cursor: str | None
) -> tuple[list[InquiryOut], str | None]:
    stmt = select(AdmissionInquiry).where(AdmissionInquiry.deleted_at.is_(None))
    if status:
        stmt = stmt.where(AdmissionInquiry.status == status)
    if due:  # follow-ups that are due today or overdue
        stmt = stmt.where(AdmissionInquiry.status == "OPEN", AdmissionInquiry.follow_up_on <= calendar.today())
    if q:
        stmt = stmt.where(or_(AdmissionInquiry.full_name.ilike(f"%{q}%"), AdmissionInquiry.phone.contains(q)))
    rows, next_cursor = await paginate(
        session, stmt, [AdmissionInquiry.created_at, AdmissionInquiry.id], limit, cursor, descending=True
    )
    return [inquiry_out(r[0]) for r in rows], next_cursor


async def create_inquiry(session: AsyncSession, principal: Principal, body: InquiryIn) -> AdmissionInquiry:
    data = body.model_dump()
    data["email"] = str(body.email) if body.email else None
    return await crud.create(session, principal, AdmissionInquiry, data)


async def update_inquiry(session: AsyncSession, inquiry_id: uuid.UUID, body: InquiryUpdate) -> AdmissionInquiry:
    row = await crud.get_live(session, AdmissionInquiry, inquiry_id, lock=True)
    if row.status == "CONVERTED":
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "already_converted"}])
    return await crud.update(session, AdmissionInquiry, inquiry_id, body.model_dump(exclude_unset=True))


async def convert_inquiry(session: AsyncSession, principal: Principal, inquiry_id: uuid.UUID, application) -> uuid.UUID:
    """Make an enrolment application from an open inquiry and link the two."""
    row = await crud.get_live(session, AdmissionInquiry, inquiry_id, lock=True)
    if row.status != "OPEN":
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "not_open"}])
    application_id = await enrolment.create(session, principal, application)  # commits the application
    row = await crud.get_live(session, AdmissionInquiry, inquiry_id, lock=True)
    row.status, row.application_id = "CONVERTED", application_id
    await session.commit()
    return application_id


# ---------------------------------------------------------------- calendar


def audiences_for(principal: Principal) -> tuple[str, ...]:
    if principal.has("portal.parent"):
        return ("ALL", "PARENTS")
    if principal.has("portal.student"):
        return ("ALL", "STUDENTS")
    return ("ALL", "STAFF", "PARENTS", "STUDENTS")  # staff see the whole calendar


async def list_events(session: AsyncSession, principal: Principal, start: date, end: date) -> list[SchoolEvent]:
    return list(
        (
            await session.execute(
                select(SchoolEvent)
                .where(
                    SchoolEvent.deleted_at.is_(None),
                    SchoolEvent.audience.in_(audiences_for(principal)),
                    SchoolEvent.starts_on <= end,
                    SchoolEvent.ends_on >= start,
                )
                .order_by(SchoolEvent.starts_on, SchoolEvent.title_en)
            )
        ).scalars()
    )


async def create_event(session: AsyncSession, principal: Principal, body: EventIn) -> SchoolEvent:
    return await crud.create(session, principal, SchoolEvent, body.model_dump())


async def update_event(session: AsyncSession, event_id: uuid.UUID, body: EventIn) -> SchoolEvent:
    return await crud.update(session, SchoolEvent, event_id, body.model_dump())


# ---------------------------------------------------------------- staff attendance


async def _approved_staff_leave(session: AsyncSession, start: date, end: date) -> list[tuple[uuid.UUID, date, date]]:
    return list(
        (
            await session.execute(
                select(LeaveRequest.staff_id, LeaveRequest.start_date, LeaveRequest.end_date).where(
                    LeaveRequest.status == "APPROVED",
                    LeaveRequest.staff_id.is_not(None),
                    LeaveRequest.start_date <= end,
                    LeaveRequest.end_date >= start,
                )
            )
        ).all()
    )


async def staff_day(session: AsyncSession, day: date) -> list[StaffDayRow]:
    rows = (
        await session.execute(
            select(Staff.id, Staff.staff_no, FULL_NAME, StaffAttendance)
            .join(User, User.id == Staff.user_id)
            .outerjoin(StaffAttendance, and_(StaffAttendance.staff_id == Staff.id, StaffAttendance.on_date == day))
            .where(Staff.status.in_(("ACTIVE", "ON_LEAVE")), Staff.deleted_at.is_(None))
            .order_by(User.last_name, User.first_name)
        )
    ).all()
    leave = {staff_id for staff_id, _, _ in await _approved_staff_leave(session, day, day)}
    return [
        StaffDayRow(
            staff_id=staff_id,
            staff_no=staff_no,
            full_name=name,
            status=mark.status if mark else None,
            on_leave=staff_id in leave,
            time_in=mark.time_in if mark else None,
            time_out=mark.time_out if mark else None,
            note=mark.note if mark else None,
        )
        for staff_id, staff_no, name, mark in rows
    ]


async def save_staff_day(session: AsyncSession, principal: Principal, day: date, body: StaffDayIn) -> None:
    if day > calendar.today():
        raise AppError(422, "VALIDATION_ERROR", [{"field": "date", "code": "future_date"}])
    known = set((await session.execute(select(Staff.id).where(Staff.deleted_at.is_(None)))).scalars())
    existing = {
        r.staff_id: r
        for r in (await session.execute(select(StaffAttendance).where(StaffAttendance.on_date == day))).scalars()
    }
    for mark in body.marks:
        if mark.staff_id not in known:
            raise AppError(422, "INVALID_REFERENCE", [{"field": "staff_id", "code": "invalid_value"}])
        values = mark.model_dump(exclude={"staff_id"})
        row = existing.get(mark.staff_id)
        if row is None:
            session.add(
                StaffAttendance(
                    school_id=principal.school_id,
                    staff_id=mark.staff_id,
                    on_date=day,
                    created_by=principal.user_id,
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(row, key, value)
    await session.commit()


async def staff_month(session: AsyncSession, year: int, month: int) -> list[StaffMonthRow]:
    counts = (
        select(
            StaffAttendance.staff_id,
            func.count().filter(StaffAttendance.status == "PRESENT").label("present"),
            func.count().filter(StaffAttendance.status == "LATE").label("late"),
            func.count().filter(StaffAttendance.status == "ABSENT").label("absent"),
            func.count().filter(StaffAttendance.status == "ON_LEAVE").label("on_leave"),
        )
        .where(extract("year", StaffAttendance.on_date) == year, extract("month", StaffAttendance.on_date) == month)
        .group_by(StaffAttendance.staff_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(Staff.id, FULL_NAME, counts.c.present, counts.c.late, counts.c.absent, counts.c.on_leave)
            .join(User, User.id == Staff.user_id)
            .outerjoin(counts, counts.c.staff_id == Staff.id)
            .where(Staff.status.in_(("ACTIVE", "ON_LEAVE")), Staff.deleted_at.is_(None))
            .order_by(User.last_name, User.first_name)
        )
    ).all()
    return [
        StaffMonthRow(staff_id=s, full_name=n, present=p or 0, late=la or 0, absent=a or 0, on_leave=o or 0)
        for s, n, p, la, a, o in rows
    ]


# ---------------------------------------------------------------- leave


async def create_leave_type(session: AsyncSession, principal: Principal, body: LeaveTypeIn) -> LeaveType:
    item = await crud.create(session, principal, LeaveType, body.model_dump(), commit=False)
    await crud.flush_checked(session, "name_en", "duplicate")
    await session.commit()
    return item


async def own_staff_id(session: AsyncSession, principal: Principal) -> uuid.UUID | None:
    return (
        await session.execute(select(Staff.id).where(Staff.user_id == principal.user_id, Staff.deleted_at.is_(None)))
    ).scalar_one_or_none()


def _days(start: date, end: date) -> int:
    return (end - start).days + 1


async def request_leave(session: AsyncSession, principal: Principal, body: LeaveIn) -> uuid.UUID:
    kind = await crud.get_live(session, LeaveType, body.leave_type_id)
    staff_id = None
    if body.student_id is None:
        staff_id = await own_staff_id(session, principal)
        if staff_id is None or kind.applies_to != "STAFF":
            raise AppError(422, "VALIDATION_ERROR", [{"field": "leave_type_id", "code": "not_for_staff"}])
        if kind.days_per_year:
            year_start, year_end = date(body.start_date.year, 1, 1), date(body.start_date.year, 12, 31)
            taken = (
                await session.execute(
                    select(LeaveRequest.start_date, LeaveRequest.end_date).where(
                        LeaveRequest.staff_id == staff_id,
                        LeaveRequest.leave_type_id == kind.id,
                        LeaveRequest.status.in_(("PENDING", "APPROVED")),
                        LeaveRequest.start_date <= year_end,
                        LeaveRequest.end_date >= year_start,
                    )
                )
            ).all()
            used = sum(_days(s, e) for s, e in taken)
            if used + _days(body.start_date, body.end_date) > kind.days_per_year:
                raise AppError(
                    422,
                    "LEAVE_DAYS_EXCEEDED",
                    [{"field": "end_date", "code": "over_limit"}],
                    left=kind.days_per_year - used,
                )
    else:
        # class teachers and the office ask for a student's leave
        if not (principal.has("attendance.take") or principal.has("leave.decide")):
            raise forbidden()
        if kind.applies_to != "STUDENT":
            raise AppError(422, "VALIDATION_ERROR", [{"field": "leave_type_id", "code": "not_for_students"}])
        await crud.get_live(session, Student, body.student_id)
    row = LeaveRequest(
        school_id=principal.school_id,
        leave_type_id=kind.id,
        staff_id=staff_id,
        student_id=body.student_id,
        start_date=body.start_date,
        end_date=body.end_date,
        reason=body.reason,
        created_by=principal.user_id,
    )
    session.add(row)
    await session.commit()
    return row.id


async def list_leave(
    session: AsyncSession, principal: Principal, *, status: str | None, everyone: bool
) -> list[LeaveOut]:
    staff_user = User.__table__.alias("staff_user")
    student_user = User.__table__.alias("student_user")
    stmt = (
        select(
            LeaveRequest,
            LeaveType,
            staff_user.c.first_name,
            staff_user.c.last_name,
            student_user.c.first_name,
            student_user.c.last_name,
        )
        .join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
        .outerjoin(Staff, Staff.id == LeaveRequest.staff_id)
        .outerjoin(staff_user, staff_user.c.id == Staff.user_id)
        .outerjoin(Student, Student.id == LeaveRequest.student_id)
        .outerjoin(student_user, student_user.c.id == Student.user_id)
        .order_by(LeaveRequest.created_at.desc())
        .limit(200)
    )
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    if not everyone:
        stmt = stmt.where(LeaveRequest.created_by == principal.user_id)
    lang_en = principal.language == "en"
    out = []
    for req, kind, sf, sl, tf, tl in (await session.execute(stmt)).all():
        out.append(
            LeaveOut(
                id=req.id,
                leave_type_id=kind.id,
                type_name=kind.name_en if lang_en else kind.name_sw,
                person=" ".join(p for p in (sf or tf, sl or tl) if p),
                staff_id=req.staff_id,
                student_id=req.student_id,
                start_date=req.start_date,
                end_date=req.end_date,
                days=_days(req.start_date, req.end_date),
                reason=req.reason,
                status=req.status,
                decision_note=req.decision_note,
                requested_by_me=req.created_by == principal.user_id,
                created_at=req.created_at,
            )
        )
    return out


async def decide_leave(
    session: AsyncSession, principal: Principal, leave_id: uuid.UUID, approve: bool, note: str | None
) -> None:
    row = await crud.get_live(session, LeaveRequest, leave_id, lock=True)
    if row.status != "PENDING":
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "already_decided"}])
    if row.created_by == principal.user_id:
        raise AppError(403, "NOT_ALLOWED", [{"field": "decided_by", "code": "own_request"}])
    row.status = "APPROVED" if approve else "REJECTED"
    row.decided_by, row.decided_at, row.decision_note = principal.user_id, now(), note
    try:
        await session.commit()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23P01":  # overlaps leave already approved
            await session.rollback()
            raise AppError(409, "LEAVE_OVERLAP", [{"field": "start_date", "code": "overlap"}]) from None
        raise


async def cancel_leave(session: AsyncSession, principal: Principal, leave_id: uuid.UUID) -> None:
    row = await crud.get_live(session, LeaveRequest, leave_id, lock=True)
    if row.created_by != principal.user_id:
        raise not_found()
    if row.status != "PENDING":  # a decided request stays on record; the office can reject a new one instead
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "cannot_cancel"}])
    row.status = "CANCELLED"
    await session.commit()
