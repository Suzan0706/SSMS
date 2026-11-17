"""Morning registers (offline sync), attendance reports and the chronic-absence list.

A register is one REGISTER session per stream and school day. Phones send records with a client_record_id, so a
batch can be sent again safely. When two phones marked the same student, the later captured_at wins; an older
edit is returned as a conflict with the server value. Records may be sent up to SYNC_DAYS days late.
"""

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, forbidden
from app.models import (
    AcademicYear,
    AttendanceRecord,
    AttendanceSession,
    Enrolment,
    SchoolClass,
    Staff,
    Stream,
    StreamClassTeacher,
    Student,
    TeachingAssignment,
    User,
)
from app.models.enums import AttendanceSource, AttendanceStatus, EnrolmentStatus, SessionKind
from app.schemas.attendance import (
    AttendanceItem,
    ChronicRow,
    MyStream,
    RegisterOut,
    RegisterStudent,
    ServerRecord,
    StreamReportOut,
    StreamReportRow,
    StudentAttendanceOut,
    StudentDay,
    SyncResult,
)
from app.services import calendar, crud
from app.services.invoices import guardian_of
from app.services.people import now

SYNC_DAYS = 7
ATTENDED = (AttendanceStatus.PRESENT, AttendanceStatus.LATE)


def _name(first: str, middle: str | None, last: str) -> str:
    return " ".join(p for p in (first, middle, last) if p)


async def stream_label(session: AsyncSession, stream_id: uuid.UUID) -> str:
    row = (
        await session.execute(
            select(SchoolClass.code, Stream.name)
            .join(SchoolClass, SchoolClass.id == Stream.class_id)
            .where(Stream.id == stream_id)
        )
    ).first()
    return f"{row.code} {row.name}" if row else ""


async def _year_of(session: AsyncSession, day: date) -> uuid.UUID | None:
    term = await calendar.term_on(session, day)
    if term:
        return term.academic_year_id
    return (await session.execute(select(AcademicYear.id).where(AcademicYear.is_current))).scalar()


async def may_take(session: AsyncSession, principal: Principal, stream_id: uuid.UUID, year_id: uuid.UUID) -> bool:
    """The school office (settings.update) for every stream; otherwise its class teacher or a teacher of the
    stream, who may cover the register."""
    if not principal.has("attendance.take"):
        return False
    if principal.has("settings.update"):
        return True
    staff = select(Staff.id).where(Staff.user_id == principal.user_id, Staff.deleted_at.is_(None)).scalar_subquery()
    class_teacher = select(StreamClassTeacher.id).where(
        StreamClassTeacher.stream_id == stream_id,
        StreamClassTeacher.academic_year_id == year_id,
        StreamClassTeacher.staff_id == staff,
    )
    teaches = select(TeachingAssignment.id).where(
        TeachingAssignment.stream_id == stream_id,
        TeachingAssignment.academic_year_id == year_id,
        TeachingAssignment.staff_id == staff,
        TeachingAssignment.deleted_at.is_(None),
    )
    return bool((await session.execute(class_teacher.union_all(teaches).limit(1))).first())


