"""UC-05 Schedule Classes: clash detection, placement rules and timetable generation (schedulingAlgo).

Layer 1 of 3: friendly checks here. Layer 2: EXCLUDE constraints on `schedules`.
Layer 3: trigger fn_enrolment_schedules_no_clash on `enrolment_schedules`.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.models import (CourseOffering, CourseSubject, Department, Enrolment, EnrolmentSchedule, Instructor,
                        InstructorSubject, Room, Schedule, Subject, Term, User)
from app.models.enums import EnrolmentStatus, RoomType


# ---------------------------------------------------------------------------
# Single placement: conflicts and rules
# ---------------------------------------------------------------------------
@dataclass
class ScheduleCandidate:
    offering_id: int
    stream: str
    term_id: int
    subject_id: int
    instructor_id: int
    room_id: int
    day_of_week: int
    time_start: time
    time_end: time


@dataclass
class Conflict:
    kind: str            # INSTRUCTOR | ROOM | CLASS | STUDENT
    schedule_id: int
    message: str


def find_conflicts(db: Session, c: ScheduleCandidate, exclude_id: int | None = None) -> list[Conflict]:
    """Every existing session that would clash with candidate c."""
    overlap = and_(
        Schedule.term_id == c.term_id,
        Schedule.day_of_week == c.day_of_week,
        Schedule.time_start < c.time_end,      # half-open [start, end)
        c.time_start < Schedule.time_end,
    )
    if exclude_id is not None:
        overlap = and_(overlap, Schedule.schedule_id != exclude_id)

    conflicts: list[Conflict] = []
    rows = db.scalars(select(Schedule).where(overlap, or_(
        Schedule.instructor_id == c.instructor_id,
        Schedule.room_id == c.room_id,
        and_(Schedule.offering_id == c.offering_id, Schedule.stream == c.stream),
    ))).all()
    for s in rows:
        if s.instructor_id == c.instructor_id:
            conflicts.append(Conflict("INSTRUCTOR", s.schedule_id, "Instructor already teaching"))
        if s.room_id == c.room_id:
            conflicts.append(Conflict("ROOM", s.schedule_id, "Room already in use"))
        if (s.offering_id, s.stream) == (c.offering_id, c.stream):
            conflicts.append(Conflict("CLASS", s.schedule_id, "Class already has a lesson"))

    # Students of this stream who are also linked to other overlapping sessions
    students_here = (
        select(Enrolment.enrolment_id)
        .where(Enrolment.offering_id == c.offering_id, Enrolment.stream == c.stream,
               Enrolment.status == EnrolmentStatus.CONFIRMED)
    )
    student_clashes = db.scalars(
        select(Schedule.schedule_id).distinct()
        .join(EnrolmentSchedule, EnrolmentSchedule.schedule_id == Schedule.schedule_id)
        .where(overlap, EnrolmentSchedule.enrolment_id.in_(students_here),
               or_(Schedule.offering_id != c.offering_id, Schedule.stream != c.stream))
    ).all()
    conflicts += [Conflict("STUDENT", sid, "Students already in another class") for sid in student_clashes]
    return conflicts


def periods_of(start: time, end: time) -> int:
    minutes = (datetime.combine(datetime.min, end) - datetime.combine(datetime.min, start)).seconds // 60
    return math.ceil(minutes / get_settings().period_minutes)


def room_fits(room_type: RoomType, required: RoomType) -> bool:
    if required == RoomType.CLASSROOM:
        return room_type in (RoomType.CLASSROOM, RoomType.HALL)
    return room_type == required


def class_size(db: Session, offering_id: int, stream: str) -> int:
    return db.scalar(select(func.count()).select_from(Enrolment).where(
        Enrolment.offering_id == offering_id, Enrolment.stream == stream,
        Enrolment.status == EnrolmentStatus.CONFIRMED)) or 0


def instructor_load(db: Session, instructor_id: int, term_id: int, exclude_id: int | None = None) -> int:
    stmt = select(Schedule.time_start, Schedule.time_end).where(
        Schedule.instructor_id == instructor_id, Schedule.term_id == term_id)
    if exclude_id is not None:
        stmt = stmt.where(Schedule.schedule_id != exclude_id)
    return sum(periods_of(s, e) for s, e in db.execute(stmt).all())


def check_rules(db: Session, c: ScheduleCandidate) -> list[str]:
    """Hard rules other than clashes. Returns human-readable problems (empty = OK)."""
    offering = db.get(CourseOffering, c.offering_id)
    term = db.get(Term, c.term_id)
    subject = db.get(Subject, c.subject_id)
    instructor = db.get(Instructor, c.instructor_id)
    room = db.get(Room, c.room_id)
    missing = [name for name, obj in (("offering", offering), ("term", term), ("subject", subject),
                                      ("instructor", instructor), ("room", room)) if obj is None]
    if missing:
        return [f"Unknown {', '.join(missing)}"]

    problems: list[str] = []
    if term.academic_year_id != offering.academic_year_id:
        problems.append("Term is not in the offering's academic year")
    if db.get(CourseSubject, (offering.course_id, offering.level_id, c.subject_id)) is None:
        problems.append("Subject is not part of this course at this level")
    if db.get(InstructorSubject, (c.instructor_id, c.subject_id)) is None:
        problems.append("Instructor is not qualified for this subject")
    if instructor.employment_status != "ACTIVE":
        problems.append("Instructor is not active")
    if not room.is_active:
        problems.append("Room is not available")
    if not room_fits(room.room_type, subject.room_type_required):
        problems.append(f"{subject.name_en} needs a {subject.room_type_required.value} room")
    size = class_size(db, c.offering_id, c.stream)
    if size > room.capacity:
        problems.append(f"Room holds {room.capacity} but the class has {size} students")
    load = instructor_load(db, c.instructor_id, c.term_id) + periods_of(c.time_start, c.time_end)
    if load > instructor.max_periods_per_week:
        problems.append(f"Instructor load would be {load} periods (max {instructor.max_periods_per_week})")
    return problems


def link_stream_students(db: Session, schedule: Schedule) -> int:
    """Link every CONFIRMED student of the session's stream (student-clash trigger re-checks)."""
    enrolment_ids = db.scalars(select(Enrolment.enrolment_id).where(
        Enrolment.offering_id == schedule.offering_id, Enrolment.stream == schedule.stream,
        Enrolment.status == EnrolmentStatus.CONFIRMED)).all()
    for eid in enrolment_ids:
        db.add(EnrolmentSchedule(enrolment_id=eid, schedule_id=schedule.schedule_id))
    db.flush()
    return len(enrolment_ids)


