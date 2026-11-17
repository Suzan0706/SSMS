"""Hostels: rooms, accommodation requests (student, guardian or hostel office), decisions, occupancy.

Approving a request allocates a room for the term in the same transaction; the database refuses a full room
(fn_capacity_guard -> 422 FULL room_full) and a second open request or allocation for the same term. A hostel for one
gender only takes students of that gender. The boarding fee (optional BOARDING fee-structure line) is added to the
student's invoice for the term when it already exists.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, forbidden, not_found
from app.models import (
    AccommodationRequest,
    Guardian,
    Hostel,
    HostelAllocation,
    HostelRoom,
    SchoolSettings,
    Student,
    StudentGuardian,
    Term,
    User,
)
from app.models.enums import AccommodationStatus, HostelGender
from app.schemas.facilities import (
    AccommodationIn,
    AccommodationOut,
    DecisionIn,
    HostelOut,
    OccupancyOut,
    Occupant,
    RoomOccupancy,
)
from app.services import crud, facility_fees, invoices
from app.services.invoices import guardian_of
from app.services.people import now

MANAGE = "hostel.manage"


def _name(first: str, middle: str | None, last: str) -> str:
    return " ".join(p for p in (first, middle, last) if p)


async def hostel_out(session: AsyncSession, hostel: Hostel) -> HostelOut:
    rooms, beds = (
        await session.execute(
            select(func.count(HostelRoom.id), func.coalesce(func.sum(HostelRoom.capacity), 0)).where(
                HostelRoom.hostel_id == hostel.id, HostelRoom.deleted_at.is_(None)
            )
        )
    ).one()
    return HostelOut(
        id=hostel.id,
        name=hostel.name,
        gender=hostel.gender,
        warden_staff_id=hostel.warden_staff_id,
        rooms=rooms,
        beds=beds,
    )


async def _student_gender(session: AsyncSession, student_id: uuid.UUID) -> str | None:
    return (
        await session.execute(
            select(User.gender).join(Student, Student.user_id == User.id).where(Student.id == student_id)
        )
    ).scalar()


def _check_gender(hostel: Hostel, gender: str | None) -> None:
    if hostel.gender != HostelGender.MIXED and gender != hostel.gender:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "hostel", "code": "wrong_gender"}])


async def _own_student(session: AsyncSession, principal: Principal) -> uuid.UUID | None:
    return (
        await session.execute(
            select(Student.id).where(Student.user_id == principal.user_id, Student.deleted_at.is_(None))
        )
    ).scalar()


async def request(session: AsyncSession, principal: Principal, body: AccommodationIn) -> AccommodationOut:
    if principal.has(MANAGE) and body.student_id:
        student_id = body.student_id
    elif principal.has("portal.student") and (own := await _own_student(session, principal)):
        student_id = own
    elif principal.has("portal.parent") and body.student_id:
        if not await guardian_of(session, principal, body.student_id):
            raise AppError(403, "FORBIDDEN", [{"field": "student_id", "code": "not_own_child"}])
        student_id = body.student_id
    else:
        raise forbidden()
    await crud.get_live(session, Student, student_id)
    await crud.get_live(session, Term, body.term_id)
    if body.preferred_hostel_id:
        _check_gender(
            await crud.get_live(session, Hostel, body.preferred_hostel_id), await _student_gender(session, student_id)
        )
    item = AccommodationRequest(
        school_id=principal.school_id,
        student_id=student_id,
        term_id=body.term_id,
        preferred_hostel_id=body.preferred_hostel_id,
        note=body.note,
        created_by=principal.user_id,
    )
    session.add(item)
    await crud.flush_checked(session, "term_id", "room_full")
    await session.commit()
    return (await requests(session, principal, ids=[item.id]))[0]


async def requests(
    session: AsyncSession,
    principal: Principal,
    term_id: uuid.UUID | None = None,
    status: str | None = None,
    ids: list[uuid.UUID] | None = None,
) -> list[AccommodationOut]:
    """The hostel office sees every request; a guardian their children's; a student their own."""
    stmt = (
        select(
            AccommodationRequest, Student.admission_no, User.first_name, User.middle_name, User.last_name, User.gender
        )
        .join(Student, Student.id == AccommodationRequest.student_id)
        .join(User, User.id == Student.user_id)
        .where(AccommodationRequest.deleted_at.is_(None))
        .order_by(AccommodationRequest.created_at.desc())
        .limit(200)
    )
    if ids:
        stmt = stmt.where(AccommodationRequest.id.in_(ids))
    if term_id:
        stmt = stmt.where(AccommodationRequest.term_id == term_id)
    if status:
        stmt = stmt.where(AccommodationRequest.status == status)
    if not principal.has(MANAGE):
        own = await _own_student(session, principal)
        stmt = stmt.where(
            (AccommodationRequest.student_id == own) | AccommodationRequest.student_id.in_(_children_of(principal))
        )
    rows = (await session.execute(stmt)).all()
    rooms = await _rooms_of(session, [r[0].id for r in rows])
    return [
        AccommodationOut(
            id=item.id,
            student_id=item.student_id,
            admission_no=admission,
            full_name=_name(first, middle, last),
            gender=gender,
            term_id=item.term_id,
            preferred_hostel_id=item.preferred_hostel_id,
            status=item.status,
            note=item.note,
            decided_at=item.decided_at,
            room=rooms.get(item.id),
        )
        for item, admission, first, middle, last, gender in rows
    ]


