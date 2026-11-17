"""/me: what a signed-in parent or student sees about their own family. Small answers (parent screens < 5 KB).

Details reuse the staff endpoints, which check the same access (guardian of the student, or the student):
/students/{id}/attendance, /results, /report-card, /statement, and /announcements.
"""

import uuid
from datetime import datetime, time
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal
from app.core.errors import forbidden, not_found
from app.db.session import get_session
from app.models import (
    AcademicYear,
    AttendanceRecord,
    AttendanceSession,
    Enrolment,
    Guardian,
    Room,
    SchoolClass,
    Staff,
    Stream,
    Student,
    StudentGuardian,
    Subject,
    TimetableSlot,
    User,
)
from app.models.enums import EnrolmentStatus, SessionKind
from app.schemas.finance import MoneyOut
from app.services import calendar
from app.services.attendance import gate_times

router = APIRouter(prefix="/me", tags=["portal"])
Session = Annotated[AsyncSession, Depends(get_session)]
Signed = Annotated[Principal, Depends(active_principal)]


class Child(BaseModel):
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    class_code: str | None
    stream_name: str | None
    stream_id: uuid.UUID | None
    outstanding_tzs: MoneyOut
    credit_tzs: MoneyOut
    today_status: str | None = None  # register mark today (PRESENT, ABSENT, LATE, EXCUSED)
    gate_in_at: datetime | None = None


class StudentHome(BaseModel):
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    class_code: str | None
    stream_name: str | None
    outstanding_tzs: MoneyOut
    today_status: str | None
    gate_in_at: datetime | None


class Lesson(BaseModel):
    day_of_week: int
    time_start: time
    time_end: time
    subject_code: str
    subject_en: str
    subject_sw: str
    teacher: str
    room: str


def _people_query():
    return (
        select(
            Student.id,
            Student.admission_no,
            User.first_name,
            User.middle_name,
            User.last_name,
            SchoolClass.code,
            Stream.name,
            Stream.id.label("stream_id"),
        )
        .join(User, User.id == Student.user_id)
        .outerjoin(Enrolment, and_(Enrolment.student_id == Student.id, Enrolment.status == EnrolmentStatus.ACTIVE))
        .outerjoin(AcademicYear, and_(AcademicYear.id == Enrolment.academic_year_id, AcademicYear.is_current))
        .outerjoin(Stream, Stream.id == Enrolment.stream_id)
        .outerjoin(SchoolClass, SchoolClass.id == Stream.class_id)
        .where(Student.deleted_at.is_(None))
    )


async def _positions(session: AsyncSession, ids: list[uuid.UUID]) -> dict:
    if not ids:
        return {}
    query = text(
        "SELECT student_id, outstanding_tzs, credit_tzs FROM v_student_fee_position WHERE student_id = ANY(:ids)"
    )
    return {
        r.student_id: (r.outstanding_tzs, r.credit_tzs)
        for r in (await session.execute(query.bindparams(ids=ids))).all()
    }


async def _today(session: AsyncSession, ids: list[uuid.UUID]) -> tuple[dict, dict]:
    """(register status, first gate tap) per student for today in EAT."""
    day = calendar.today()
    marks = (
        dict(
            (
                await session.execute(
                    select(AttendanceRecord.student_id, AttendanceRecord.status)
                    .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
                    .where(
                        AttendanceSession.session_date == day,
                        AttendanceSession.kind == SessionKind.REGISTER,
                        AttendanceRecord.student_id.in_(ids),
                    )
                )
            ).all()
        )
        if ids
        else {}
    )
    return marks, await gate_times(session, day, ids)


def _name(r) -> str:
    return " ".join(p for p in (r.first_name, r.middle_name, r.last_name) if p)


@router.get("/children", response_model=list[Child], summary="The signed-in guardian's children: class, fees, today")
async def children(principal: Signed, session: Session):
    rows = (
        await session.execute(
            _people_query()
            .join(StudentGuardian, and_(StudentGuardian.student_id == Student.id, StudentGuardian.deleted_at.is_(None)))
            .join(Guardian, Guardian.id == StudentGuardian.guardian_id)
            .where(Guardian.user_id == principal.user_id)
            .order_by(User.first_name)
        )
    ).all()
    ids = list(dict.fromkeys(r.id for r in rows))
    positions = await _positions(session, ids)
    marks, gate = await _today(session, ids)
    out, seen = [], set()
    for r in rows:
        if r.id in seen:
            continue
        seen.add(r.id)
        owed, credit = positions.get(r.id, (Decimal("0"), Decimal("0")))
        out.append(
            Child(
                student_id=r.id,
                admission_no=r.admission_no,
                full_name=_name(r),
                class_code=r.code,
                stream_name=r.name,
                stream_id=r.stream_id,
                outstanding_tzs=owed,
                credit_tzs=credit,
                today_status=marks.get(r.id),
                gate_in_at=gate.get(r.id),
            )
        )
    return out


async def _own(session: AsyncSession, principal: Principal):
    if not principal.has("portal.student"):
        raise forbidden()
    row = (await session.execute(_people_query().where(Student.user_id == principal.user_id))).first()
    if row is None:
        raise not_found()
    return row


@router.get("/student", response_model=StudentHome, summary="The signed-in student's home: class, fees, today")
async def student_home(principal: Signed, session: Session):
    r = await _own(session, principal)
    owed, _ = (await _positions(session, [r.id])).get(r.id, (Decimal("0"), Decimal("0")))
    marks, gate = await _today(session, [r.id])
    return StudentHome(
        student_id=r.id,
        admission_no=r.admission_no,
        full_name=_name(r),
        class_code=r.code,
        stream_name=r.name,
        outstanding_tzs=owed,
        today_status=marks.get(r.id),
        gate_in_at=gate.get(r.id),
    )


@router.get("/timetable", response_model=list[Lesson], summary="The signed-in student's lessons this term")
async def timetable(principal: Signed, session: Session):
    r = await _own(session, principal)
    term = await calendar.term_on(session, calendar.today())
    if term is None or r.stream_id is None:
        return []
    rows = (
        await session.execute(
            select(
                TimetableSlot.day_of_week,
                TimetableSlot.time_start,
                TimetableSlot.time_end,
                Subject.code,
                Subject.name_en,
                Subject.name_sw,
                User.first_name,
                User.last_name,
                Room.name.label("room"),
            )
            .join(Subject, Subject.id == TimetableSlot.subject_id)
            .join(Staff, Staff.id == TimetableSlot.staff_id)
            .join(User, User.id == Staff.user_id)
            .join(Room, Room.id == TimetableSlot.room_id)
            .where(
                TimetableSlot.term_id == term.id,
                TimetableSlot.stream_id == r.stream_id,
                TimetableSlot.deleted_at.is_(None),
            )
            .order_by(TimetableSlot.day_of_week, TimetableSlot.time_start)
        )
    ).all()
    return [
        Lesson(
            day_of_week=x.day_of_week,
            time_start=x.time_start,
            time_end=x.time_end,
            subject_code=x.code,
            subject_en=x.name_en,
            subject_sw=x.name_sw,
            teacher=f"{x.first_name} {x.last_name}",
            room=x.room,
        )
        for x in rows
    ]
