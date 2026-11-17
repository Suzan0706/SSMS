"""UC-05 Schedule Classes."""
from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.core.i18n import DAY_NAMES
from app.deps import CurrentUser, DbSession, require_roles
from app.models import Instructor, Schedule, User
from app.models.enums import Role
from app.schemas.schedules import (CheckResult, ConflictOut, DraftLesson, GenerateIn, GenerateOut, ScheduleIn,
                                   ScheduleOut)
from app.services import notify
from app.services import scheduling as svc

router = APIRouter(prefix="/schedules", tags=["Schedules"])
Admin = Depends(require_roles(Role.ADMIN))


@router.post("/check", response_model=CheckResult, dependencies=[Admin])
def check(body: ScheduleIn, db: DbSession):
    """Dry run used by the timetable grid while the admin fills the form."""
    candidate = svc.ScheduleCandidate(**body.model_dump())
    conflicts = svc.find_conflicts(db, candidate)
    problems = svc.check_rules(db, candidate)
    return CheckResult(ok=not conflicts and not problems,
                       conflicts=[ConflictOut(**vars(c)) for c in conflicts], problems=problems)


@router.post("", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
def create(body: ScheduleIn, db: DbSession, user: User = Admin):
    """201 created · 409 clash (with the conflicting sessions) · 422 rule broken."""
    schedule = svc.create_schedule(db, svc.ScheduleCandidate(**body.model_dump()), user)
    db.commit()
    instructor = db.get(Instructor, schedule.instructor_id)
    lang = instructor.user.preferred_language
    notify.sms_user(instructor.user, "new_class_session", subject=schedule.subject.name_en,
                    day=DAY_NAMES[lang][schedule.day_of_week], start=schedule.time_start.strftime("%H:%M"),
                    end=schedule.time_end.strftime("%H:%M"), room=schedule.room.room_code)
    return schedule


@router.get("", response_model=list[ScheduleOut])
def list_schedules(db: DbSession, user: CurrentUser, term_id: int, offering_id: int | None = None,
                   stream: str | None = None, instructor_id: int | None = None, room_id: int | None = None):
    stmt = select(Schedule).where(Schedule.term_id == term_id)
    for column, value in ((Schedule.offering_id, offering_id), (Schedule.stream, stream),
                          (Schedule.instructor_id, instructor_id), (Schedule.room_id, room_id)):
        if value is not None:
            stmt = stmt.where(column == value)
    return db.scalars(stmt.order_by(Schedule.day_of_week, Schedule.time_start)).all()


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Admin])
def delete(schedule_id: int, db: DbSession):
    svc.delete_schedule(db, schedule_id)
    db.commit()


@router.post("/generate", response_model=GenerateOut)
def generate(body: GenerateIn, db: DbSession, user: User = Admin):
    """schedulingAlgo: draft (persist=false) or save the whole term timetable in one transaction."""
    result = svc.generate_for_term(db, body.term_id, body.offering_ids, body.streams, body.persist, user)
    if body.persist:
        db.commit()
    periods = result.periods

    def lesson(b, pl=None) -> DraftLesson:
        return DraftLesson(
            offering_id=b.offering_id, stream=b.stream, subject_id=b.subject_id, instructor_id=b.instructor_id,
            room_id=pl.room_id if pl else None, day_of_week=pl.day if pl else None,
            time_start=periods[pl.first].start if pl else None,
            time_end=periods[pl.first + b.length - 1].end if pl else None)

    return GenerateOut(placed=[lesson(p.block, p) for p in result.placed],
                       unplaced=[lesson(b) for b in result.unplaced], persisted=result.persisted)