def _children_of(principal: Principal):
    return (
        select(StudentGuardian.student_id)
        .join(Guardian, Guardian.id == StudentGuardian.guardian_id)
        .where(Guardian.user_id == principal.user_id, StudentGuardian.deleted_at.is_(None))
    )


async def _rooms_of(session: AsyncSession, request_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not request_ids:
        return {}
    rows = await session.execute(
        select(HostelAllocation.request_id, Hostel.name, HostelRoom.name)
        .join(HostelRoom, HostelRoom.id == HostelAllocation.hostel_room_id)
        .join(Hostel, Hostel.id == HostelRoom.hostel_id)
        .where(HostelAllocation.request_id.in_(request_ids), HostelAllocation.vacated_at.is_(None))
    )
    return {r[0]: f"{r[1]} / {r[2]}" for r in rows.all()}


async def decide(
    session: AsyncSession, principal: Principal, request_id: uuid.UUID, body: DecisionIn
) -> AccommodationOut:
    item = await crud.get_live(session, AccommodationRequest, request_id, lock=True)
    if item.status != AccommodationStatus.PENDING:
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "invalid_value"}])
    invoice_no = None
    if body.approve:
        room = await crud.get_live(session, HostelRoom, body.room_id)
        _check_gender(
            await crud.get_live(session, Hostel, room.hostel_id), await _student_gender(session, item.student_id)
        )
        session.add(
            HostelAllocation(
                school_id=principal.school_id,
                student_id=item.student_id,
                hostel_room_id=room.id,
                term_id=item.term_id,
                request_id=item.id,
                created_by=principal.user_id,
            )
        )
        await crud.flush_checked(session, "room_id", "room_full")
        term = await crud.get_live(session, Term, item.term_id)
        lang = (await session.execute(select(SchoolSettings.default_language))).scalar() or "sw"
        charges = await facility_fees.boarding(session, item.student_id, term, lang)
        invoice_no = await invoices.add_charges(
            session, principal.school_id, item.student_id, item.term_id, charges, principal.user_id
        )
    item.status = AccommodationStatus.APPROVED if body.approve else AccommodationStatus.REJECTED
    item.decided_by, item.decided_at, item.note = principal.user_id, now(), body.note or item.note
    await session.commit()
    out = (await requests(session, principal, ids=[item.id]))[0]
    out.invoice_no = invoice_no
    return out


async def cancel(session: AsyncSession, principal: Principal, request_id: uuid.UUID) -> AccommodationOut:
    """The requester (or the hostel office) withdraws a request that is still pending."""
    mine = await requests(session, principal, ids=[request_id])
    if not mine:
        raise not_found()
    item = await crud.get_live(session, AccommodationRequest, request_id, lock=True)
    if item.status != AccommodationStatus.PENDING:
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "invalid_value"}])
    item.status = AccommodationStatus.CANCELLED
    await session.commit()
    return (await requests(session, principal, ids=[item.id]))[0]


async def vacate(session: AsyncSession, allocation_id: uuid.UUID) -> None:
    allocation = await crud.get_live(session, HostelAllocation, allocation_id, lock=True)
    if allocation.vacated_at is None:
        allocation.vacated_at = now()
        await session.commit()


async def occupancy(session: AsyncSession, hostel_id: uuid.UUID, term_id: uuid.UUID) -> OccupancyOut:
    await crud.get_live(session, Hostel, hostel_id)
    rooms = await crud.list_live(session, HostelRoom, HostelRoom.name, where=[HostelRoom.hostel_id == hostel_id])
    rows = (
        await session.execute(
            select(HostelAllocation, Student.admission_no, User.first_name, User.middle_name, User.last_name)
            .join(Student, Student.id == HostelAllocation.student_id)
            .join(User, User.id == Student.user_id)
            .where(
                HostelAllocation.hostel_room_id.in_([r.id for r in rooms]),
                HostelAllocation.term_id == term_id,
                HostelAllocation.vacated_at.is_(None),
            )
        )
    ).all()
    occupants: dict[uuid.UUID, list[Occupant]] = {r.id: [] for r in rooms}
    for allocation, admission, first, middle, last in rows:
        occupants[allocation.hostel_room_id].append(
            Occupant(
                allocation_id=allocation.id,
                student_id=allocation.student_id,
                admission_no=admission,
                full_name=_name(first, middle, last),
            )
        )
    return OccupancyOut(
        hostel_id=hostel_id,
        term_id=term_id,
        beds=sum(r.capacity for r in rooms),
        used=len(rows),
        rooms=[RoomOccupancy(room_id=r.id, name=r.name, capacity=r.capacity, occupants=occupants[r.id]) for r in rooms],
    )