def create_schedule(db: Session, c: ScheduleCandidate, actor: User) -> Schedule:
    problems = check_rules(db, c)
    if problems:
        raise AppError(422, "SCHEDULE_RULE", "The session breaks a scheduling rule",
                       "Kipindi kinavunja kanuni ya ratiba", {"problems": problems})
    conflicts = find_conflicts(db, c)
    if conflicts:
        raise AppError(409, "CLASH", "This session clashes with existing sessions",
                       "Kipindi hiki kinagongana na vipindi vilivyopo",
                       {"conflicts": [vars(x) for x in conflicts]})
    schedule = Schedule(**vars(c), created_by=actor.user_id)
    db.add(schedule)
    db.flush()                       # EXCLUDE constraints fire here under concurrency
    link_stream_students(db, schedule)
    return schedule


def delete_schedule(db: Session, schedule_id: int) -> None:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise not_found("Schedule")
    # Fails with 409 (FK from attendance) once attendance has been taken for the session.
    db.execute(delete(EnrolmentSchedule).where(EnrolmentSchedule.schedule_id == schedule_id))
    db.delete(schedule)
    db.flush()


# ---------------------------------------------------------------------------
# schedulingAlgo: whole-term generation (pure functions, no database)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Period:
    start: time
    end: time


# 40-minute periods, break 10:00-10:20, lunch 12:20-13:00
DEFAULT_PERIODS = [
    Period(time(8, 0), time(8, 40)), Period(time(8, 40), time(9, 20)), Period(time(9, 20), time(10, 0)),
    Period(time(10, 20), time(11, 0)), Period(time(11, 0), time(11, 40)), Period(time(11, 40), time(12, 20)),
    Period(time(13, 0), time(13, 40)), Period(time(13, 40), time(14, 20)),
]
SCHOOL_DAYS = (1, 2, 3, 4, 5)


@dataclass(eq=False)
class Block:
    """`length` consecutive periods of one subject for one class stream."""
    offering_id: int
    stream: str
    subject_id: int
    instructor_id: int | None
    length: int
    room_type: RoomType
    class_size: int
    morning: bool = False            # prefer early periods (Mathematics, sciences)

    @property
    def class_key(self) -> tuple[int, str]:
        return (self.offering_id, self.stream)


@dataclass(frozen=True)
class RoomInfo:
    room_id: int
    room_type: RoomType
    capacity: int


@dataclass(eq=False)
class Placement:
    block: Block
    day: int
    first: int                        # index into the period list
    room_id: int


