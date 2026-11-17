"""UC-04 Manage Instructors' Info & Designation."""
from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.core.errors import forbidden, not_found
from app.core.security import generate_temporary_password, hash_password
from app.deps import CurrentUser, DbSession, require_roles
from app.models import Instructor, InstructorDesignation, InstructorSubject, Schedule, User
from app.models.enums import STAFF_ROLES, Role
from app.schemas.instructors import (DesignationAssign, DesignationOut, InstructorCreate, InstructorCreated,
                                     InstructorOut, InstructorUpdate)
from app.schemas.schedules import ScheduleOut
from app.services import notify

router = APIRouter(prefix="/instructors", tags=["Instructors"])
AdminOnly = [Depends(require_roles(Role.ADMIN))]


def _get(db, instructor_id: int) -> Instructor:
    instructor = db.get(Instructor, instructor_id)
    if instructor is None:
        raise not_found("Instructor")
    return instructor


@router.post("", response_model=InstructorCreated, status_code=status.HTTP_201_CREATED, dependencies=AdminOnly)
def create_instructor(body: InstructorCreate, db: DbSession):
    password = generate_temporary_password()
    user = User(username=f"tch.{body.employee_no.lower()}", password_hash=hash_password(password),
                role=Role.INSTRUCTOR, first_name=body.first_name, middle_name=body.middle_name,
                last_name=body.last_name, gender=body.gender, date_of_birth=body.date_of_birth,
                phone=body.phone, email=body.email, preferred_language=body.preferred_language)
    db.add(user)
    db.flush()
    instructor = Instructor(user_id=user.user_id, employee_no=body.employee_no, department_id=body.department_id,
                            qualification=body.qualification, employment_date=body.employment_date,
                            max_periods_per_week=body.max_periods_per_week,
                            subjects=[InstructorSubject(subject_id=s) for s in set(body.subject_ids)])
    db.add(instructor)
    db.commit()                       # duplicate employee_no -> 409
    db.refresh(instructor)
    notify.sms_user(user, "account_created", name=user.full_name, username=user.username, password=password)
    return InstructorCreated(**InstructorOut.of(instructor).model_dump(), username=user.username,
                             initial_password=password)


@router.get("", response_model=list[InstructorOut],
            dependencies=[Depends(require_roles(*STAFF_ROLES, Role.INSTRUCTOR))])
def list_instructors(db: DbSession, department_id: int | None = None, subject_id: int | None = None):
    stmt = select(Instructor)
    if department_id:
        stmt = stmt.where(Instructor.department_id == department_id)
    if subject_id:
        stmt = stmt.join(InstructorSubject).where(InstructorSubject.subject_id == subject_id)
    return [InstructorOut.of(i) for i in db.scalars(stmt.order_by(Instructor.employee_no)).unique().all()]


@router.get("/{instructor_id}", response_model=InstructorOut)
def get_instructor(instructor_id: int, db: DbSession, user: CurrentUser):
    return InstructorOut.of(_get(db, instructor_id))


@router.patch("/{instructor_id}", response_model=InstructorOut, dependencies=AdminOnly)
def update_instructor(instructor_id: int, body: InstructorUpdate, db: DbSession):
    instructor = _get(db, instructor_id)
    changes = body.model_dump(exclude_unset=True)
    for field in ("phone", "email"):
        if field in changes:
            setattr(instructor.user, field, changes.pop(field))
    for k, v in changes.items():
        setattr(instructor, k, v)
    if instructor.employment_status in ("TRANSFERRED", "RETIRED"):
        instructor.user.is_active = False
    db.commit()
    return InstructorOut.of(instructor)


@router.put("/{instructor_id}/subjects", response_model=InstructorOut, dependencies=AdminOnly)
def set_subjects(instructor_id: int, subject_ids: list[int], db: DbSession):
    """Replace the subjects this instructor is qualified to teach."""
    instructor = _get(db, instructor_id)
    instructor.subjects = [InstructorSubject(subject_id=s) for s in sorted(set(subject_ids))]
    db.commit()
    return InstructorOut.of(instructor)


@router.post("/{instructor_id}/designations", response_model=DesignationOut,
             status_code=status.HTTP_201_CREATED)
def assign_designation(instructor_id: int, body: DesignationAssign, db: DbSession,
                       user: User = Depends(require_roles(Role.ADMIN))):
    _get(db, instructor_id)
    values = body.model_dump(exclude_none=True)
    designation = InstructorDesignation(instructor_id=instructor_id, assigned_by=user.user_id, **values)
    db.add(designation)
    db.commit()                       # same designation, year and class twice -> 409
    db.refresh(designation)
    return designation


@router.get("/{instructor_id}/designations", response_model=list[DesignationOut])
def list_designations(instructor_id: int, db: DbSession, user: CurrentUser,
                      academic_year_id: int | None = None):
    stmt = select(InstructorDesignation).where(InstructorDesignation.instructor_id == instructor_id)
    if academic_year_id:
        stmt = stmt.where(InstructorDesignation.academic_year_id == academic_year_id)
    return db.scalars(stmt).all()


@router.get("/{instructor_id}/timetable", response_model=list[ScheduleOut])
def timetable(instructor_id: int, term_id: int, db: DbSession, user: CurrentUser):
    """Teaching timetable. Instructors may only read their own."""
    instructor = _get(db, instructor_id)
    if user.role == Role.INSTRUCTOR and instructor.user_id != user.user_id:
        raise forbidden()
    if user.role not in (*STAFF_ROLES, Role.INSTRUCTOR):
        raise forbidden()
    return db.scalars(select(Schedule).where(Schedule.instructor_id == instructor_id, Schedule.term_id == term_id)
                      .order_by(Schedule.day_of_week, Schedule.time_start)).all()
