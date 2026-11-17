"""Teaching assignments, timetable checks, manual slots and the timetable generator (caller's school context).

The database has the final word on clashes (three EXCLUDE constraints on teacher, room and stream); the checks
here explain problems before saving and add rules the database cannot see (assignment, room fit, teacher load).
"""

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import time

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, not_found
from app.models import (
    AcademicYear,
    ClassSubject,
    Combination,
    CombinationSubject,
    Enrolment,
    Room,
    SchoolClass,
    Staff,
    StaffSubject,
    Stream,
    Subject,
    TeachingAssignment,
    Term,
    TimetableSlot,
    User,
)
from app.models.enums import EnrolmentStatus, RoomType, StaffStatus
from app.schemas.timetable import (
    AssignmentItem,
    AssignmentOut,
    CheckOut,
    Conflict,
    FreePeriod,
    GenerateIn,
    GenerateOut,
    Problem,
    SlotCheckIn,
    SlotIn,
    SlotUpdate,
    Unplaced,
)
from app.services import crud
from app.services.people import now

# Default bell schedule (Monday–Friday, 40-minute periods, tea break 10:40–11:00, lunch 13:00–14:00).
# VERIFY with each school; manual slots may use any times.
PERIODS = [
    (time(8, 0), time(8, 40)),
    (time(8, 40), time(9, 20)),
    (time(9, 20), time(10, 0)),
    (time(10, 0), time(10, 40)),
    (time(11, 0), time(11, 40)),
    (time(11, 40), time(12, 20)),
    (time(12, 20), time(13, 0)),
    (time(14, 0), time(14, 40)),
    (time(14, 40), time(15, 20)),
]
SCHOOL_DAYS = (1, 2, 3, 4, 5)
PERIOD_MINUTES = 40


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def periods_of(start: time, end: time) -> int:
    return max(1, round((_minutes(end) - _minutes(start)) / PERIOD_MINUTES))


def _overlaps(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    return a_start < b_end and b_start < a_end


async def _term(session: AsyncSession, term_id: uuid.UUID) -> Term:
    return await crud.get_live(session, Term, term_id)


async def enrolled_counts(session: AsyncSession, year_id: uuid.UUID, stream_ids) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(Enrolment.stream_id, func.count())
        .where(
            Enrolment.academic_year_id == year_id,
            Enrolment.stream_id.in_(list(stream_ids)),
            Enrolment.status == EnrolmentStatus.ACTIVE,
        )
        .group_by(Enrolment.stream_id)
    )
    return dict(rows.all())


# ---------------------------------------------------------------- teaching assignments


async def list_assignments(
    session: AsyncSession,
    year_id: uuid.UUID,
    stream_id: uuid.UUID | None,
    staff_id: uuid.UUID | None,
    user_id: uuid.UUID | None = None,
) -> list[AssignmentOut]:
    stmt = (
        select(TeachingAssignment, Subject.code, User.first_name, User.last_name)
        .join(Subject, Subject.id == TeachingAssignment.subject_id)
        .join(Staff, Staff.id == TeachingAssignment.staff_id)
        .join(User, User.id == Staff.user_id)
        .where(TeachingAssignment.academic_year_id == year_id, TeachingAssignment.deleted_at.is_(None))
    )
    if stream_id:
        stmt = stmt.where(TeachingAssignment.stream_id == stream_id)
    if staff_id:
        stmt = stmt.where(TeachingAssignment.staff_id == staff_id)
    if user_id:
        stmt = stmt.where(Staff.user_id == user_id)
    rows = (await session.execute(stmt.order_by(TeachingAssignment.stream_id, Subject.code).limit(500))).all()
    return [
        AssignmentOut(
            id=a.id,
            academic_year_id=a.academic_year_id,
            stream_id=a.stream_id,
            subject_id=a.subject_id,
            subject_code=code,
            staff_id=a.staff_id,
            staff_name=f"{first} {last}",
        )
        for a, code, first, last in rows
    ]