@dataclass
class Occupancy:
    """(kind, key, day, period) -> owner. Owner None = an existing session that cannot move."""
    owners: dict[tuple, Placement | None] = field(default_factory=dict)

    @staticmethod
    def keys(block: Block, day: int, first: int, room_id: int) -> list[tuple]:
        out = []
        for p in range(first, first + block.length):
            out += [("I", block.instructor_id, day, p), ("R", room_id, day, p), ("C", block.class_key, day, p)]
        return out

    def blockers(self, block: Block, day: int, first: int, room_id: int) -> set:
        return {id(o) if o else None for k in self.keys(block, day, first, room_id)
                if k in self.owners for o in [self.owners[k]]}

    def is_free(self, block: Block, day: int, first: int, room_id: int) -> bool:
        return not any(k in self.owners for k in self.keys(block, day, first, room_id))

    def take(self, pl: Placement | None, block: Block, day: int, first: int, room_id: int) -> None:
        for k in self.keys(block, day, first, room_id):
            self.owners[k] = pl

    def free(self, pl: Placement) -> None:
        for k in self.keys(pl.block, pl.day, pl.first, pl.room_id):
            self.owners.pop(k, None)


def block_starts(periods: list[Period], length: int) -> list[int]:
    """Start indexes where `length` periods run back-to-back (a double never spans a break)."""
    return [i for i in range(len(periods) - length + 1)
            if all(periods[j].end == periods[j + 1].start for j in range(i, i + length - 1))]


def suitable_rooms(block: Block, rooms: list[RoomInfo]) -> list[RoomInfo]:
    fits = [r for r in rooms if room_fits(r.room_type, block.room_type) and r.capacity >= block.class_size]
    return sorted(fits, key=lambda r: r.capacity)         # best fit first


def generate_timetable(
    blocks: list[Block],
    rooms: list[RoomInfo],
    periods: list[Period] = DEFAULT_PERIODS,
    days: tuple[int, ...] = SCHOOL_DAYS,
    occupancy: Occupancy | None = None,
) -> tuple[list[Placement], list[Block]]:
    """Most-constrained-first greedy placement with a depth-1 repair step.

    Hard constraints (never broken): instructor, room and class free; room type and capacity.
    Soft constraints (penalty): one block of a subject per class per day; morning for `morning` subjects;
    spread a class's lessons evenly over the week.
    """
    occ = occupancy or Occupancy()
    placed: list[Placement] = []
    unplaced: list[Block] = []
    subject_days: dict[tuple, set[int]] = defaultdict(set)
    lessons_per_day: dict[tuple, int] = defaultdict(int)
    room_options = {id(b): suitable_rooms(b, rooms) for b in blocks}
    instructor_demand: dict[int | None, int] = defaultdict(int)
    for b in blocks:
        instructor_demand[b.instructor_id] += b.length

    def penalty(b: Block, day: int, first: int) -> float:
        p = 10.0 if day in subject_days[(b.class_key, b.subject_id)] else 0.0
        p += first * (1.0 if b.morning else 0.1)
        p += lessons_per_day[(b.class_key, day)] * 0.5
        return p

    def candidates(b: Block) -> list[tuple[float, int, int, int]]:
        found = []
        for day in days:
            for first in block_starts(periods, b.length):
                for r in room_options[id(b)]:
                    if occ.is_free(b, day, first, r.room_id):
                        found.append((penalty(b, day, first), day, first, r.room_id))
                        break                               # best-fit room for this cell
        return sorted(found)

    def put(b: Block, day: int, first: int, room_id: int) -> Placement:
        pl = Placement(b, day, first, room_id)
        occ.take(pl, b, day, first, room_id)
        subject_days[(b.class_key, b.subject_id)].add(day)
        lessons_per_day[(b.class_key, day)] += b.length
        placed.append(pl)
        return pl

    def remove(pl: Placement) -> None:
        occ.free(pl)
        subject_days[(pl.block.class_key, pl.block.subject_id)].discard(pl.day)
        lessons_per_day[(pl.block.class_key, pl.day)] -= pl.block.length
        placed.remove(pl)

    def repair(b: Block) -> bool:
        """Move exactly one generator-placed block out of the way, if it can go elsewhere."""
        for day in days:
            for first in block_starts(periods, b.length):
                for r in room_options[id(b)]:
                    blockers = occ.blockers(b, day, first, r.room_id)
                    if len(blockers) != 1 or None in blockers:
                        continue
                    victim = {id(p): p for p in placed}[next(iter(blockers))]
                    remove(victim)
                    mine = put(b, day, first, r.room_id)
                    alternatives = candidates(victim.block)
                    if alternatives:
                        _, d, f, room = alternatives[0]
                        put(victim.block, d, f, room)
                        return True
                    remove(mine)
                    put(victim.block, victim.day, victim.first, victim.room_id)
        return False

    order = sorted(blocks, key=lambda b: (len(room_options[id(b)]), -b.length,
                                          -instructor_demand[b.instructor_id]))
    for b in order:
        if b.instructor_id is None or not room_options[id(b)]:
            unplaced.append(b)
            continue
        options = candidates(b)
        if options:
            _, day, first, room_id = options[0]
            put(b, day, first, room_id)
        elif not repair(b):
            unplaced.append(b)
    return placed, unplaced