async def my_streams(session: AsyncSession, principal: Principal) -> list[MyStream]:
    year_id = await _year_of(session, calendar.today())
    if year_id is None or not principal.has("attendance.take"):
        return []
    rows = (
        await session.execute(
            select(Stream.id, SchoolClass.code, Stream.name, SchoolClass.sort_order)
            .join(SchoolClass, SchoolClass.id == Stream.class_id)
            .where(Stream.deleted_at.is_(None))
            .order_by(SchoolClass.sort_order, Stream.name)
        )
    ).all()
    staff = (await session.execute(select(Staff.id).where(Staff.user_id == principal.user_id))).scalar()
    class_of = set(
        (
            await session.execute(
                select(StreamClassTeacher.stream_id).where(
                    StreamClassTeacher.academic_year_id == year_id, StreamClassTeacher.staff_id == staff
                )
            )
        ).scalars()
    )
    teaches = set(
        (
            await session.execute(
                select(TeachingAssignment.stream_id).where(
                    TeachingAssignment.academic_year_id == year_id,
                    TeachingAssignment.staff_id == staff,
                    TeachingAssignment.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    office = principal.has("settings.update")
    out = [
        MyStream(stream_id=r.id, label=f"{r.code} {r.name}", class_teacher=r.id in class_of)
        for r in rows
        if office or r.id in class_of or r.id in teaches
    ]
    return sorted(out, key=lambda s: not s.class_teacher)


async def _enrolled(session: AsyncSession, stream_id: uuid.UUID, year_id: uuid.UUID) -> list:
    return (
        await session.execute(
            select(Student.id, Student.admission_no, User.first_name, User.middle_name, User.last_name)
            .join(Enrolment, Enrolment.student_id == Student.id)
            .join(User, User.id == Student.user_id)
            .where(
                Enrolment.stream_id == stream_id,
                Enrolment.academic_year_id == year_id,
                Enrolment.status == EnrolmentStatus.ACTIVE,
            )
            .order_by(User.last_name, User.first_name)
        )
    ).all()


async def _session_of(
    session: AsyncSession, day: date, stream_id: uuid.UUID | None, kind: SessionKind = SessionKind.REGISTER
) -> AttendanceSession | None:
    stmt = select(AttendanceSession).where(
        AttendanceSession.session_date == day,
        AttendanceSession.kind == kind,
        AttendanceSession.timetable_slot_id.is_(None),
    )
    stmt = stmt.where(
        AttendanceSession.stream_id.is_(None) if stream_id is None else AttendanceSession.stream_id == stream_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def open_session(
    session: AsyncSession,
    school_id: uuid.UUID,
    day: date,
    stream_id: uuid.UUID | None,
    kind: SessionKind,
    taken_by: uuid.UUID | None,
) -> AttendanceSession:
    """Get or create the day's session and lock it, so concurrent syncs of one register queue up."""
    await session.execute(
        insert(AttendanceSession)
        .values(
            id=uuid.uuid4(),
            school_id=school_id,
            session_date=day,
            kind=kind,
            stream_id=stream_id,
            taken_by=taken_by,
            created_by=taken_by,
        )
        .on_conflict_do_nothing(constraint="uq_attendance_sessions")
    )
    stmt = select(AttendanceSession).where(
        AttendanceSession.session_date == day,
        AttendanceSession.kind == kind,
        AttendanceSession.timetable_slot_id.is_(None),
        AttendanceSession.stream_id.is_(None) if stream_id is None else AttendanceSession.stream_id == stream_id,
    )
    return (await session.execute(stmt.with_for_update())).scalar_one()


async def gate_times(session: AsyncSession, day: date, student_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """First gate tap of each student on that day."""
    if not student_ids:
        return {}
    rows = await session.execute(
        select(AttendanceRecord.student_id, func.min(AttendanceRecord.captured_at))
        .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
        .where(
            AttendanceSession.session_date == day,
            AttendanceSession.kind == SessionKind.GATE,
            AttendanceRecord.student_id.in_(student_ids),
        )
        .group_by(AttendanceRecord.student_id)
    )
    return dict(rows.all())


async def register(session: AsyncSession, principal: Principal, stream_id: uuid.UUID, day: date) -> RegisterOut:
    await crud.get_live(session, Stream, stream_id)
    year_id = await _year_of(session, day)
    if year_id is None or not (
        principal.has("attendance.read") or await may_take(session, principal, stream_id, year_id)
    ):
        raise forbidden()
    reason = await calendar.closed_reason(session, day)
    students = await _enrolled(session, stream_id, year_id)
    reg = await _session_of(session, day, stream_id)
    marks = {}
    if reg:
        marks = {
            r.student_id: r
            for r in (
                await session.execute(select(AttendanceRecord).where(AttendanceRecord.session_id == reg.id))
            ).scalars()
        }
    gate = await gate_times(session, day, [s.id for s in students])
    return RegisterOut(
        session_id=reg.id if reg else None,
        session_date=day,
        stream_id=stream_id,
        stream_label=await stream_label(session, stream_id),
        closed_at=reg.closed_at if reg else None,
        school_day=reason is None,
        reason=reason,
        students=[
            RegisterStudent(
                student_id=s.id,
                admission_no=s.admission_no,
                full_name=_name(s.first_name, s.middle_name, s.last_name),
                status=marks[s.id].status if s.id in marks else None,
                captured_at=marks[s.id].captured_at if s.id in marks else None,
                gate_in_at=gate.get(s.id),
            )
            for s in students
        ],
    )


class _Scope:
    """What one batch needs per (stream, day): permission, school-day check, enrolled students, the session."""

    def __init__(self, session: AsyncSession, principal: Principal):
        self.session, self.principal = session, principal
        self.cache: dict[tuple[uuid.UUID, date], tuple[str | None, set[uuid.UUID], AttendanceSession | None]] = {}

    async def get(self, stream_id: uuid.UUID, day: date):
        key = (stream_id, day)
        if key not in self.cache:
            self.cache[key] = await self._load(stream_id, day)
        return self.cache[key]

    async def _load(self, stream_id: uuid.UUID, day: date):
        today = calendar.today()
        if day > today:
            return "future_date", set(), None
        if day < today - timedelta(days=SYNC_DAYS):
            return "too_old", set(), None
        year_id = await _year_of(self.session, day)
        if year_id is None or not await may_take(self.session, self.principal, stream_id, year_id):
            return "forbidden", set(), None
        if await calendar.closed_reason(self.session, day):
            return "not_school_day", set(), None
        enrolled = {s.id for s in await _enrolled(self.session, stream_id, year_id)}
        reg = await open_session(
            self.session, self.principal.school_id, day, stream_id, SessionKind.REGISTER, self.principal.user_id
        )
        return None, enrolled, reg


async def sync(session: AsyncSession, principal: Principal, items: list[AttendanceItem]) -> list[SyncResult]:
    scope = _Scope(session, principal)
    results = []
    for item in items:
        problem, enrolled, reg = await scope.get(item.stream_id, item.session_date)
        if problem:
            results.append(SyncResult(client_record_id=item.client_record_id, result="error", code=problem))
            continue
        if item.student_id not in enrolled:
            results.append(SyncResult(client_record_id=item.client_record_id, result="error", code="not_enrolled"))
            continue
        existing = (
            await session.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.session_id == reg.id, AttendanceRecord.student_id == item.student_id
                )
            )
        ).scalar_one_or_none()
        captured = calendar.local(item.captured_at)
        if existing is None:
            session.add(
                AttendanceRecord(
                    school_id=principal.school_id,
                    session_id=reg.id,
                    student_id=item.student_id,
                    status=item.status,
                    source=AttendanceSource.MANUAL,
                    captured_at=captured,
                    client_record_id=item.client_record_id,
                    recorded_by=principal.user_id,
                    created_by=principal.user_id,
                )
            )
            await session.flush()
        elif existing.client_record_id == item.client_record_id or (
            existing.status == item.status and existing.captured_at >= captured
        ):
            pass  # the same record sent again, or nothing new: already synced
        elif existing.captured_at > captured:
            results.append(
                SyncResult(
                    client_record_id=item.client_record_id,
                    result="conflict",
                    server=ServerRecord(status=existing.status, captured_at=existing.captured_at),
                )
            )
            continue
        else:
            existing.status, existing.captured_at = item.status, captured
            existing.client_record_id, existing.recorded_by, existing.synced_at = (
                item.client_record_id,
                principal.user_id,
                now(),
            )
            await session.flush()
        results.append(SyncResult(client_record_id=item.client_record_id, result="synced"))
    await session.commit()
    return results


async def close(session: AsyncSession, principal: Principal, session_id: uuid.UUID) -> AttendanceSession:
    reg = await crud.get_live(session, AttendanceSession, session_id, lock=True)
    year_id = await _year_of(session, reg.session_date)
    if reg.kind != SessionKind.REGISTER or not await may_take(session, principal, reg.stream_id, year_id):
        raise forbidden()
    if reg.closed_at is None:
        reg.closed_at = now()
        await session.commit()
    return reg


# ---------------------------------------------------------------- reports


def _check_range(date_from: date, date_to: date) -> None:
    if date_to < date_from or (date_to - date_from).days > 366:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "to", "code": "invalid_range"}])


async def stream_report(session: AsyncSession, stream_id: uuid.UUID, date_from: date, date_to: date) -> StreamReportOut:
    _check_range(date_from, date_to)
    await crud.get_live(session, Stream, stream_id)
    year_id = await _year_of(session, date_from)
    students = await _enrolled(session, stream_id, year_id) if year_id else []
    sessions = select(AttendanceSession.id).where(
        AttendanceSession.stream_id == stream_id,
        AttendanceSession.kind == SessionKind.REGISTER,
        AttendanceSession.session_date.between(date_from, date_to),
    )
    days = (await session.execute(select(func.count()).select_from(sessions.subquery()))).scalar_one()
    counts: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for student_id, status, n in (
        await session.execute(
            select(AttendanceRecord.student_id, AttendanceRecord.status, func.count())
            .where(AttendanceRecord.session_id.in_(sessions))
            .group_by(AttendanceRecord.student_id, AttendanceRecord.status)
        )
    ).all():
        counts[student_id][status] = n
    rows = []
    for s in students:
        c = counts[s.id]
        marked = sum(c.values())
        attended = c[AttendanceStatus.PRESENT] + c[AttendanceStatus.LATE]
        rows.append(
            StreamReportRow(
                student_id=s.id,
                admission_no=s.admission_no,
                full_name=_name(s.first_name, s.middle_name, s.last_name),
                present=c[AttendanceStatus.PRESENT],
                late=c[AttendanceStatus.LATE],
                absent=c[AttendanceStatus.ABSENT],
                excused=c[AttendanceStatus.EXCUSED],
                rate_pct=round(100 * attended / marked, 1) if marked else None,
            )
        )
    return StreamReportOut(stream_id=stream_id, date_from=date_from, date_to=date_to, register_days=days, rows=rows)


async def may_see(session: AsyncSession, principal: Principal, student_id: uuid.UUID) -> bool:
    if principal.has("attendance.read"):
        return True
    if principal.has("portal.parent") and await guardian_of(session, principal, student_id):
        return True
    owner = (await session.execute(select(Student.user_id).where(Student.id == student_id))).scalar()
    return principal.has("portal.student") and owner == principal.user_id


async def student_attendance(
    session: AsyncSession, principal: Principal, student_id: uuid.UUID, date_from: date, date_to: date
) -> StudentAttendanceOut:
    _check_range(date_from, date_to)
    if not await may_see(session, principal, student_id):
        raise forbidden()
    await crud.get_live(session, Student, student_id)
    rows = (
        await session.execute(
            select(
                AttendanceSession.session_date,
                AttendanceSession.kind,
                AttendanceRecord.status,
                AttendanceRecord.captured_at,
            )
            .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
            .where(
                AttendanceRecord.student_id == student_id,
                AttendanceSession.session_date.between(date_from, date_to),
                AttendanceSession.kind.in_((SessionKind.REGISTER, SessionKind.GATE)),
            )
            .order_by(AttendanceSession.session_date, AttendanceRecord.captured_at)
        )
    ).all()
    status: dict[date, AttendanceStatus] = {}
    gate: dict[date, datetime] = {}
    for day, kind, st, at in rows:
        if kind == SessionKind.REGISTER:
            status[day] = st
        else:
            gate.setdefault(day, at)
    days = [StudentDay(day=d, status=status.get(d), gate_in_at=gate.get(d)) for d in sorted(set(status) | set(gate))]
    week = calendar.today() - timedelta(days=calendar.today().weekday())
    values = list(status.values())
    return StudentAttendanceOut(
        student_id=student_id,
        date_from=date_from,
        date_to=date_to,
        present=values.count(AttendanceStatus.PRESENT),
        late=values.count(AttendanceStatus.LATE),
        absent=values.count(AttendanceStatus.ABSENT),
        excused=values.count(AttendanceStatus.EXCUSED),
        days=days,
        absent_this_week=sum(1 for d, s in status.items() if d >= week and s == AttendanceStatus.ABSENT),
    )


async def chronic(session: AsyncSession, any_day: date) -> list[ChronicRow]:
    """Students absent from the morning register on 3 or more days of that week. Same rule as the view
    v_chronic_absence, but filtered on the week's dates first: the view groups the whole year before it can
    filter on its computed week_start (measured on synthetic data, scripts/explain.py)."""
    week_start = any_day - timedelta(days=any_day.weekday())
    year_id = await _year_of(session, any_day)
    rows = (
        await session.execute(
            text(
                "WITH c AS (SELECT ar.student_id, count(DISTINCT a.session_date) AS days_absent "
                "FROM attendance_records ar JOIN attendance_sessions a ON a.id = ar.session_id "
                "WHERE ar.status = 'ABSENT' AND a.kind = 'REGISTER' AND a.session_date BETWEEN :week AND :week_end "
                "GROUP BY ar.student_id HAVING count(DISTINCT a.session_date) >= 3) "
                "SELECT c.student_id, CAST(:week AS date) AS week_start, c.days_absent, st.admission_no, "
                "u.first_name, u.middle_name, u.last_name, cl.code AS class_code, s.name AS stream_name "
                "FROM c JOIN students st ON st.id = c.student_id JOIN users u ON u.id = st.user_id "
                "LEFT JOIN enrolments e ON e.student_id = c.student_id AND e.status = 'ACTIVE' "
                "AND e.academic_year_id = CAST(:year AS uuid) "
                "LEFT JOIN streams s ON s.id = e.stream_id LEFT JOIN classes cl ON cl.id = s.class_id "
                "ORDER BY c.days_absent DESC, st.admission_no"
            ).bindparams(week=week_start, week_end=week_start + timedelta(days=6), year=year_id)
        )
    ).all()
    return [
        ChronicRow(
            student_id=r.student_id,
            admission_no=r.admission_no,
            full_name=_name(r.first_name, r.middle_name, r.last_name),
            stream_label=f"{r.class_code} {r.stream_name}" if r.class_code else None,
            week_start=r.week_start,
            days_absent=r.days_absent,
        )
        for r in rows
    ]