async def replace_assignments(
    session: AsyncSession, principal: Principal, year_id: uuid.UUID, stream_id: uuid.UUID, items: list[AssignmentItem]
) -> list[AssignmentOut]:
    await crud.get_live(session, AcademicYear, year_id)
    await crud.get_live(session, Stream, stream_id)
    wanted = {i.subject_id: i.staff_id for i in items}
    if len(wanted) != len(items):
        raise AppError(422, "VALIDATION_ERROR", [{"field": "subject_id", "code": "duplicate_in_file"}])
    active = set(
        (
            await session.execute(
                select(Staff.id).where(
                    Staff.id.in_(list(wanted.values())), Staff.status == StaffStatus.ACTIVE, Staff.deleted_at.is_(None)
                )
            )
        ).scalars()
    )
    if set(wanted.values()) - active:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "staff_id", "code": "invalid_value"}])
    current = {
        a.subject_id: a
        for a in (
            await session.execute(
                select(TeachingAssignment)
                .where(
                    TeachingAssignment.academic_year_id == year_id,
                    TeachingAssignment.stream_id == stream_id,
                    TeachingAssignment.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalars()
    }
    for subject_id, assignment in current.items():
        if subject_id not in wanted:
            assignment.deleted_at = now()
        else:
            assignment.staff_id = wanted[subject_id]
    await session.flush()
    for subject_id, staff_id in wanted.items():
        if subject_id not in current:
            session.add(
                TeachingAssignment(
                    school_id=principal.school_id,
                    academic_year_id=year_id,
                    stream_id=stream_id,
                    subject_id=subject_id,
                    staff_id=staff_id,
                    created_by=principal.user_id,
                )
            )
    await session.commit()
    return await list_assignments(session, year_id, stream_id, None)


# ---------------------------------------------------------------- slots and checks


def _live_slots(term_id: uuid.UUID):
    return select(TimetableSlot).where(TimetableSlot.term_id == term_id, TimetableSlot.deleted_at.is_(None))


async def list_slots(session: AsyncSession, term_id: uuid.UUID, stream_id=None, staff_id=None, room_id=None) -> list:
    stmt = _live_slots(term_id)
    for column, value in (
        (TimetableSlot.stream_id, stream_id),
        (TimetableSlot.staff_id, staff_id),
        (TimetableSlot.room_id, room_id),
    ):
        if value:
            stmt = stmt.where(column == value)
    return list(
        (
            await session.execute(
                stmt.order_by(TimetableSlot.day_of_week, TimetableSlot.time_start, TimetableSlot.id).limit(500)
            )
        ).scalars()
    )


async def conflicts(session: AsyncSession, slot: SlotIn, exclude: uuid.UUID | None) -> list[Conflict]:
    stmt = _live_slots(slot.term_id).where(
        TimetableSlot.day_of_week == slot.day_of_week,
        TimetableSlot.time_start < slot.time_end,
        TimetableSlot.time_end > slot.time_start,
        or_(
            TimetableSlot.staff_id == slot.staff_id,
            TimetableSlot.room_id == slot.room_id,
            TimetableSlot.stream_id == slot.stream_id,
        ),
    )
    if exclude:
        stmt = stmt.where(TimetableSlot.id != exclude)
    out = []
    for other in (await session.execute(stmt)).scalars():
        for kind, mine, theirs in (
            ("teacher", slot.staff_id, other.staff_id),
            ("room", slot.room_id, other.room_id),
            ("stream", slot.stream_id, other.stream_id),
        ):
            if mine == theirs:
                out.append(
                    Conflict(
                        kind=kind,
                        slot_id=other.id,
                        stream_id=other.stream_id,
                        subject_id=other.subject_id,
                        time_start=other.time_start,
                        time_end=other.time_end,
                    )
                )
    return out


async def teacher_load(
    session: AsyncSession, term_id: uuid.UUID, staff_id: uuid.UUID, exclude: uuid.UUID | None = None
) -> int:
    stmt = _live_slots(term_id).where(TimetableSlot.staff_id == staff_id)
    if exclude:
        stmt = stmt.where(TimetableSlot.id != exclude)
    return sum(periods_of(s.time_start, s.time_end) for s in (await session.execute(stmt)).scalars())


async def _in_curriculum(session: AsyncSession, school_class: SchoolClass, subject_id: uuid.UUID) -> bool:
    in_class = (
        await session.execute(
            select(ClassSubject.id).where(
                ClassSubject.class_id == school_class.id,
                ClassSubject.subject_id == subject_id,
                ClassSubject.deleted_at.is_(None),
            )
        )
    ).first()
    in_combination = (
        await session.execute(
            select(CombinationSubject.id)
            .join(Combination, Combination.id == CombinationSubject.combination_id)
            .where(
                Combination.education_level_id == school_class.education_level_id,
                Combination.deleted_at.is_(None),
                CombinationSubject.subject_id == subject_id,
                CombinationSubject.deleted_at.is_(None),
            )
        )
    ).first()
    return bool(in_class or in_combination)


async def problems(session: AsyncSession, slot: SlotIn, exclude: uuid.UUID | None) -> list[Problem]:
    term = await _term(session, slot.term_id)
    stream = await crud.get_live(session, Stream, slot.stream_id)
    subject = await crud.get_live(session, Subject, slot.subject_id)
    room = await crud.get_live(session, Room, slot.room_id)
    staff = await crud.get_live(session, Staff, slot.staff_id)
    school_class = await crud.get_live(session, SchoolClass, stream.class_id)
    found: list[Problem] = []
    assigned = (
        await session.execute(
            select(TeachingAssignment.staff_id).where(
                TeachingAssignment.academic_year_id == term.academic_year_id,
                TeachingAssignment.stream_id == stream.id,
                TeachingAssignment.subject_id == subject.id,
                TeachingAssignment.deleted_at.is_(None),
            )
        )
    ).scalar()
    if assigned != staff.id:
        found.append(
            Problem(
                code="not_assigned",
                detail="No teaching assignment for this teacher, stream and subject"
                if assigned is None
                else "The subject is assigned to another teacher in this stream",
            )
        )
    qualified = (
        await session.execute(
            select(StaffSubject.id).where(
                StaffSubject.staff_id == staff.id,
                StaffSubject.subject_id == subject.id,
                StaffSubject.deleted_at.is_(None),
            )
        )
    ).first()
    if not qualified:
        found.append(Problem(code="not_qualified", detail=f"This teacher is not qualified to teach {subject.code}"))
    if staff.status != StaffStatus.ACTIVE:
        found.append(Problem(code="teacher_inactive", detail=f"Teacher status is {staff.status}"))
    if not await _in_curriculum(session, school_class, subject.id):
        found.append(Problem(code="not_in_curriculum", detail=f"{subject.code} is not taught in {school_class.code}"))
    if room.room_type != subject.room_type:
        found.append(
            Problem(
                code="room_type",
                detail=f"{subject.code} needs a {subject.room_type}, {room.code} is a {room.room_type}",
            )
        )
    enrolled = (await enrolled_counts(session, term.academic_year_id, [stream.id])).get(stream.id, 0)
    if enrolled > room.capacity:
        found.append(Problem(code="room_capacity", detail=f"{enrolled} students, {room.code} seats {room.capacity}"))
    load = await teacher_load(session, term.id, staff.id, exclude) + periods_of(slot.time_start, slot.time_end)
    if load > staff.max_periods_per_week:
        found.append(Problem(code="teacher_load", detail=f"{load} periods > maximum {staff.max_periods_per_week}"))
    return found


async def free_periods(session: AsyncSession, slot: SlotIn, exclude: uuid.UUID | None) -> list[FreePeriod]:
    stmt = _live_slots(slot.term_id).where(
        TimetableSlot.day_of_week == slot.day_of_week,
        or_(
            TimetableSlot.staff_id == slot.staff_id,
            TimetableSlot.room_id == slot.room_id,
            TimetableSlot.stream_id == slot.stream_id,
        ),
    )
    if exclude:
        stmt = stmt.where(TimetableSlot.id != exclude)
    busy = [(s.time_start, s.time_end) for s in (await session.execute(stmt)).scalars()]
    return [FreePeriod(time_start=a, time_end=b) for a, b in PERIODS if not any(_overlaps(a, b, s, e) for s, e in busy)]


async def check(session: AsyncSession, body: SlotCheckIn) -> CheckOut:
    slot = SlotIn.model_validate(body.model_dump(exclude={"exclude_slot_id"}))
    found_conflicts = await conflicts(session, slot, body.exclude_slot_id)
    found_problems = await problems(session, slot, body.exclude_slot_id)
    return CheckOut(
        ok=not found_conflicts and not found_problems,
        conflicts=found_conflicts,
        problems=found_problems,
        free_periods=await free_periods(session, slot, body.exclude_slot_id),
    )


async def _insert_or_clash(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23P01":  # someone saved a clashing slot meanwhile
            raise AppError(409, "TIMETABLE_CLASH") from None
        raise


async def _guard(session: AsyncSession, slot: SlotIn, exclude: uuid.UUID | None) -> None:
    found = await conflicts(session, slot, exclude)
    if found:
        raise AppError(409, "TIMETABLE_CLASH", [c.model_dump(mode="json") for c in found])
    issues = await problems(session, slot, exclude)
    if issues:
        raise AppError(422, "RULE_VIOLATION", [p.model_dump() for p in issues], detail=issues[0].detail)


async def create_slot(session: AsyncSession, principal: Principal, body: SlotIn) -> TimetableSlot:
    await _guard(session, body, None)
    slot = TimetableSlot(school_id=principal.school_id, created_by=principal.user_id, **body.model_dump())
    session.add(slot)
    await _insert_or_clash(session)
    await session.commit()
    return slot


async def update_slot(session: AsyncSession, slot_id: uuid.UUID, body: SlotUpdate) -> TimetableSlot:
    slot = await crud.get_live(session, TimetableSlot, slot_id, lock=True)
    merged = SlotIn.model_validate(
        {**{f: getattr(slot, f) for f in SlotIn.model_fields}, **body.model_dump(exclude_unset=True)}
    )
    await _guard(session, merged, slot.id)
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(slot, name, value)
    await _insert_or_clash(session)
    await session.commit()
    return slot


# ---------------------------------------------------------------- generator


@dataclass
class _Lesson:
    stream_id: uuid.UUID
    subject_id: uuid.UUID
    staff_id: uuid.UUID
    rooms: list[uuid.UUID]
    per_week: int


@dataclass
class _Grid:
    """Busy periods per teacher, room and stream: key -> {(day, period index)}; placed lessons by position."""

    teacher: dict = field(default_factory=lambda: defaultdict(set))
    room: dict = field(default_factory=lambda: defaultdict(set))
    stream: dict = field(default_factory=lambda: defaultdict(set))
    load: dict = field(default_factory=lambda: defaultdict(int))
    subject_days: dict = field(default_factory=lambda: defaultdict(int))
    placed: dict = field(default_factory=dict)  # (stream, day, period) -> (lesson, room)

    def mark(self, lesson: _Lesson, room: uuid.UUID, day: int, period: int, add: bool = True) -> None:
        op = set.add if add else set.discard
        op(self.teacher[lesson.staff_id], (day, period))
        op(self.room[room], (day, period))
        op(self.stream[lesson.stream_id], (day, period))
        self.load[lesson.staff_id] += 1 if add else -1
        self.subject_days[(lesson.stream_id, lesson.subject_id, day)] += 1 if add else -1
        if add:
            self.placed[(lesson.stream_id, day, period)] = (lesson, room)
        else:
            self.placed.pop((lesson.stream_id, day, period), None)


def _period_index(start: time, end: time) -> list[int]:
    return [i for i, (a, b) in enumerate(PERIODS) if _overlaps(a, b, start, end)]


def _room_for(grid: _Grid, lesson: _Lesson, day: int, period: int) -> uuid.UUID | None:
    return next((r for r in lesson.rooms if (day, period) not in grid.room[r]), None)


def _fits(grid: _Grid, lesson: _Lesson, day: int, period: int, max_load: dict, ignore_stream: bool = False):
    if (day, period) in grid.teacher[lesson.staff_id] or grid.load[lesson.staff_id] >= max_load[lesson.staff_id]:
        return None
    if not ignore_stream and (day, period) in grid.stream[lesson.stream_id]:
        return None
    return _room_for(grid, lesson, day, period)


def _candidates(grid: _Grid, lesson: _Lesson):
    """Spread a subject over the week: days where it is not taught yet come first, mornings before afternoons."""
    cells = [(d, p) for d in SCHOOL_DAYS for p in range(len(PERIODS))]
    return sorted(cells, key=lambda c: (grid.subject_days[(lesson.stream_id, lesson.subject_id, c[0])], c[1], c[0]))


def _place(grid: _Grid, lesson: _Lesson, max_load: dict, movable: set) -> bool:
    for day, period in _candidates(grid, lesson):
        room = _fits(grid, lesson, day, period, max_load)
        if room:
            grid.mark(lesson, room, day, period)
            movable.add((lesson.stream_id, day, period))
            return True
    # one-step repair: free a cell of this stream by moving a lesson placed in this run elsewhere
    for day, period in _candidates(grid, lesson):
        if not _fits(grid, lesson, day, period, max_load, ignore_stream=True):
            continue
        key = (lesson.stream_id, day, period)
        if key not in movable or key not in grid.placed:
            continue
        other, other_room = grid.placed[key]
        grid.mark(other, other_room, day, period, add=False)
        for d2, p2 in _candidates(grid, other):
            if (d2, p2) == (day, period):
                continue
            room2 = _fits(grid, other, d2, p2, max_load)
            if room2:
                grid.mark(other, room2, d2, p2)
                movable.discard(key)
                movable.add((other.stream_id, d2, p2))
                room = _fits(grid, lesson, day, period, max_load)
                if room:
                    grid.mark(lesson, room, day, period)
                    movable.add(key)
                    return True
                break
        else:
            grid.mark(other, other_room, day, period)  # could not move it: put it back
    return False


async def generate(session: AsyncSession, principal: Principal, body: GenerateIn) -> GenerateOut:
    """Most-constrained-first greedy placement with one-step repair. persist=False returns a draft."""
    term = await _term(session, body.term_id)
    streams = (
        (await session.execute(select(Stream).where(Stream.id.in_(body.stream_ids), Stream.deleted_at.is_(None))))
        .scalars()
        .all()
    )
    if len(streams) != len(set(body.stream_ids)):
        raise not_found()
    selected = {s.id for s in streams}
    existing = list((await session.execute(_live_slots(term.id))).scalars())
    kept = [s for s in existing if not (body.replace and s.stream_id in selected)]

    grid = _Grid()
    already: dict[tuple, int] = defaultdict(int)
    for s in kept:
        for p in _period_index(s.time_start, s.time_end):
            grid.teacher[s.staff_id].add((s.day_of_week, p))
            grid.room[s.room_id].add((s.day_of_week, p))
            grid.stream[s.stream_id].add((s.day_of_week, p))
        grid.load[s.staff_id] += periods_of(s.time_start, s.time_end)
        already[(s.stream_id, s.subject_id)] += periods_of(s.time_start, s.time_end)
        grid.subject_days[(s.stream_id, s.subject_id, s.day_of_week)] += 1

    enrolled = await enrolled_counts(session, term.academic_year_id, selected)
    rooms = (
        (await session.execute(select(Room).where(Room.deleted_at.is_(None)).order_by(Room.capacity))).scalars().all()
    )
    subjects = {s.id: s for s in (await session.execute(select(Subject).where(Subject.deleted_at.is_(None)))).scalars()}
    assignments = {
        (a.stream_id, a.subject_id): a.staff_id
        for a in (
            await session.execute(
                select(TeachingAssignment).where(
                    TeachingAssignment.academic_year_id == term.academic_year_id,
                    TeachingAssignment.stream_id.in_(selected),
                    TeachingAssignment.deleted_at.is_(None),
                )
            )
        ).scalars()
    }
    max_load = dict((await session.execute(select(Staff.id, Staff.max_periods_per_week))).all())
    qualified_rows = select(StaffSubject.staff_id, StaffSubject.subject_id).where(StaffSubject.deleted_at.is_(None))
    qualified = {tuple(row) for row in (await session.execute(qualified_rows)).all()}

    lessons, unplaced = [], []
    for stream in streams:
        curriculum = (
            (
                await session.execute(
                    select(ClassSubject).where(
                        ClassSubject.class_id == stream.class_id, ClassSubject.deleted_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        size = enrolled.get(stream.id, 0)
        for cs in curriculum:
            needed = cs.periods_per_week - already[(stream.id, cs.subject_id)]
            if needed <= 0:
                continue
            staff_id = assignments.get((stream.id, cs.subject_id))
            if staff_id is None:
                unplaced.append(
                    Unplaced(stream_id=stream.id, subject_id=cs.subject_id, periods=needed, reason="not_assigned")
                )
                continue
            if (staff_id, cs.subject_id) not in qualified:
                unplaced.append(
                    Unplaced(stream_id=stream.id, subject_id=cs.subject_id, periods=needed, reason="not_qualified")
                )
                continue
            kind = subjects[cs.subject_id].room_type
            fit = [r.id for r in rooms if r.room_type == kind and r.capacity >= size]
            if kind == RoomType.CLASSROOM and stream.home_room_id in fit:
                fit.remove(stream.home_room_id)
                fit.insert(0, stream.home_room_id)
            if not fit:
                unplaced.append(
                    Unplaced(stream_id=stream.id, subject_id=cs.subject_id, periods=needed, reason="no_room")
                )
                continue
            lessons.append(_Lesson(stream.id, cs.subject_id, staff_id, fit, needed))

    teacher_demand: dict[uuid.UUID, int] = defaultdict(int)
    for lesson in lessons:
        teacher_demand[lesson.staff_id] += lesson.per_week
    lessons.sort(key=lambda le: (len(le.rooms), -teacher_demand[le.staff_id], -le.per_week))  # most constrained first

    movable: set = set()
    missed: dict[tuple, int] = defaultdict(int)
    for lesson in lessons:
        for _ in range(lesson.per_week):
            if not _place(grid, lesson, max_load, movable):
                missed[(lesson.stream_id, lesson.subject_id)] += 1
    unplaced += [
        Unplaced(stream_id=s, subject_id=sub, periods=n, reason="no_free_period") for (s, sub), n in missed.items()
    ]

    placed = [
        SlotIn(
            term_id=term.id,
            stream_id=lesson.stream_id,
            subject_id=lesson.subject_id,
            staff_id=lesson.staff_id,
            room_id=room,
            day_of_week=day,
            time_start=PERIODS[p][0],
            time_end=PERIODS[p][1],
        )
        for (stream_id, day, p), (lesson, room) in sorted(
            grid.placed.items(), key=lambda i: (str(i[0][0]), i[0][1], i[0][2])
        )
        if (stream_id, day, p) in movable
    ]
    if body.persist:
        if body.replace:
            await session.execute(
                update(TimetableSlot)
                .where(
                    TimetableSlot.term_id == term.id,
                    TimetableSlot.stream_id.in_(selected),
                    TimetableSlot.deleted_at.is_(None),
                )
                .values(deleted_at=now())
            )
            await session.flush()
        session.add_all(
            [
                TimetableSlot(school_id=principal.school_id, created_by=principal.user_id, **s.model_dump())
                for s in placed
            ]
        )
        await _insert_or_clash(session)
        await session.commit()
    return GenerateOut(placed=placed, unplaced=unplaced, persisted=body.persist)


def etag_of(slots: list[TimetableSlot]) -> str:
    digest = hashlib.sha256(
        "|".join(f"{s.id}:{s.updated_at.isoformat() if s.updated_at else ''}" for s in slots).encode()
    ).hexdigest()[:32]
    return f'W/"{digest}"'