def occupancy_from_sessions(sessions: list[Schedule], periods: list[Period]) -> Occupancy:
    """Existing sessions become immovable obstacles (owner None)."""
    occ = Occupancy()
    for s in sessions:
        for i, p in enumerate(periods):
            if s.time_start < p.end and p.start < s.time_end:
                occ.owners[("I", s.instructor_id, s.day_of_week, i)] = None
                occ.owners[("R", s.room_id, s.day_of_week, i)] = None
                occ.owners[("C", (s.offering_id, s.stream), s.day_of_week, i)] = None
    return occ


MORNING_DEPARTMENTS = {"MATH", "SCI"}


def build_blocks(db: Session, term: Term, offerings: list[CourseOffering], streams: list[str],
                 existing: list[Schedule]) -> list[Block]:
    """Demand for the term: periods_per_week minus periods already timetabled, split into blocks."""
    assigned_load: dict[int, int] = defaultdict(int)
    for s in existing:
        assigned_load[s.instructor_id] += periods_of(s.time_start, s.time_end)
    blocks: list[Block] = []
    for o in offerings:
        for stream in streams:
            size = class_size(db, o.offering_id, stream)
            for cs in db.scalars(select(CourseSubject).where(CourseSubject.course_id == o.course_id,
                                                             CourseSubject.level_id == o.level_id)).all():
                same = [s for s in existing if (s.offering_id, s.stream, s.subject_id)
                        == (o.offering_id, stream, cs.subject_id)]
                remaining = cs.periods_per_week - sum(periods_of(s.time_start, s.time_end) for s in same)
                if remaining <= 0:
                    continue
                instructor_id = same[0].instructor_id if same else None
                if instructor_id is None:
                    qualified = db.scalars(select(Instructor).join(
                        InstructorSubject, InstructorSubject.instructor_id == Instructor.instructor_id).where(
                        InstructorSubject.subject_id == cs.subject_id,
                        Instructor.employment_status == "ACTIVE")).all()
                    fitting = [i for i in qualified
                               if assigned_load[i.instructor_id] + remaining <= i.max_periods_per_week]
                    if fitting:
                        instructor_id = min(fitting, key=lambda i: assigned_load[i.instructor_id]).instructor_id
                if instructor_id is not None:
                    assigned_load[instructor_id] += remaining
                subject = cs.subject
                dept = db.get(Department, subject.department_id)
                lengths = []
                if subject.room_type_required == RoomType.LABORATORY:
                    lengths += [2] * (remaining // 2)
                    remaining %= 2
                lengths += [1] * remaining
                blocks += [Block(o.offering_id, stream, cs.subject_id, instructor_id, n,
                                 subject.room_type_required, size, morning=dept.code in MORNING_DEPARTMENTS)
                           for n in lengths]
    return blocks


@dataclass
class GenerationResult:
    placed: list[Placement]
    unplaced: list[Block]
    periods: list[Period]
    persisted: bool


def generate_for_term(db: Session, term_id: int, offering_ids: list[int], streams: list[str],
                      persist: bool, actor: User) -> GenerationResult:
    term = db.get(Term, term_id)
    if term is None:
        raise not_found("Term")
    offerings = list(db.scalars(select(CourseOffering).where(CourseOffering.offering_id.in_(offering_ids))).all())
    if any(o.academic_year_id != term.academic_year_id for o in offerings):
        raise AppError(422, "SCHEDULE_RULE", "All offerings must be in the term's academic year",
                       "Kozi zote ziwe katika mwaka wa masomo wa muhula huu")
    existing = list(db.scalars(select(Schedule).where(Schedule.term_id == term_id)).all())
    rooms = [RoomInfo(r.room_id, r.room_type, r.capacity)
             for r in db.scalars(select(Room).where(Room.is_active)).all()]
    periods = DEFAULT_PERIODS
    blocks = build_blocks(db, term, offerings, streams, existing)
    placed, unplaced = generate_timetable(blocks, rooms, periods, SCHOOL_DAYS,
                                          occupancy_from_sessions(existing, periods))
    if persist:
        for pl in placed:
            b = pl.block
            schedule = Schedule(offering_id=b.offering_id, stream=b.stream, term_id=term_id,
                                subject_id=b.subject_id, instructor_id=b.instructor_id, room_id=pl.room_id,
                                day_of_week=pl.day, time_start=periods[pl.first].start,
                                time_end=periods[pl.first + b.length - 1].end, created_by=actor.user_id)
            db.add(schedule)
            db.flush()
            link_stream_students(db, schedule)
    return GenerationResult(placed, unplaced, periods, persist)
