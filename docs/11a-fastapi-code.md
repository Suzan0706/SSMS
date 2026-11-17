# 11a. FastAPI Code by Module

Generated from [backend/app/](../backend/app/); do not edit here. Regenerate after code changes. Models for Instructors live in `models/people.py` (shown under Students); Schedules use `models/academic.py` (shown under Courses & Subjects).

## 11a.1 Students

```python
# File: backend/app/models/people.py
"""Person/User and its role subtypes (class-table inheritance on users)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CHAR, BigInteger, DateTime, ForeignKey, Identity, Integer, SmallInteger, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import Gender, GuardianRelationship, Role, StudentStatus


class User(Base):
    """Abstract Person: shared identity and login. Exactly one subtype row per user."""

    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    username: Mapped[str] = mapped_column(String(50))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role]
    first_name: Mapped[str] = mapped_column(String(50))
    middle_name: Mapped[str | None] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50))
    gender: Mapped[Gender]
    date_of_birth: Mapped[date | None]
    phone: Mapped[str | None] = mapped_column(String(12))
    email: Mapped[str | None] = mapped_column(String(254))
    preferred_language: Mapped[str] = mapped_column(CHAR(2), server_default="sw")
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    failed_login_count: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.middle_name, self.last_name) if p)

    def age(self, on: date | None = None) -> int | None:
        if self.date_of_birth is None:
            return None
        on = on or date.today()
        dob = self.date_of_birth
        return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


class Staff(Base):
    """Admin, Registrar and Bursar."""

    __tablename__ = "staff"

    staff_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), unique=True)
    employee_no: Mapped[str] = mapped_column(String(20))
    job_title: Mapped[str] = mapped_column(String(80))
    hired_on: Mapped[date | None]

    user: Mapped[User] = relationship(lazy="joined")


class Department(Base):
    __tablename__ = "departments"

    department_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(10))
    name_en: Mapped[str] = mapped_column(String(80))
    name_sw: Mapped[str] = mapped_column(String(80))


class Instructor(Base):
    __tablename__ = "instructors"

    instructor_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), unique=True)
    employee_no: Mapped[str] = mapped_column(String(20))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.department_id"))
    qualification: Mapped[str] = mapped_column(String(100))
    employment_date: Mapped[date | None]
    employment_status: Mapped[str] = mapped_column(String(12), server_default="ACTIVE")
    max_periods_per_week: Mapped[int] = mapped_column(SmallInteger, server_default="30")

    user: Mapped[User] = relationship(lazy="joined")
    department: Mapped[Department] = relationship(lazy="joined")
    subjects: Mapped[list[InstructorSubject]] = relationship(cascade="all, delete-orphan")


class InstructorSubject(Base):
    __tablename__ = "instructor_subjects"

    instructor_id: Mapped[int] = mapped_column(ForeignKey("instructors.instructor_id"), primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.subject_id"), primary_key=True)


class Designation(Base):
    __tablename__ = "designations"

    designation_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(20))
    name_en: Mapped[str] = mapped_column(String(60))
    name_sw: Mapped[str] = mapped_column(String(60))


class InstructorDesignation(Base):
    __tablename__ = "instructor_designations"

    instructor_designation_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    instructor_id: Mapped[int] = mapped_column(ForeignKey("instructors.instructor_id"))
    designation_id: Mapped[int] = mapped_column(ForeignKey("designations.designation_id"))
    academic_year_id: Mapped[int] = mapped_column(ForeignKey("academic_years.academic_year_id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.department_id"))
    level_id: Mapped[int | None] = mapped_column(ForeignKey("class_levels.level_id"))
    stream: Mapped[str | None] = mapped_column(String(5))
    assigned_on: Mapped[date] = mapped_column(server_default=func.current_date())
    ended_on: Mapped[date | None]
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))

    designation: Mapped[Designation] = relationship(lazy="joined")


class Guardian(Base):
    __tablename__ = "guardians"

    guardian_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), unique=True)
    nida_no: Mapped[str | None] = mapped_column(CHAR(20))
    occupation: Mapped[str | None] = mapped_column(String(80))
    address: Mapped[str | None] = mapped_column(String(200))

    user: Mapped[User] = relationship(lazy="joined")


class Student(Base):
    __tablename__ = "students"

    student_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), unique=True)
    admission_no: Mapped[str] = mapped_column(String(20))
    birth_cert_no: Mapped[str | None] = mapped_column(String(30))
    necta_index_no: Mapped[str | None] = mapped_column(String(20))
    admission_date: Mapped[date] = mapped_column(server_default=func.current_date())
    current_status: Mapped[StudentStatus] = mapped_column(server_default=StudentStatus.APPLICANT.value)
    region: Mapped[str | None] = mapped_column(String(40))
    district: Mapped[str | None] = mapped_column(String(40))
    home_address: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(lazy="joined")
    guardian_links: Mapped[list[StudentGuardian]] = relationship(back_populates="student")


class StudentGuardian(Base):
    __tablename__ = "student_guardians"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"), primary_key=True)
    guardian_id: Mapped[int] = mapped_column(ForeignKey("guardians.guardian_id"), primary_key=True)
    relationship_: Mapped[GuardianRelationship] = mapped_column("relationship")
    is_primary: Mapped[bool] = mapped_column(server_default=text("false"))

    student: Mapped[Student] = relationship(back_populates="guardian_links")
    guardian: Mapped[Guardian] = relationship(lazy="joined")


class StudentStatusHistory(Base):
    __tablename__ = "student_status_history"

    history_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"))
    old_status: Mapped[StudentStatus | None]
    new_status: Mapped[StudentStatus]
    reason: Mapped[str] = mapped_column(String(300))
    effective_date: Mapped[date] = mapped_column(server_default=func.current_date())
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

```python
# File: backend/app/schemas/students.py
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import Student
from app.models.enums import Gender, GuardianRelationship, StudentStatus
from app.schemas.common import Name, NidaNo, TzPhone


class GuardianIn(BaseModel):
    first_name: Name
    last_name: Name
    gender: Gender
    phone: TzPhone
    relationship: GuardianRelationship
    is_primary: bool = False
    nida_no: NidaNo | None = None
    occupation: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=200)
    preferred_language: Literal["sw", "en"] = "sw"


class StudentCreate(BaseModel):
    first_name: Name
    middle_name: Name | None = None
    last_name: Name
    gender: Gender
    date_of_birth: date
    birth_cert_no: str | None = Field(default=None, max_length=30)
    necta_index_no: str | None = Field(default=None, max_length=20)
    phone: TzPhone | None = None
    region: str | None = Field(default=None, max_length=40)
    district: str | None = Field(default=None, max_length=40)
    home_address: str | None = Field(default=None, max_length=200)
    preferred_language: Literal["sw", "en"] = "sw"
    guardians: list[GuardianIn] = Field(min_length=1, max_length=4)

    @field_validator("date_of_birth")
    @classmethod
    def plausible_dob(cls, v: date) -> date:
        today = date.today()
        if v > today or today.year - v.year < 3:
            raise ValueError("date_of_birth must be at least 3 years ago")
        return v

    @model_validator(mode="after")
    def one_primary_guardian(self) -> "StudentCreate":
        primaries = [g for g in self.guardians if g.is_primary]
        if len(primaries) > 1:
            raise ValueError("only one guardian can be primary")
        if not primaries:
            self.guardians[0].is_primary = True
        return self


class StudentUpdate(BaseModel):
    first_name: Name | None = None
    middle_name: Name | None = None
    last_name: Name | None = None
    gender: Gender | None = None
    date_of_birth: date | None = None
    birth_cert_no: str | None = Field(default=None, max_length=30)
    necta_index_no: str | None = Field(default=None, max_length=20)
    phone: TzPhone | None = None
    region: str | None = Field(default=None, max_length=40)
    district: str | None = Field(default=None, max_length=40)
    home_address: str | None = Field(default=None, max_length=200)


class StudentOut(BaseModel):
    student_id: int
    admission_no: str
    first_name: str
    middle_name: str | None
    last_name: str
    gender: Gender
    date_of_birth: date | None
    age: int | None
    phone: str | None
    current_status: StudentStatus
    admission_date: date
    necta_index_no: str | None
    region: str | None
    district: str | None
    home_address: str | None

    @classmethod
    def of(cls, s: Student) -> "StudentOut":
        u = s.user
        return cls(
            student_id=s.student_id, admission_no=s.admission_no, first_name=u.first_name,
            middle_name=u.middle_name, last_name=u.last_name, gender=u.gender, date_of_birth=u.date_of_birth,
            age=u.age(), phone=u.phone, current_status=s.current_status, admission_date=s.admission_date,
            necta_index_no=s.necta_index_no, region=s.region, district=s.district, home_address=s.home_address,
        )


class StudentCreated(StudentOut):
    username: str
    initial_password: str = Field(description="Shown once so the registrar can print the login slip")


class StatusChangeIn(BaseModel):
    new_status: StudentStatus
    reason: str = Field(min_length=5, max_length=300)
    effective_date: date | None = None


class StatusChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    history_id: int
    student_id: int
    old_status: StudentStatus | None
    new_status: StudentStatus
    reason: str
    effective_date: date
    changed_by: int | None
    changed_at: datetime
```

```python
# File: backend/app/routers/students.py
from fastapi import APIRouter, Depends, Query, status

from app.core.i18n import STATUS_LABELS
from app.deps import CurrentUser, DbSession, require_roles
from app.models import User
from app.models.enums import Role, StudentStatus
from app.schemas.common import Page
from app.schemas.students import (StatusChangeIn, StatusChangeOut, StudentCreate, StudentCreated, StudentOut,
                                  StudentUpdate)
from app.services import notify
from app.services import students as svc

router = APIRouter(prefix="/students", tags=["Students"])

RegistrarOrAdmin = Depends(require_roles(Role.REGISTRAR, Role.ADMIN))
StaffOrInstructor = Depends(require_roles(Role.ADMIN, Role.REGISTRAR, Role.BURSAR, Role.INSTRUCTOR))


@router.post("", response_model=StudentCreated, status_code=status.HTTP_201_CREATED)
def create_student(body: StudentCreate, db: DbSession, user: User = RegistrarOrAdmin):
    result = svc.create_student(db, body)
    db.commit()
    student = result.student
    for account in result.new_guardian_accounts:
        notify.sms_user(account.user, "account_created", name=account.user.full_name,
                        username=account.user.username, password=account.password)
    notify.sms_guardians(db, student, "account_created", primary_only=True,
                         username=student.user.username, password=result.password)
    return StudentCreated(**StudentOut.of(student).model_dump(), username=student.user.username,
                          initial_password=result.password)


@router.get("", response_model=Page[StudentOut], dependencies=[StaffOrInstructor])
def search_students(
    db: DbSession,
    q: str | None = Query(default=None, max_length=50, description="Name, admission no. or NECTA index no."),
    status_: StudentStatus | None = Query(default=None, alias="status"),
    level_id: int | None = None,
    stream: str | None = Query(default=None, pattern=r"^[A-Z]{1,5}$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=25, ge=1, le=100),
):
    rows, total = svc.search_students(db, q, status_, level_id, stream, page, size)
    return Page[StudentOut](items=[StudentOut.of(s) for s in rows], total=total, page=page, size=size)


@router.get("/{student_id}", response_model=StudentOut)
def get_student(student_id: int, db: DbSession, user: CurrentUser):
    student = svc.get_student(db, student_id)
    svc.ensure_can_view(db, user, student)
    return StudentOut.of(student)


@router.patch("/{student_id}", response_model=StudentOut)
def update_student(student_id: int, body: StudentUpdate, db: DbSession, user: User = RegistrarOrAdmin):
    student = svc.update_student(db, svc.get_student(db, student_id), body)
    db.commit()
    return StudentOut.of(student)


@router.patch("/{student_id}/status", response_model=StatusChangeOut)
def change_status(student_id: int, body: StatusChangeIn, db: DbSession, user: User = RegistrarOrAdmin):
    student = svc.get_student(db, student_id)
    history = svc.change_status(db, student, body, user)
    db.commit()
    notify.sms_guardians(db, student, "status_changed", status=STATUS_LABELS[body.new_status.value],
                         reason=body.reason)
    return history


@router.get("/{student_id}/status-history", response_model=list[StatusChangeOut])
def status_history(student_id: int, db: DbSession, user: CurrentUser):
    svc.ensure_can_view(db, user, svc.get_student(db, student_id))
    return svc.status_history(db, student_id)
```

```python
# File: backend/app/services/students.py
"""UC-02: register, search, update students; status changes with history."""
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, forbidden, rule_violation
from app.core.security import generate_temporary_password, hash_password
from app.models import (AcademicYear, CourseOffering, Enrolment, Guardian, Student, StudentGuardian,
                        StudentStatusHistory, User)
from app.models.enums import STAFF_ROLES, EnrolmentStatus, Role, StudentStatus
from app.schemas.students import GuardianIn, StatusChangeIn, StudentCreate, StudentUpdate
from app.services.auth import revoke_all_tokens
from app.services.common import next_number

S = StudentStatus

# Allowed status transitions (UC-02 business rule).
ALLOWED_TRANSITIONS: dict[StudentStatus, set[StudentStatus]] = {
    S.APPLICANT: {S.ACTIVE},                       # only through enrolment confirmation
    S.ACTIVE: {S.SUSPENDED, S.TRANSFERRED, S.DROPPED_OUT, S.GRADUATED},
    S.SUSPENDED: {S.ACTIVE, S.DROPPED_OUT},
    S.TRANSFERRED: {S.ACTIVE},                     # re-admission, ADMIN only
    S.DROPPED_OUT: {S.ACTIVE},                     # re-admission, ADMIN only
    S.GRADUATED: set(),
}
READMISSION_FROM = {S.TRANSFERRED, S.DROPPED_OUT}
DEACTIVATES_LOGIN = {S.TRANSFERRED, S.DROPPED_OUT}


@dataclass
class NewAccount:
    user: User
    password: str


@dataclass
class StudentCreated:
    student: Student
    password: str
    new_guardian_accounts: list[NewAccount] = field(default_factory=list)


def _find_or_create_guardian(db: Session, g: GuardianIn) -> tuple[Guardian, NewAccount | None]:
    existing = db.scalar(select(Guardian).join(User, User.user_id == Guardian.user_id)
                         .where(User.phone == g.phone, User.role == Role.PARENT))
    if existing:
        return existing, None
    password = generate_temporary_password()
    user = User(username=f"p{g.phone}", password_hash=hash_password(password), role=Role.PARENT,
                first_name=g.first_name, last_name=g.last_name, gender=g.gender, phone=g.phone,
                preferred_language=g.preferred_language)
    db.add(user)
    db.flush()
    guardian = Guardian(user_id=user.user_id, nida_no=g.nida_no, occupation=g.occupation, address=g.address)
    db.add(guardian)
    db.flush()
    return guardian, NewAccount(user, password)


def create_student(db: Session, data: StudentCreate) -> StudentCreated:
    admission_no = next_number(db, "admission")
    password = generate_temporary_password()
    user = User(username=admission_no.lower(), password_hash=hash_password(password), role=Role.STUDENT,
                first_name=data.first_name, middle_name=data.middle_name, last_name=data.last_name,
                gender=data.gender, date_of_birth=data.date_of_birth, phone=data.phone,
                preferred_language=data.preferred_language)
    db.add(user)
    db.flush()
    student = Student(user_id=user.user_id, admission_no=admission_no, birth_cert_no=data.birth_cert_no,
                      necta_index_no=data.necta_index_no, region=data.region, district=data.district,
                      home_address=data.home_address)
    db.add(student)
    db.flush()
    result = StudentCreated(student, password)
    for g in data.guardians:
        guardian, account = _find_or_create_guardian(db, g)
        if account:
            result.new_guardian_accounts.append(account)
        db.add(StudentGuardian(student_id=student.student_id, guardian_id=guardian.guardian_id,
                               relationship_=g.relationship, is_primary=g.is_primary))
    db.flush()
    db.refresh(student)
    return result


def get_student(db: Session, student_id: int) -> Student:
    student = db.get(Student, student_id)
    if student is None:
        raise AppError(404, "NOT_FOUND", "Student not found", "Mwanafunzi hakupatikana")
    return student


def ensure_can_view(db: Session, user: User, student: Student) -> None:
    """Staff and instructors see all students; a student sees self; a parent sees linked children.
    Others get 404 (not 403) so the existence of a record is not revealed."""
    if user.role in STAFF_ROLES or user.role == Role.INSTRUCTOR:
        return
    if user.role == Role.STUDENT and student.user_id == user.user_id:
        return
    if user.role == Role.PARENT and db.scalar(select(exists().where(
            StudentGuardian.student_id == student.student_id,
            StudentGuardian.guardian_id == Guardian.guardian_id,
            Guardian.user_id == user.user_id))):
        return
    raise AppError(404, "NOT_FOUND", "Student not found", "Mwanafunzi hakupatikana")


def search_students(db: Session, q: str | None, status: StudentStatus | None, level_id: int | None,
                    stream: str | None, page: int, size: int) -> tuple[list[Student], int]:
    stmt = select(Student).join(User, User.user_id == Student.user_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.first_name.ilike(like), User.last_name.ilike(like),
                              Student.admission_no.ilike(like), Student.necta_index_no.ilike(like)))
    if status:
        stmt = stmt.where(Student.current_status == status)
    if level_id or stream:
        current = (select(Enrolment.student_id)
                   .join(CourseOffering, CourseOffering.offering_id == Enrolment.offering_id)
                   .join(AcademicYear, AcademicYear.academic_year_id == CourseOffering.academic_year_id)
                   .where(AcademicYear.is_current, Enrolment.status == EnrolmentStatus.CONFIRMED))
        if level_id:
            current = current.where(CourseOffering.level_id == level_id)
        if stream:
            current = current.where(Enrolment.stream == stream)
        stmt = stmt.where(Student.student_id.in_(current))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.last_name, User.first_name)
                      .offset((page - 1) * size).limit(size)).all()
    return list(rows), total or 0


def update_student(db: Session, student: Student, data: StudentUpdate) -> Student:
    changes = data.model_dump(exclude_unset=True)
    for field_name in ("first_name", "middle_name", "last_name", "gender", "date_of_birth", "phone"):
        if field_name in changes:
            setattr(student.user, field_name, changes.pop(field_name))
    for field_name, value in changes.items():
        setattr(student, field_name, value)
    db.flush()
    return student


def change_status(db: Session, student: Student, data: StatusChangeIn, actor: User,
                  via_enrolment: bool = False) -> StudentStatusHistory:
    # Lock only the students row (serialises concurrent changes), then reload it.
    db.execute(select(Student.student_id).where(Student.student_id == student.student_id).with_for_update())
    db.refresh(student)
    old, new = student.current_status, data.new_status
    if new not in ALLOWED_TRANSITIONS[old]:
        raise rule_violation(f"Status change {old} -> {new} is not allowed",
                             f"Kubadilisha hali kutoka {old} kwenda {new} hakuruhusiwi")
    if old == S.APPLICANT and not via_enrolment:
        raise rule_violation("Applicants become ACTIVE only when their enrolment is confirmed",
                             "Mwombaji anakuwa hai pale tu usajili wake unapothibitishwa")
    if old in READMISSION_FROM and actor.role != Role.ADMIN:
        raise forbidden()

    student.current_status = new
    history = StudentStatusHistory(student_id=student.student_id, old_status=old, new_status=new,
                                   reason=data.reason, effective_date=data.effective_date or date.today(),
                                   changed_by=actor.user_id)
    db.add(history)
    if new in DEACTIVATES_LOGIN:
        student.user.is_active = False
        revoke_all_tokens(db, student.user_id)
    elif old in READMISSION_FROM:
        student.user.is_active = True
    db.flush()
    return history


def status_history(db: Session, student_id: int) -> list[StudentStatusHistory]:
    return list(db.scalars(select(StudentStatusHistory).where(StudentStatusHistory.student_id == student_id)
                           .order_by(StudentStatusHistory.changed_at.desc())).all())
```

## 11a.2 Courses & Subjects

```python
# File: backend/app/models/academic.py
"""Calendar, levels, courses, subjects, offerings, rooms and timetable sessions."""
from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Integer, SmallInteger, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import EducationLevel, RoomType


class AcademicYear(Base):
    __tablename__ = "academic_years"

    academic_year_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(9))
    start_date: Mapped[date]
    end_date: Mapped[date]
    is_current: Mapped[bool] = mapped_column(server_default=text("false"))


class Term(Base):
    __tablename__ = "terms"

    term_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    academic_year_id: Mapped[int] = mapped_column(ForeignKey("academic_years.academic_year_id"))
    term_no: Mapped[int] = mapped_column(SmallInteger)
    name_en: Mapped[str] = mapped_column(String(30))
    name_sw: Mapped[str] = mapped_column(String(30))
    start_date: Mapped[date]
    end_date: Mapped[date]


class ClassLevel(Base):
    __tablename__ = "class_levels"

    level_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(5))
    name_en: Mapped[str] = mapped_column(String(30))
    name_sw: Mapped[str] = mapped_column(String(30))
    education_level: Mapped[EducationLevel]
    exam_scale: Mapped[str] = mapped_column(String(5))
    sort_order: Mapped[int] = mapped_column(SmallInteger)


class Subject(Base):
    __tablename__ = "subjects"

    subject_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    subject_code: Mapped[str] = mapped_column(String(10))
    necta_code: Mapped[str | None] = mapped_column(String(5))
    name_en: Mapped[str] = mapped_column(String(80))
    name_sw: Mapped[str] = mapped_column(String(80))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.department_id"))
    room_type_required: Mapped[RoomType] = mapped_column(server_default=RoomType.CLASSROOM.value)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Course(Base):
    __tablename__ = "courses"

    course_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    course_code: Mapped[str] = mapped_column(String(10))
    course_name: Mapped[str] = mapped_column(String(100))
    course_name_sw: Mapped[str] = mapped_column(String(100))
    course_desc: Mapped[str | None] = mapped_column(Text)
    education_level: Mapped[EducationLevel]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    subjects: Mapped[list[CourseSubject]] = relationship(cascade="all, delete-orphan")


class CourseSubject(Base):
    __tablename__ = "course_subjects"

    course_id: Mapped[int] = mapped_column(ForeignKey("courses.course_id"), primary_key=True)
    level_id: Mapped[int] = mapped_column(ForeignKey("class_levels.level_id"), primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.subject_id"), primary_key=True)
    is_compulsory: Mapped[bool] = mapped_column(server_default=text("true"))
    periods_per_week: Mapped[int] = mapped_column(SmallInteger, server_default="4")

    subject: Mapped[Subject] = relationship(lazy="joined")


class CourseOffering(Base):
    __tablename__ = "course_offerings"

    offering_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.course_id"))
    academic_year_id: Mapped[int] = mapped_column(ForeignKey("academic_years.academic_year_id"))
    level_id: Mapped[int] = mapped_column(ForeignKey("class_levels.level_id"))
    capacity: Mapped[int] = mapped_column(SmallInteger)
    is_open: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    course: Mapped[Course] = relationship(lazy="joined")
    level: Mapped[ClassLevel] = relationship(lazy="joined")
    academic_year: Mapped[AcademicYear] = relationship(lazy="joined")


class Room(Base):
    __tablename__ = "rooms"

    room_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    room_code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(60))
    room_type: Mapped[RoomType] = mapped_column(server_default=RoomType.CLASSROOM.value)
    capacity: Mapped[int] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Schedule(Base):
    """One weekly class session. The generated `slot` range column is left to the database."""

    __tablename__ = "schedules"

    schedule_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    offering_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.offering_id"))
    stream: Mapped[str] = mapped_column(String(5), server_default="A")
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.term_id"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.subject_id"))
    instructor_id: Mapped[int] = mapped_column(ForeignKey("instructors.instructor_id"))
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.room_id"))
    day_of_week: Mapped[int] = mapped_column(SmallInteger)
    time_start: Mapped[time]
    time_end: Mapped[time]
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    subject: Mapped[Subject] = relationship(lazy="joined")
    room: Mapped[Room] = relationship(lazy="joined")

    def overlaps(self, other: Schedule) -> bool:
        return (self.term_id == other.term_id and self.day_of_week == other.day_of_week
                and self.time_start < other.time_end and other.time_start < self.time_end)
```

```python
# File: backend/app/schemas/courses.py
from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EducationLevel, RoomType


class SubjectIn(BaseModel):
    subject_code: str = Field(max_length=10, pattern=r"^[A-Z0-9-]+$")
    necta_code: str | None = Field(default=None, max_length=5)
    name_en: str = Field(max_length=80)
    name_sw: str = Field(max_length=80)
    department_id: int
    room_type_required: RoomType = RoomType.CLASSROOM
    description: str | None = None


class SubjectOut(SubjectIn):
    model_config = ConfigDict(from_attributes=True)

    subject_id: int
    is_active: bool


class CourseIn(BaseModel):
    course_code: str = Field(max_length=10, pattern=r"^[A-Z0-9-]+$")
    course_name: str = Field(max_length=100)
    course_name_sw: str = Field(max_length=100)
    course_desc: str | None = None
    education_level: EducationLevel


class CourseUpdate(BaseModel):
    course_name: str | None = Field(default=None, max_length=100)
    course_name_sw: str | None = Field(default=None, max_length=100)
    course_desc: str | None = None
    is_active: bool | None = None


class CourseOut(CourseIn):
    model_config = ConfigDict(from_attributes=True)

    course_id: int
    is_active: bool


class CourseSubjectIn(BaseModel):
    subject_id: int
    is_compulsory: bool = True
    periods_per_week: int = Field(default=4, ge=1, le=12)


class CourseSubjectOut(CourseSubjectIn):
    model_config = ConfigDict(from_attributes=True)

    level_id: int
    subject: SubjectOut


class OfferingIn(BaseModel):
    course_id: int
    academic_year_id: int
    level_id: int
    capacity: int = Field(gt=0, le=2000)
    is_open: bool = True


class OfferingOut(BaseModel):
    offering_id: int
    course_id: int
    course_code: str
    course_name: str
    course_name_sw: str
    academic_year: str
    level_code: str
    level_name_en: str
    level_name_sw: str
    capacity: int
    confirmed: int
    places_left: int
    is_open: bool


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    requirement_id: int
    code: str
    name_en: str
    name_sw: str
    is_mandatory: bool


class OfferingDetail(OfferingOut):
    subjects: list[CourseSubjectOut]
    requirements: list[RequirementOut]
```

```python
# File: backend/app/routers/courses.py
"""UC-03 Manage Courses & Subjects, and course offerings (D2 Course Offers)."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select

from app.core.errors import not_found
from app.deps import CurrentUser, DbSession, require_roles
from app.models import (AcademicYear, Course, CourseOffering, CourseSubject, Enrolment, EnrolmentRequirement,
                        Subject)
from app.models.enums import EnrolmentStatus, Role
from app.schemas.courses import (CourseIn, CourseOut, CourseSubjectIn, CourseSubjectOut, CourseUpdate,
                                 OfferingDetail, OfferingIn, OfferingOut, RequirementOut, SubjectIn, SubjectOut)

router = APIRouter(tags=["Courses & Subjects"])
AdminOnly = [Depends(require_roles(Role.ADMIN))]


# ----- Subjects -----
@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(db: DbSession, user: CurrentUser, active_only: bool = True):
    stmt = select(Subject).order_by(Subject.subject_code)
    if active_only:
        stmt = stmt.where(Subject.is_active)
    return db.scalars(stmt).all()


@router.post("/subjects", response_model=SubjectOut, status_code=status.HTTP_201_CREATED, dependencies=AdminOnly)
def create_subject(body: SubjectIn, db: DbSession):
    subject = Subject(**body.model_dump())
    db.add(subject)
    db.commit()                            # duplicate subject_code -> 409 DUPLICATE
    db.refresh(subject)
    return subject


@router.patch("/subjects/{subject_id}", response_model=SubjectOut, dependencies=AdminOnly)
def update_subject(subject_id: int, body: SubjectIn, db: DbSession):
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise not_found("Subject")
    for k, v in body.model_dump().items():
        setattr(subject, k, v)
    db.commit()
    return subject


# ----- Courses -----
@router.get("/courses", response_model=list[CourseOut])
def list_courses(db: DbSession, user: CurrentUser):
    return db.scalars(select(Course).order_by(Course.course_code)).all()


@router.post("/courses", response_model=CourseOut, status_code=status.HTTP_201_CREATED, dependencies=AdminOnly)
def create_course(body: CourseIn, db: DbSession):
    course = Course(**body.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.patch("/courses/{course_id}", response_model=CourseOut, dependencies=AdminOnly)
def update_course(course_id: int, body: CourseUpdate, db: DbSession):
    course = db.get(Course, course_id)
    if course is None:
        raise not_found("Course")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(course, k, v)
    db.commit()
    return course


def _course_subjects(db, course_id: int, level_id: int) -> list[CourseSubject]:
    return list(db.scalars(select(CourseSubject).where(CourseSubject.course_id == course_id,
                                                       CourseSubject.level_id == level_id)).all())


@router.get("/courses/{course_id}/levels/{level_id}/subjects", response_model=list[CourseSubjectOut])
def course_subjects(course_id: int, level_id: int, db: DbSession, user: CurrentUser):
    return _course_subjects(db, course_id, level_id)


@router.put("/courses/{course_id}/levels/{level_id}/subjects", response_model=list[CourseSubjectOut],
            dependencies=AdminOnly)
def set_course_subjects(course_id: int, level_id: int, body: list[CourseSubjectIn], db: DbSession):
    """Replace the subject list of a course at one level."""
    course = db.get(Course, course_id)
    if course is None:
        raise not_found("Course")
    course.subjects = [cs for cs in course.subjects if cs.level_id != level_id] + [
        CourseSubject(course_id=course_id, level_id=level_id, **item.model_dump()) for item in body]
    db.commit()
    return _course_subjects(db, course_id, level_id)


# ----- Offerings -----
def _offering_out(db, o: CourseOffering) -> dict:
    confirmed = db.scalar(select(func.count()).select_from(Enrolment).where(
        Enrolment.offering_id == o.offering_id, Enrolment.status == EnrolmentStatus.CONFIRMED)) or 0
    return dict(offering_id=o.offering_id, course_id=o.course_id, course_code=o.course.course_code,
                course_name=o.course.course_name, course_name_sw=o.course.course_name_sw,
                academic_year=o.academic_year.name, level_code=o.level.code, level_name_en=o.level.name_en,
                level_name_sw=o.level.name_sw, capacity=o.capacity, confirmed=confirmed,
                places_left=max(o.capacity - confirmed, 0), is_open=o.is_open)


@router.get("/course-offerings", response_model=list[OfferingOut])
def list_offerings(db: DbSession, user: CurrentUser, academic_year_id: int | None = None,
                   is_open: bool | None = Query(default=None)):
    """List of courses offered. Defaults to the current academic year."""
    stmt = select(CourseOffering).join(AcademicYear)
    stmt = stmt.where(CourseOffering.academic_year_id == academic_year_id) if academic_year_id \
        else stmt.where(AcademicYear.is_current)
    if is_open is not None:
        stmt = stmt.where(CourseOffering.is_open == is_open)
    return [_offering_out(db, o) for o in db.scalars(stmt.order_by(CourseOffering.offering_id)).all()]


@router.get("/course-offerings/{offering_id}", response_model=OfferingDetail)
def get_offering(offering_id: int, db: DbSession, user: CurrentUser):
    """Course information: subjects at this level and the enrolment requirements."""
    o = db.get(CourseOffering, offering_id)
    if o is None:
        raise not_found("Course offering")
    subjects = db.scalars(select(CourseSubject).where(CourseSubject.course_id == o.course_id,
                                                      CourseSubject.level_id == o.level_id)).all()
    requirements = db.scalars(select(EnrolmentRequirement).where(
        EnrolmentRequirement.is_active,
        or_(EnrolmentRequirement.education_level.is_(None),
            EnrolmentRequirement.education_level == o.course.education_level))).all()
    return OfferingDetail(**_offering_out(db, o),
                          subjects=[CourseSubjectOut.model_validate(s) for s in subjects],
                          requirements=[RequirementOut.model_validate(r) for r in requirements])


@router.post("/course-offerings", response_model=OfferingOut, status_code=status.HTTP_201_CREATED,
             dependencies=AdminOnly)
def create_offering(body: OfferingIn, db: DbSession):
    offering = CourseOffering(**body.model_dump())
    db.add(offering)
    db.commit()                            # one offering per course + year + level
    db.refresh(offering)
    return _offering_out(db, offering)
```

## 11a.3 Instructors

```python
# File: backend/app/schemas/instructors.py
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import Instructor
from app.models.enums import Gender
from app.schemas.common import Name, Stream, TzPhone


class InstructorCreate(BaseModel):
    first_name: Name
    middle_name: Name | None = None
    last_name: Name
    gender: Gender
    date_of_birth: date | None = None
    phone: TzPhone
    email: EmailStr | None = None
    preferred_language: Literal["sw", "en"] = "sw"
    employee_no: str = Field(max_length=20)
    department_id: int
    qualification: str = Field(max_length=100)
    employment_date: date | None = None
    max_periods_per_week: int = Field(default=30, ge=1, le=50)
    subject_ids: list[int] = Field(default_factory=list)


class InstructorUpdate(BaseModel):
    department_id: int | None = None
    qualification: str | None = Field(default=None, max_length=100)
    employment_status: Literal["ACTIVE", "ON_LEAVE", "TRANSFERRED", "RETIRED"] | None = None
    max_periods_per_week: int | None = Field(default=None, ge=1, le=50)
    phone: TzPhone | None = None
    email: EmailStr | None = None


class InstructorOut(BaseModel):
    instructor_id: int
    employee_no: str
    first_name: str
    last_name: str
    gender: Gender
    phone: str | None
    email: str | None
    department_code: str
    qualification: str
    employment_status: str
    max_periods_per_week: int
    subject_ids: list[int]

    @classmethod
    def of(cls, i: Instructor) -> "InstructorOut":
        return cls(
            instructor_id=i.instructor_id, employee_no=i.employee_no, first_name=i.user.first_name,
            last_name=i.user.last_name, gender=i.user.gender, phone=i.user.phone, email=i.user.email,
            department_code=i.department.code, qualification=i.qualification,
            employment_status=i.employment_status, max_periods_per_week=i.max_periods_per_week,
            subject_ids=sorted(s.subject_id for s in i.subjects),
        )


class InstructorCreated(InstructorOut):
    username: str
    initial_password: str


class DesignationAssign(BaseModel):
    designation_id: int
    academic_year_id: int
    department_id: int | None = None
    level_id: int | None = None
    stream: Stream | None = None
    assigned_on: date | None = None

    @model_validator(mode="after")
    def class_needs_stream(self) -> "DesignationAssign":
        if (self.level_id is None) != (self.stream is None):
            raise ValueError("level_id and stream must be given together")
        return self


class DesignationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instructor_designation_id: int
    instructor_id: int
    designation_id: int
    academic_year_id: int
    department_id: int | None
    level_id: int | None
    stream: str | None
    assigned_on: date
    ended_on: date | None
```

```python
# File: backend/app/routers/instructors.py
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
```

## 11a.4 Schedules

```python
# File: backend/app/schemas/schedules.py
from datetime import time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import Stream


class ScheduleIn(BaseModel):
    offering_id: int
    stream: Stream = "A"
    term_id: int
    subject_id: int
    instructor_id: int
    room_id: int
    day_of_week: int = Field(ge=1, le=6, description="1 = Monday ... 6 = Saturday")
    time_start: time
    time_end: time

    @model_validator(mode="after")
    def end_after_start(self) -> "ScheduleIn":
        if self.time_end <= self.time_start:
            raise ValueError("time_end must be after time_start")
        return self


class ScheduleOut(ScheduleIn):
    model_config = ConfigDict(from_attributes=True)

    schedule_id: int


class ConflictOut(BaseModel):
    kind: str = Field(description="INSTRUCTOR, ROOM, CLASS or STUDENT")
    schedule_id: int
    message: str


class CheckResult(BaseModel):
    ok: bool
    conflicts: list[ConflictOut]
    problems: list[str] = Field(description="Rule failures: qualification, room type, capacity, load")


class GenerateIn(BaseModel):
    term_id: int
    offering_ids: list[int] = Field(min_length=1)
    streams: list[Stream] = ["A"]
    persist: bool = Field(default=False, description="false = return a draft only")


class DraftLesson(BaseModel):
    offering_id: int
    stream: str
    subject_id: int
    instructor_id: int | None
    room_id: int | None
    day_of_week: int | None
    time_start: time | None
    time_end: time | None


class GenerateOut(BaseModel):
    placed: list[DraftLesson]
    unplaced: list[DraftLesson]
    persisted: bool
```

```python
# File: backend/app/routers/schedules.py
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
```

```python
# File: backend/app/services/scheduling.py
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
```

## 11a.5 Enrolment

```python
# File: backend/app/models/enrolment.py
"""Enrolment, requirement documents and the student <-> session link."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, BigInteger, DateTime, ForeignKey, Identity, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.academic import CourseOffering
from app.models.enums import DocumentStatus, EducationLevel, EnrolmentStatus
from app.models.people import Student


class EnrolmentRequirement(Base):
    __tablename__ = "enrolment_requirements"

    requirement_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(20))
    name_en: Mapped[str] = mapped_column(String(100))
    name_sw: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    education_level: Mapped[EducationLevel | None]
    is_mandatory: Mapped[bool] = mapped_column(server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Enrolment(Base):
    __tablename__ = "enrolments"

    enrolment_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    enrolment_no: Mapped[str] = mapped_column(String(20))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"))
    offering_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.offering_id"))
    stream: Mapped[str | None] = mapped_column(String(5))
    status: Mapped[EnrolmentStatus] = mapped_column(server_default=EnrolmentStatus.PENDING.value)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student] = relationship(lazy="joined")
    offering: Mapped[CourseOffering] = relationship(lazy="joined")
    documents: Mapped[list[EnrolmentDocument]] = relationship(back_populates="enrolment")


class EnrolmentDocument(Base):
    __tablename__ = "enrolment_documents"

    document_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    enrolment_id: Mapped[int] = mapped_column(ForeignKey("enrolments.enrolment_id"))
    requirement_id: Mapped[int] = mapped_column(ForeignKey("enrolment_requirements.requirement_id"))
    file_name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(50))
    file_size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(CHAR(64))
    status: Mapped[DocumentStatus] = mapped_column(server_default=DocumentStatus.PENDING.value)
    remarks: Mapped[str | None] = mapped_column(String(300))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    validated_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    enrolment: Mapped[Enrolment] = relationship(back_populates="documents")
    requirement: Mapped[EnrolmentRequirement] = relationship(lazy="joined")


class EnrolmentSchedule(Base):
    __tablename__ = "enrolment_schedules"

    enrolment_id: Mapped[int] = mapped_column(ForeignKey("enrolments.enrolment_id"), primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.schedule_id"), primary_key=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

```python
# File: backend/app/schemas/enrolments.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import DocumentStatus, EnrolmentStatus
from app.schemas.common import Stream
from app.schemas.courses import RequirementOut


class EnrolmentCreate(BaseModel):
    offering_id: int
    student_id: int | None = Field(default=None, description="Registrar only; students apply for themselves")


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    requirement_id: int
    file_name: str
    mime_type: str
    file_size_bytes: int
    sha256: str
    status: DocumentStatus
    remarks: str | None
    uploaded_at: datetime
    validated_at: datetime | None


class EnrolmentOut(BaseModel):
    enrolment_id: int
    enrolment_no: str
    student_id: int
    offering_id: int
    course_code: str
    level_code: str
    academic_year: str
    stream: str | None
    status: EnrolmentStatus
    applied_at: datetime
    submitted_at: datetime | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    requirements: list[RequirementOut] = []
    documents: list[DocumentOut] = []


class DocumentValidateIn(BaseModel):
    status: Literal["VALID", "INVALID"]
    remarks: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def invalid_needs_remarks(self) -> "DocumentValidateIn":
        if self.status == "INVALID" and not self.remarks:
            raise ValueError("remarks are required when a document is INVALID")
        return self


class ConfirmIn(BaseModel):
    stream: Stream


class CancelIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


class ConfirmOut(BaseModel):
    enrolment: EnrolmentOut
    schedules_linked: int
    invoice_no: str | None
```

```python
# File: backend/app/routers/enrolments.py
"""UC-06 Enrol Student and UC-07 Validate Requirements."""
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError, forbidden
from app.core.i18n import tzs
from app.deps import CurrentUser, DbSession, get_storage, require_roles
from app.models import Enrolment, EnrolmentDocument, Student, User
from app.models.enums import DocumentStatus, EnrolmentStatus, Role
from app.schemas.courses import RequirementOut
from app.schemas.enrolments import (CancelIn, ConfirmIn, ConfirmOut, DocumentOut, DocumentValidateIn,
                                    EnrolmentCreate, EnrolmentOut)
from app.services import enrolments as svc
from app.services import notify
from app.services.payments import invoice_balance
from app.services.storage import Storage
from app.tasks.payments import request_control_number

router = APIRouter(tags=["Enrolment"])
Registrar = Depends(require_roles(Role.REGISTRAR, Role.ADMIN))


def _out(db, e: Enrolment, with_details: bool = True) -> EnrolmentOut:
    o = e.offering
    return EnrolmentOut(
        enrolment_id=e.enrolment_id, enrolment_no=e.enrolment_no, student_id=e.student_id,
        offering_id=e.offering_id, course_code=o.course.course_code, level_code=o.level.code,
        academic_year=o.academic_year.name, stream=e.stream, status=e.status, applied_at=e.applied_at,
        submitted_at=e.submitted_at, confirmed_at=e.confirmed_at, cancelled_at=e.cancelled_at,
        cancel_reason=e.cancel_reason,
        requirements=[RequirementOut.model_validate(r) for r in svc.requirements_for(db, e)] if with_details else [],
        documents=[DocumentOut.model_validate(d) for d in e.documents] if with_details else [],
    )


def _load_for(db, enrolment_id: int, user: User) -> Enrolment:
    """Students act only on their own enrolment; staff and instructors on any."""
    enrolment = svc.get_enrolment(db, enrolment_id)
    if user.role == Role.STUDENT and enrolment.student.user_id != user.user_id:
        raise AppError(404, "NOT_FOUND", "Enrolment not found", "Usajili haukupatikana")
    if user.role == Role.PARENT:
        raise forbidden()
    return enrolment


@router.post("/enrolments", response_model=EnrolmentOut, status_code=status.HTTP_201_CREATED)
def apply(body: EnrolmentCreate, db: DbSession, user: CurrentUser):
    """Student applies for themselves; Registrar/Admin may apply on behalf of a student."""
    if user.role == Role.STUDENT:
        student = db.scalar(select(Student).where(Student.user_id == user.user_id))
    elif user.role in (Role.REGISTRAR, Role.ADMIN) and body.student_id:
        student = db.get(Student, body.student_id)
    else:
        raise forbidden()
    if student is None:
        raise AppError(404, "NOT_FOUND", "Student not found", "Mwanafunzi hakupatikana")
    enrolment = svc.apply(db, student, body.offering_id)
    db.commit()
    return _out(db, enrolment)


@router.get("/enrolments", response_model=list[EnrolmentOut], dependencies=[Registrar])
def list_enrolments(db: DbSession, status_: EnrolmentStatus | None = Query(default=None, alias="status"),
                    offering_id: int | None = None):
    stmt = select(Enrolment).order_by(Enrolment.enrolment_id.desc())
    if status_:
        stmt = stmt.where(Enrolment.status == status_)
    if offering_id:
        stmt = stmt.where(Enrolment.offering_id == offering_id)
    return [_out(db, e, with_details=False) for e in db.scalars(stmt.limit(500)).all()]


@router.get("/enrolments/{enrolment_id}", response_model=EnrolmentOut)
def get_enrolment(enrolment_id: int, db: DbSession, user: CurrentUser):
    return _out(db, _load_for(db, enrolment_id, user))


@router.get("/enrolments/{enrolment_id}/requirements", response_model=list[RequirementOut])
def requirements(enrolment_id: int, db: DbSession, user: CurrentUser):
    return svc.requirements_for(db, _load_for(db, enrolment_id, user))


@router.post("/enrolments/{enrolment_id}/documents", response_model=DocumentOut,
             status_code=status.HTTP_201_CREATED)
async def upload_document(enrolment_id: int, db: DbSession, user: CurrentUser,
                          requirement_id: int = Form(...), file: UploadFile = File(...),
                          storage: Storage = Depends(get_storage)):
    """PDF, JPG or PNG up to 5 MB. Type is checked from the file content, not the name."""
    enrolment = _load_for(db, enrolment_id, user)
    content = await file.read(get_settings().max_upload_bytes + 1)
    doc = svc.upload_document(db, storage, enrolment, requirement_id, file.filename or "upload", content)
    db.commit()
    return doc


@router.post("/enrolments/{enrolment_id}/submit", response_model=EnrolmentOut)
def submit(enrolment_id: int, db: DbSession, user: CurrentUser):
    enrolment = svc.submit(db, _load_for(db, enrolment_id, user))
    db.commit()
    return _out(db, enrolment)


@router.get("/enrolment-documents", response_model=list[DocumentOut],
            dependencies=[Depends(require_roles(Role.INSTRUCTOR, Role.REGISTRAR, Role.ADMIN))])
def validation_queue(db: DbSession, status_: DocumentStatus = Query(default=DocumentStatus.PENDING, alias="status")):
    """Documents of SUBMITTED enrolments waiting for faculty validation."""
    return db.scalars(select(EnrolmentDocument).join(Enrolment).where(
        EnrolmentDocument.status == status_, Enrolment.status == EnrolmentStatus.SUBMITTED)
        .order_by(EnrolmentDocument.uploaded_at)).all()


@router.patch("/enrolment-documents/{document_id}", response_model=EnrolmentOut)
def validate_document(document_id: int, body: DocumentValidateIn, db: DbSession,
                      user: User = Depends(require_roles(Role.INSTRUCTOR, Role.ADMIN))):
    """Faculty marks one document VALID or INVALID (remarks required). Enrolment status follows."""
    enrolment = svc.validate_document(db, document_id, body.status, body.remarks, user)
    db.commit()
    if enrolment.status == EnrolmentStatus.VALIDATED:
        notify.sms_user(enrolment.student.user, "requirements_completed", enrolment_no=enrolment.enrolment_no)
    elif enrolment.status == EnrolmentStatus.INVALID:
        notify.sms_user(enrolment.student.user, "requirements_invalid")
    return _out(db, enrolment)


@router.post("/enrolments/{enrolment_id}/confirm", response_model=ConfirmOut)
def confirm(enrolment_id: int, body: ConfirmIn, db: DbSession, user: User = Registrar):
    """Confirm: stream, class sessions, student ACTIVE and term invoice in one transaction."""
    result = svc.confirm(db, svc.get_enrolment(db, enrolment_id), body.stream, user)
    db.commit()
    e = result.enrolment
    notify.sms_user(e.student.user, "enrolment_confirmed", name=e.student.user.full_name,
                    level={"sw": e.offering.level.name_sw, "en": e.offering.level.name_en}, stream=e.stream)
    if result.invoice:
        balance = invoice_balance(db, result.invoice.invoice_id)
        notify.sms_guardians(db, e.student, "invoice_issued", primary_only=True,
                             invoice_no=result.invoice.invoice_no, amount=tzs(balance["total_tzs"]),
                             control_no=result.invoice.gepg_control_no or "-")
        try:
            request_control_number.delay(result.invoice.invoice_id)
        except Exception:              # retried by the nightly reconciliation job
            pass
    return ConfirmOut(enrolment=_out(db, e), schedules_linked=result.schedules_linked,
                      invoice_no=result.invoice.invoice_no if result.invoice else None)


@router.post("/enrolments/{enrolment_id}/cancel", response_model=EnrolmentOut)
def cancel(enrolment_id: int, body: CancelIn, db: DbSession, user: CurrentUser):
    if user.role not in (Role.STUDENT, Role.REGISTRAR, Role.ADMIN):
        raise forbidden()
    enrolment = svc.cancel(db, _load_for(db, enrolment_id, user), body.reason)
    db.commit()
    notify.sms_user(enrolment.student.user, "enrolment_cancelled", enrolment_no=enrolment.enrolment_no,
                    reason=body.reason)
    return _out(db, enrolment)
```

```python
# File: backend/app/services/enrolments.py
"""UC-06 Enrol Student and UC-07 Validate Requirements."""
import hashlib
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, not_found, rule_violation
from app.models import (CourseOffering, Enrolment, EnrolmentDocument, EnrolmentRequirement, EnrolmentSchedule,
                        Invoice, Schedule, Student, Term, User)
from app.models.enums import DocumentStatus, EnrolmentStatus, StudentStatus
from app.schemas.students import StatusChangeIn
from app.services import payments, students
from app.services.common import next_number, now_eat
from app.services.storage import Storage

E = EnrolmentStatus

# File type is decided by the first bytes, never by the extension or the browser's claim.
MAGIC = {
    b"%PDF-": ("application/pdf", "pdf"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
}


def confirmed_count(db: Session, offering_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Enrolment).where(
        Enrolment.offering_id == offering_id, Enrolment.status == E.CONFIRMED)) or 0


def get_enrolment(db: Session, enrolment_id: int) -> Enrolment:
    enrolment = db.get(Enrolment, enrolment_id)
    if enrolment is None:
        raise not_found("Enrolment")
    return enrolment


def requirements_for(db: Session, enrolment: Enrolment) -> list[EnrolmentRequirement]:
    level = enrolment.offering.course.education_level
    return list(db.scalars(select(EnrolmentRequirement).where(
        EnrolmentRequirement.is_active,
        or_(EnrolmentRequirement.education_level.is_(None), EnrolmentRequirement.education_level == level),
    ).order_by(EnrolmentRequirement.requirement_id)).all())


def apply(db: Session, student: Student, offering_id: int) -> Enrolment:
    offering = db.get(CourseOffering, offering_id)
    if offering is None or not offering.is_open:
        raise AppError(404, "NOT_FOUND", "Course offering not open", "Kozi hii haipo wazi kwa usajili")
    if student.current_status not in (StudentStatus.APPLICANT, StudentStatus.ACTIVE):
        raise rule_violation("Only applicants and active students can enrol",
                             "Ni waombaji na wanafunzi hai pekee wanaoweza kujisajili")
    if confirmed_count(db, offering_id) >= offering.capacity:
        raise AppError(409, "OFFERING_FULL", "No places left", "Nafasi zimejaa")
    enrolment = Enrolment(enrolment_no=next_number(db, "enrolment"), student_id=student.student_id,
                          offering_id=offering_id)
    db.add(enrolment)
    db.flush()                         # trigger: one active enrolment per student per year
    db.refresh(enrolment)
    return enrolment


def upload_document(db: Session, storage: Storage, enrolment: Enrolment, requirement_id: int,
                    file_name: str, content: bytes) -> EnrolmentDocument:
    if enrolment.status not in (E.PENDING, E.INVALID):
        raise rule_violation("Documents can only be changed before submission or after rejection",
                             "Nyaraka zinaweza kubadilishwa kabla ya kuwasilisha au baada ya kukataliwa",
                             status_code=409)
    requirement = db.get(EnrolmentRequirement, requirement_id)
    if requirement is None or requirement not in requirements_for(db, enrolment):
        raise rule_violation("This requirement does not apply to this enrolment",
                             "Hitaji hili halihusiani na usajili huu")
    if not 0 < len(content) <= get_settings().max_upload_bytes:
        raise rule_violation("File must be between 1 byte and 5 MB", "Faili liwe kati ya baiti 1 na MB 5")
    kind = next((v for magic, v in MAGIC.items() if content.startswith(magic)), None)
    if kind is None:
        raise rule_violation("Only PDF, JPG or PNG files are accepted", "Ni faili za PDF, JPG au PNG pekee")
    mime, ext = kind

    doc = db.scalar(select(EnrolmentDocument).where(EnrolmentDocument.enrolment_id == enrolment.enrolment_id,
                                                    EnrolmentDocument.requirement_id == requirement_id))
    if doc is not None and doc.status == DocumentStatus.VALID:
        raise rule_violation("This document is already valid", "Nyaraka hii tayari imethibitishwa",
                             status_code=409)
    key = f"enrolments/{enrolment.enrolment_id}/{requirement.code}/{uuid.uuid4().hex}.{ext}"
    storage.put(key, content, mime)
    values = dict(file_name=file_name[:255], storage_key=key, mime_type=mime, file_size_bytes=len(content),
                  sha256=hashlib.sha256(content).hexdigest(), status=DocumentStatus.PENDING, remarks=None,
                  validated_by=None, validated_at=None, uploaded_at=now_eat())
    if doc is None:
        doc = EnrolmentDocument(enrolment_id=enrolment.enrolment_id, requirement_id=requirement_id, **values)
        db.add(doc)
    else:
        for k, v in values.items():
            setattr(doc, k, v)
    db.flush()
    return doc


def submit(db: Session, enrolment: Enrolment) -> Enrolment:
    if enrolment.status not in (E.PENDING, E.INVALID):
        raise rule_violation("Only a pending or rejected application can be submitted",
                             "Maombi yanayosubiri au yaliyokataliwa pekee ndiyo yanaweza kuwasilishwa",
                             status_code=409)
    docs = {d.requirement_id: d for d in enrolment.documents}
    missing = [r.code for r in requirements_for(db, enrolment)
               if r.is_mandatory and (r.requirement_id not in docs
                                      or docs[r.requirement_id].status == DocumentStatus.INVALID)]
    if missing:
        raise rule_violation("Some mandatory documents are missing or still invalid",
                             "Baadhi ya nyaraka za lazima hazipo au bado si sahihi", missing=missing)
    enrolment.status = E.SUBMITTED
    enrolment.submitted_at = now_eat()
    db.flush()
    return enrolment


def refresh_status(db: Session, enrolment: Enrolment) -> Enrolment:
    """After validation: VALIDATED when every mandatory document is VALID, INVALID when any is INVALID."""
    docs = {d.requirement_id: d for d in enrolment.documents}
    if any(d.status == DocumentStatus.PENDING for d in docs.values()):
        return enrolment
    mandatory = [r for r in requirements_for(db, enrolment) if r.is_mandatory]
    if all(r.requirement_id in docs and docs[r.requirement_id].status == DocumentStatus.VALID for r in mandatory):
        enrolment.status = E.VALIDATED
    elif any(d.status == DocumentStatus.INVALID for d in docs.values()):
        enrolment.status = E.INVALID
    db.flush()
    return enrolment


def validate_document(db: Session, document_id: int, status: str, remarks: str | None,
                      validator: User) -> Enrolment:
    doc = db.get(EnrolmentDocument, document_id)
    if doc is None:
        raise not_found("Document")
    enrolment = doc.enrolment
    if enrolment.status != E.SUBMITTED:
        raise rule_violation("Only submitted applications can be validated",
                             "Maombi yaliyowasilishwa pekee ndiyo yanaweza kuhakikiwa", status_code=409)
    doc.status = DocumentStatus(status)
    doc.remarks = remarks
    doc.validated_by = validator.user_id
    doc.validated_at = now_eat()
    db.flush()
    return refresh_status(db, enrolment)


def term_to_bill(db: Session, offering: CourseOffering) -> Term | None:
    """The current or next term of the offering's year (the last term if the year is over)."""
    terms = db.scalars(select(Term).where(Term.academic_year_id == offering.academic_year_id)
                       .order_by(Term.term_no)).all()
    today = date.today()
    return next((t for t in terms if t.end_date >= today), terms[-1] if terms else None)


@dataclass
class Confirmation:
    enrolment: Enrolment
    schedules_linked: int
    invoice: Invoice | None


def confirm(db: Session, enrolment: Enrolment, stream: str, actor: User) -> Confirmation:
    if enrolment.status != E.VALIDATED:
        raise rule_violation("Only validated applications can be confirmed",
                             "Maombi yaliyohakikiwa pekee ndiyo yanaweza kuthibitishwa", status_code=409)
    offering = db.scalar(select(CourseOffering).where(CourseOffering.offering_id == enrolment.offering_id)
                         .with_for_update(of=CourseOffering))  # serialise the capacity check
    if confirmed_count(db, offering.offering_id) >= offering.capacity:
        raise AppError(409, "OFFERING_FULL", "No places left", "Nafasi zimejaa")

    enrolment.status = E.CONFIRMED
    enrolment.stream = stream
    enrolment.confirmed_at = now_eat()
    enrolment.confirmed_by = actor.user_id
    db.flush()

    sessions = db.scalars(select(Schedule.schedule_id).join(Term, Term.term_id == Schedule.term_id).where(
        Schedule.offering_id == offering.offering_id, Schedule.stream == stream,
        Term.academic_year_id == offering.academic_year_id)).all()
    for sid in sessions:
        db.add(EnrolmentSchedule(enrolment_id=enrolment.enrolment_id, schedule_id=sid))
    db.flush()                         # trigger: no student clash

    student = enrolment.student
    if student.current_status == StudentStatus.APPLICANT:
        students.change_status(db, student, StatusChangeIn(
            new_status=StudentStatus.ACTIVE,
            reason=f"Enrolment {enrolment.enrolment_no} confirmed"), actor, via_enrolment=True)

    term = term_to_bill(db, offering)
    invoice = payments.raise_invoice(db, student, offering, term, actor) if term else None
    return Confirmation(enrolment, len(sessions), invoice)


def cancel(db: Session, enrolment: Enrolment, reason: str) -> Enrolment:
    if enrolment.status in (E.CONFIRMED, E.CANCELLED):
        raise rule_violation("Confirmed or cancelled enrolments cannot be cancelled here",
                             "Usajili uliothibitishwa au kusitishwa hauwezi kusitishwa hapa", status_code=409)
    enrolment.status = E.CANCELLED
    enrolment.cancelled_at = now_eat()
    enrolment.cancel_reason = reason
    db.flush()
    return enrolment
```

## 11a.6 Transactions

```python
# File: backend/app/models/finance.py
"""Fee structures, invoices and the append-only transaction ledger."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (BigInteger, Column, Date, DateTime, ForeignKey, ForeignKeyConstraint, Identity, Integer,
                        Numeric, String, Table, func, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import (FeeItem, PaymentMethod, TransactionSource, TransactionStatus, TransactionType)

Money = Numeric(14, 2)


class FeeStructure(Base):
    __tablename__ = "fee_structures"

    fee_structure_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.term_id"))
    level_id: Mapped[int] = mapped_column(ForeignKey("class_levels.level_id"))
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.course_id"))
    fee_item: Mapped[FeeItem]
    description: Mapped[str] = mapped_column(String(120))
    amount_tzs: Mapped[Decimal] = mapped_column(Money)
    is_mandatory: Mapped[bool] = mapped_column(server_default=text("true"))


class Invoice(Base):
    __tablename__ = "invoices"

    invoice_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(20))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"))
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.term_id"))
    gepg_control_no: Mapped[str | None] = mapped_column(String(12))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    due_date: Mapped[date]
    issued_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))

    items: Mapped[list[InvoiceItem]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    invoice_item_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.invoice_id"))
    fee_structure_id: Mapped[int | None] = mapped_column(ForeignKey("fee_structures.fee_structure_id"))
    description: Mapped[str] = mapped_column(String(120))
    amount_tzs: Mapped[Decimal] = mapped_column(Money)


class Transaction(Base):
    """Never updated or deleted (DB trigger). Corrections are REVERSAL rows."""

    __tablename__ = "transactions"
    # The invoice must belong to the same student (composite FK, as in db/schema.sql).
    __table_args__ = (
        ForeignKeyConstraint(["invoice_id", "student_id"], ["invoices.invoice_id", "invoices.student_id"],
                             name="fk_transactions_invoice"),
    )

    trans_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    trans_no: Mapped[str] = mapped_column(String(20))
    trans_type: Mapped[TransactionType]
    trans_name: Mapped[str] = mapped_column(String(120))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"))
    invoice_id: Mapped[int | None] = mapped_column(BigInteger)
    amount_tzs: Mapped[Decimal] = mapped_column(Money)
    payment_method: Mapped[PaymentMethod | None]
    reference_no: Mapped[str | None] = mapped_column(String(50))
    payer_name: Mapped[str | None] = mapped_column(String(100))
    payer_phone: Mapped[str | None] = mapped_column(String(12))
    status: Mapped[TransactionStatus] = mapped_column(server_default=TransactionStatus.PENDING.value)
    source: Mapped[TransactionSource] = mapped_column(server_default=TransactionSource.MANUAL.value)
    reverses_trans_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.trans_id"))
    trans_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Read-only view: total, paid, balance and payment status per invoice.
invoice_balances = Table(
    "v_invoice_balances",
    Base.metadata,
    Column("invoice_id", BigInteger, primary_key=True),
    Column("invoice_no", String),
    Column("student_id", BigInteger),
    Column("term_id", Integer),
    Column("gepg_control_no", String),
    Column("due_date", Date),
    Column("total_tzs", Money),
    Column("paid_tzs", Money),
    Column("balance_tzs", Money),
    Column("payment_status", String),
    info={"is_view": True},
)
```

```python
# File: backend/app/schemas/transactions.py
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import PaymentMethod, TransactionSource, TransactionStatus, TransactionType
from app.schemas.common import TzPhone

AmountTzs = Field(gt=0, max_digits=14, decimal_places=2)


class PaymentIn(BaseModel):
    student_id: int
    invoice_id: int | None = None
    amount_tzs: Decimal = AmountTzs
    payment_method: PaymentMethod
    reference_no: str | None = Field(default=None, max_length=50)
    payer_name: str | None = Field(default=None, max_length=100)
    payer_phone: TzPhone | None = None
    trans_date: datetime | None = None
    trans_name: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def reference_unless_cash(self) -> "PaymentIn":
        if self.payment_method != PaymentMethod.CASH and not self.reference_no:
            raise ValueError("reference_no is required for non-cash payments")
        if self.payment_method == PaymentMethod.GEPG:
            raise ValueError("GePG payments are posted by the GePG callback, not manually")
        return self


class ReverseIn(BaseModel):
    reason: str = Field(min_length=5, max_length=100)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trans_id: int
    trans_no: str
    trans_type: TransactionType
    trans_name: str
    student_id: int
    invoice_id: int | None
    amount_tzs: Decimal
    payment_method: PaymentMethod | None
    reference_no: str | None
    payer_name: str | None
    payer_phone: str | None
    status: TransactionStatus
    source: TransactionSource
    reverses_trans_id: int | None
    trans_date: datetime
    recorded_by: int | None


class InvoiceBalanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invoice_id: int
    invoice_no: str
    term_id: int
    gepg_control_no: str | None
    due_date: date
    total_tzs: Decimal
    paid_tzs: Decimal
    balance_tzs: Decimal
    payment_status: str


class PaymentRecorded(BaseModel):
    transaction: TransactionOut
    invoice: InvoiceBalanceOut | None


class StatementOut(BaseModel):
    student_id: int
    admission_no: str
    student_name: str
    invoices: list[InvoiceBalanceOut]
    transactions: list[TransactionOut]
    total_balance_tzs: Decimal
```

```python
# File: backend/app/routers/transactions.py
"""UC-08 Record Transaction: manual payments, reversals, statements and the GePG callback."""
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select

from app.core.errors import AppError
from app.core.i18n import tzs
from app.deps import CurrentUser, DbSession, require_roles
from app.integrations import gepg
from app.models import Student, Transaction, User
from app.models.enums import STAFF_ROLES, PaymentMethod, Role
from app.schemas.transactions import (InvoiceBalanceOut, PaymentIn, PaymentRecorded, ReverseIn, StatementOut,
                                      TransactionOut)
from app.services import notify
from app.services import payments as svc
from app.services.common import EAT
from app.services.students import ensure_can_view, get_student
from app.tasks.payments import request_control_number

router = APIRouter(tags=["Transactions"])
Bursar = Depends(require_roles(Role.BURSAR, Role.ADMIN))


def _receipt_sms(db, trans: Transaction) -> None:
    student = db.get(Student, trans.student_id)
    balance = svc.invoice_balance(db, trans.invoice_id)["balance_tzs"] if trans.invoice_id else 0
    notify.sms_guardians(db, student, "payment_received", primary_only=True, amount=tzs(trans.amount_tzs),
                         trans_no=trans.trans_no, balance=tzs(balance))


@router.post("/transactions", response_model=PaymentRecorded, status_code=status.HTTP_201_CREATED)
def record_payment(body: PaymentIn, db: DbSession, user: User = Bursar):
    """Cash, bank, M-Pesa, Tigo Pesa or Airtel Money receipt. 409 if the reference was already posted."""
    trans = svc.record_manual(db, body, user)
    db.commit()
    _receipt_sms(db, trans)
    invoice = svc.invoice_balance(db, trans.invoice_id) if trans.invoice_id else None
    return PaymentRecorded(transaction=TransactionOut.model_validate(trans),
                           invoice=InvoiceBalanceOut.model_validate(dict(invoice)) if invoice else None)


@router.post("/transactions/{trans_id}/reverse", response_model=TransactionOut,
             status_code=status.HTTP_201_CREATED)
def reverse(trans_id: int, body: ReverseIn, db: DbSession, user: User = Depends(require_roles(Role.ADMIN))):
    """Never edits the original: posts a linked REVERSAL entry."""
    reversal = svc.reverse(db, trans_id, body.reason, user)
    db.commit()
    return reversal


@router.get("/transactions", response_model=list[TransactionOut],
            dependencies=[Depends(require_roles(*STAFF_ROLES))])
def transaction_history(db: DbSession, student_id: int | None = None, date_from: date | None = None,
                        date_to: date | None = None, method: PaymentMethod | None = None, limit: int = 200):
    stmt = select(Transaction).order_by(Transaction.trans_date.desc())
    if student_id:
        stmt = stmt.where(Transaction.student_id == student_id)
    if date_from:
        stmt = stmt.where(Transaction.trans_date >= datetime.combine(date_from, time.min, EAT))
    if date_to:
        stmt = stmt.where(Transaction.trans_date <= datetime.combine(date_to, time.max, EAT))
    if method:
        stmt = stmt.where(Transaction.payment_method == method)
    return db.scalars(stmt.limit(min(limit, 1000))).all()


@router.get("/students/{student_id}/statement", response_model=StatementOut)
def student_statement(student_id: int, db: DbSession, user: CurrentUser):
    """Invoices with balances and every transaction. Students/parents see only their own."""
    student = get_student(db, student_id)
    ensure_can_view(db, user, student)
    return StatementOut.model_validate(svc.statement(db, student), from_attributes=True)


@router.post("/invoices/{invoice_id}/control-number", status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Bursar])
def request_control_no(invoice_id: int):
    """Queue a GePG bill submission; the control number arrives by callback."""
    request_control_number.delay(invoice_id)
    return {"invoice_id": invoice_id, "status": "queued"}


@router.post("/payments/gepg/callback", include_in_schema=False)
async def gepg_payment_callback(request: Request, db: DbSession):
    """Signed GePG payment notification. Idempotent; always acknowledges a valid message."""
    body = await request.body()
    try:
        notification = gepg.parse_payment_notification(body)
    except gepg.SignatureError:
        raise AppError(401, "BAD_SIGNATURE", "Invalid GePG signature", "Sahihi ya GePG si sahihi")
    trans = svc.record_gateway_payment(db, notification)
    db.commit()
    if trans is not None:
        _receipt_sms(db, trans)
    return Response(gepg.acknowledgement(), media_type="application/xml")
```

```python
# File: backend/app/services/payments.py
"""UC-08 Record Transaction: invoices, manual payments, GePG payments, reversals, statements."""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import AppError, not_found, rule_violation
from app.integrations.gepg import PaymentNotification
from app.models import (CourseOffering, FeeStructure, Invoice, InvoiceItem, Student, Term, Transaction, User,
                        invoice_balances)
from app.models.enums import (PaymentMethod, TransactionSource, TransactionStatus, TransactionType)
from app.schemas.transactions import PaymentIn
from app.services.common import next_number, now_eat

INVOICE_DUE_DAYS = 30


def raise_invoice(db: Session, student: Student, offering: CourseOffering, term: Term,
                  actor: User | None) -> Invoice | None:
    """Bill the term's fee structure for the student's level and course. None if no fees apply."""
    fees = db.scalars(select(FeeStructure).where(
        FeeStructure.term_id == term.term_id, FeeStructure.level_id == offering.level_id,
        or_(FeeStructure.course_id.is_(None), FeeStructure.course_id == offering.course_id),
        FeeStructure.amount_tzs > 0,
    ).order_by(FeeStructure.fee_structure_id)).all()
    if not fees:
        return None
    invoice = Invoice(invoice_no=next_number(db, "invoice"), student_id=student.student_id, term_id=term.term_id,
                      due_date=max(term.start_date, now_eat().date()) + timedelta(days=INVOICE_DUE_DAYS),
                      issued_by=actor.user_id if actor else None,
                      items=[InvoiceItem(fee_structure_id=f.fee_structure_id, description=f.description,
                                         amount_tzs=f.amount_tzs) for f in fees])
    db.add(invoice)
    db.flush()
    return invoice


def invoice_balance(db: Session, invoice_id: int):
    return db.execute(select(invoice_balances).where(invoice_balances.c.invoice_id == invoice_id)).mappings().one()


def record_manual(db: Session, data: PaymentIn, actor: User) -> Transaction:
    student = db.get(Student, data.student_id)
    if student is None:
        raise not_found("Student")
    if data.invoice_id is not None:
        invoice = db.get(Invoice, data.invoice_id)
        if invoice is None or invoice.student_id != data.student_id:
            raise rule_violation("Invoice does not belong to this student", "Ankara si ya mwanafunzi huyu")
        if invoice.cancelled_at is not None:
            raise rule_violation("Invoice is cancelled", "Ankara imefutwa", status_code=409)
    trans = Transaction(
        trans_no=next_number(db, "transaction"), trans_type=TransactionType.PAYMENT,
        trans_name=data.trans_name or f"Fee payment ({data.payment_method.value})",
        student_id=data.student_id, invoice_id=data.invoice_id, amount_tzs=data.amount_tzs,
        payment_method=data.payment_method, reference_no=data.reference_no, payer_name=data.payer_name,
        payer_phone=data.payer_phone, status=TransactionStatus.COMPLETED, source=TransactionSource.MANUAL,
        trans_date=data.trans_date or now_eat(), recorded_by=actor.user_id,
    )
    db.add(trans)
    db.flush()                         # UNIQUE (payment_method, reference_no) -> 409 on double posting
    return trans


def reverse(db: Session, trans_id: int, reason: str, actor: User) -> Transaction:
    original = db.get(Transaction, trans_id)
    if original is None:
        raise not_found("Transaction")
    if original.trans_type not in (TransactionType.PAYMENT, TransactionType.WAIVER) \
            or original.status != TransactionStatus.COMPLETED:
        raise rule_violation("Only completed payments and waivers can be reversed",
                             "Malipo na misamaha iliyokamilika pekee ndiyo inaweza kubatilishwa", status_code=409)
    reversal = Transaction(
        trans_no=next_number(db, "transaction"), trans_type=TransactionType.REVERSAL,
        trans_name=f"Reversal of {original.trans_no}: {reason}"[:120], student_id=original.student_id,
        invoice_id=original.invoice_id, amount_tzs=original.amount_tzs, status=TransactionStatus.COMPLETED,
        source=TransactionSource.MANUAL, reverses_trans_id=original.trans_id, recorded_by=actor.user_id,
    )
    db.add(reversal)
    db.flush()                         # UNIQUE reverses_trans_id -> a transaction is reversed once
    return reversal


def record_gateway_payment(db: Session, n: PaymentNotification) -> Transaction | None:
    """Idempotent: the same GePG receipt posted twice creates one transaction. None = unknown bill."""
    invoice = db.scalar(select(Invoice).where(Invoice.gepg_control_no == n.control_no))
    if invoice is None:
        return None
    stmt = insert(Transaction).values(
        trans_no=next_number(db, "transaction"), trans_type=TransactionType.PAYMENT.value,
        trans_name=f"GePG payment {n.control_no} via {n.channel or 'PSP'}"[:120],
        student_id=invoice.student_id, invoice_id=invoice.invoice_id, amount_tzs=n.amount_tzs,
        payment_method=PaymentMethod.GEPG.value, reference_no=n.receipt_no, payer_name=n.payer_name,
        payer_phone=n.payer_phone, status=TransactionStatus.COMPLETED.value,
        source=TransactionSource.GEPG.value, trans_date=n.paid_at,
    ).on_conflict_do_nothing(constraint="uq_trans_reference").returning(Transaction.trans_id)
    trans_id = db.execute(stmt).scalar_one_or_none()
    if trans_id is None:
        trans_id = db.scalar(select(Transaction.trans_id).where(
            Transaction.payment_method == PaymentMethod.GEPG, Transaction.reference_no == n.receipt_no))
    return db.get(Transaction, trans_id)


def statement(db: Session, student: Student) -> dict:
    invoices = db.execute(select(invoice_balances).where(invoice_balances.c.student_id == student.student_id)
                          .order_by(invoice_balances.c.invoice_id)).mappings().all()
    transactions = db.scalars(select(Transaction).where(Transaction.student_id == student.student_id)
                              .order_by(Transaction.trans_date)).all()
    total = sum((i["balance_tzs"] for i in invoices if i["payment_status"] != "CANCELLED"), Decimal("0"))
    return {"student_id": student.student_id, "admission_no": student.admission_no,
            "student_name": student.user.full_name, "invoices": [dict(i) for i in invoices],
            "transactions": list(transactions), "total_balance_tzs": total}


def set_control_number(db: Session, invoice_id: int, control_no: str) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise not_found("Invoice")
    if invoice.gepg_control_no and invoice.gepg_control_no != control_no:
        raise AppError(409, "CONTROL_NO_EXISTS", "Invoice already has a control number",
                       "Ankara tayari ina namba ya malipo")
    invoice.gepg_control_no = control_no
    db.flush()
    return invoice
```

```python
# File: backend/app/integrations/gepg.py
"""GePG (Government Electronic Payment Gateway) adapter.

Element names follow the GePG Service Provider integration pattern (gepgPmtSpInfo / PymtTrxInf).
Check them against the specification version issued to the school with its SP code and
certificates; only this module changes if they differ.
"""
import base64
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import lru_cache

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from app.core.config import get_settings
from app.services.common import EAT

log = logging.getLogger(__name__)

ACK_SUCCESS = "7101"


class SignatureError(Exception):
    pass


@dataclass
class PaymentNotification:
    control_no: str
    receipt_no: str
    amount_tzs: Decimal
    paid_at: datetime
    payer_name: str | None
    payer_phone: str | None
    channel: str | None


@lru_cache
def _gepg_public_key():
    with open(get_settings().gepg_public_cert_path, "rb") as fh:
        return x509.load_pem_x509_certificate(fh.read()).public_key()


def verify_signature(signed_xml: bytes, signature_b64: str) -> None:
    try:
        _gepg_public_key().verify(base64.b64decode(signature_b64), signed_xml,
                                  padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError) as exc:
        raise SignatureError("GePG signature check failed") from exc


def _text(node: ET.Element, tag: str) -> str | None:
    found = node.find(tag)
    return found.text.strip() if found is not None and found.text else None


def _normalise_phone(raw: str | None) -> str | None:
    digits = "".join(ch for ch in raw or "" if ch.isdigit())
    if len(digits) == 10 and digits.startswith("0"):
        digits = "255" + digits[1:]
    return digits if len(digits) == 12 and digits.startswith("255") else None


def _signed_part(body: bytes) -> bytes:
    """The exact bytes GePG signed: the <gepgPmtSpInfo> element as received (no re-serialising)."""
    start, end_tag = body.find(b"<gepgPmtSpInfo>"), b"</gepgPmtSpInfo>"
    end = body.find(end_tag)
    if start < 0 or end < 0:
        raise SignatureError("Malformed GePG message")
    return body[start:end + len(end_tag)]


def _paid_at(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(EAT)
    value = datetime.fromisoformat(raw)
    return value if value.tzinfo else value.replace(tzinfo=EAT)   # GePG times are East Africa Time


def parse_payment_notification(body: bytes) -> PaymentNotification:
    """Verify the signature over <gepgPmtSpInfo> and return the payment details."""
    root = ET.fromstring(body)          # expat in Python >= 3.7.1 refuses external entities
    signature = _text(root, "gepgSignature")
    if signature is None:
        raise SignatureError("Missing gepgSignature")
    verify_signature(_signed_part(body), signature)
    trx = root.find("gepgPmtSpInfo/PymtTrxInf")
    if trx is None:
        raise SignatureError("Missing PymtTrxInf")
    return PaymentNotification(
        control_no=_text(trx, "PayCtrNum") or "",
        receipt_no=_text(trx, "PspReceiptNumber") or _text(trx, "TrxId") or "",
        amount_tzs=Decimal(_text(trx, "PaidAmt") or "0"),
        paid_at=_paid_at(_text(trx, "TrxDtTm")),
        payer_name=_text(trx, "PyrName"),
        payer_phone=_normalise_phone(_text(trx, "PyrCellNum")),
        channel=_text(trx, "UsdPayChnl"),
    )


def acknowledgement(status_code: str = ACK_SUCCESS) -> str:
    # In production the acknowledgement is signed with the school's private key as well.
    return f"<Gepg><gepgPmtSpInfoAck><TrxStsCode>{status_code}</TrxStsCode></gepgPmtSpInfoAck></Gepg>"


def request_control_number(invoice_no: str, amount_tzs: Decimal, payer_name: str, payer_phone: str | None,
                           due_date: str) -> str | None:
    """Submit a bill. Returns None here; GePG answers asynchronously with the control number."""
    settings = get_settings()
    if not settings.gepg_enabled:
        log.info("GePG disabled: bill %s for TZS %s not sent", invoice_no, amount_tzs)
        return None
    raise NotImplementedError("Build and sign the gepgBillSubReq message per the issued GePG specification")
```

## 11a.7 Shared: app, database, security

```python
# File: backend/app/main.py
"""FastAPI application. Interactive docs: /docs (Swagger UI) and /redoc."""
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.routers import auth, courses, enrolments, instructors, schedules, students, transactions

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="School Management System API",
        description="Mfumo wa Usimamizi wa Shule — students, courses, instructors, schedules, "
                    "enrolment and transactions (TZS, GePG, mobile money).",
        version="1.0.0",
        docs_url="/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def request_id_and_headers(request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        try:
            request.state.request_id = str(uuid.UUID(incoming))
        except ValueError:
            request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    register_error_handlers(app)
    for module in (auth, students, courses, instructors, schedules, enrolments, transactions):
        app.include_router(module.router, prefix=API_PREFIX)

    @app.get("/health", tags=["Health"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()
```

```python
# File: backend/app/db.py
"""Engine, session and the audit context that feeds the fn_audit_row trigger."""
import enum
from collections.abc import Iterator

from sqlalchemy import Enum as SAEnum
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    # Enumerations are VARCHAR + CHECK in the database, not native ENUM types.
    type_annotation_map = {
        enum.Enum: SAEnum(enum.Enum, native_enum=False, create_constraint=False, length=20),
    }


_AUDIT_SQL = text(
    "SELECT set_config('app.user_id', :user_id, true),"
    "       set_config('app.user_role', :user_role, true),"
    "       set_config('app.client_ip', :client_ip, true),"
    "       set_config('app.request_id', :request_id, true)"
)


def set_audit_context(
    session: Session,
    *,
    user_id: int | None,
    user_role: str | None,
    client_ip: str | None,
    request_id: str | None,
) -> None:
    """Remember who is acting; applied with SET LOCAL to every transaction of this session."""
    ctx = {
        "user_id": str(user_id or ""),
        "user_role": user_role or "",
        "client_ip": client_ip or "",
        "request_id": request_id or "",
    }
    session.info["audit"] = ctx
    if session.in_transaction():
        session.execute(_AUDIT_SQL, ctx)


@event.listens_for(Session, "after_begin")
def _apply_audit_context(session: Session, transaction, connection) -> None:
    ctx = session.info.get("audit")
    if ctx:
        connection.execute(_AUDIT_SQL, ctx)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

```python
# File: backend/app/deps.py
"""Request dependencies: DB session, current user, role checks, audit context."""
import ipaddress
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.errors import AppError, forbidden
from app.core.security import decode_access_token
from app.db import get_db, set_audit_context
from app.models import User
from app.models.enums import Role
from app.services.storage import LocalStorage, Storage

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def client_ip(request: Request) -> str | None:
    """Real client address (Uvicorn runs with --proxy-headers behind Nginx); None if not a valid IP,
    because it is stored in INET columns."""
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


def get_current_user(request: Request, db: DbSession, token: str = Depends(oauth2_scheme)) -> User:
    unauthorised = AppError(401, "NOT_AUTHENTICATED", "Please log in again", "Tafadhali ingia tena",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise unauthorised
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise unauthorised
    set_audit_context(db, user_id=user.user_id, user_role=user.role.value,
                      client_ip=client_ip(request), request_id=request.state.request_id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    """Dependency factory: allow only the given roles."""
    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise forbidden()
        return user
    return checker


def get_storage() -> Storage:
    return LocalStorage()
```

```python
# File: backend/app/core/security.py
"""Password hashing (Argon2id), JWT access tokens and opaque refresh tokens."""
import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

# Argon2id with pwdlib's recommended parameters (m=64 MiB, t=3, p=4).
_hasher = PasswordHash.recommended()

# Used when the username does not exist, so a failed login takes the same time
# whether or not the account exists (no user enumeration by timing).
DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")

PASSWORD_RULE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{10,128}$")


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> tuple[bool, str | None]:
    """Return (valid, new_hash). new_hash is set when the stored hash uses old parameters."""
    return _hasher.verify_and_update(raw, hashed)


def is_strong_password(raw: str) -> bool:
    return bool(PASSWORD_RULE.match(raw))


def generate_temporary_password() -> str:
    # 12 characters, always contains a letter and a digit
    return secrets.token_urlsafe(9)[:10] + str(secrets.randbelow(10)) + "a"


def create_access_token(user_id: int, role: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "typ"]},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return payload


def sha256_hex(value: str | bytes) -> str:
    data = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """Return (token for the client, SHA-256 hash for the database)."""
    raw = secrets.token_urlsafe(48)
    return raw, sha256_hex(raw)
```

```python
# File: backend/app/core/errors.py
"""Bilingual API errors and mapping of PostgreSQL errors to HTTP status codes."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message_en: str,
        message_sw: str,
        extra: dict | None = None,
        headers: dict | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message_en = message_en
        self.message_sw = message_sw
        self.extra = extra or {}
        self.headers = headers

    def body(self) -> dict:
        return {"detail": {"code": self.code, "message_en": self.message_en,
                           "message_sw": self.message_sw, **self.extra}}


def not_found(entity: str) -> AppError:
    return AppError(404, "NOT_FOUND", f"{entity} not found", f"{entity} haikupatikana")


def forbidden() -> AppError:
    return AppError(403, "FORBIDDEN", "You do not have permission for this action",
                    "Huna ruhusa ya kufanya kitendo hiki")


def rule_violation(message_en: str, message_sw: str, status_code: int = 422, **extra) -> AppError:
    return AppError(status_code, "RULE_VIOLATION", message_en, message_sw, extra)


# SQLSTATE -> (HTTP status, code, English, Kiswahili)
_DB_ERRORS = {
    "23505": (409, "DUPLICATE", "A record with these details already exists",
              "Taarifa hizi tayari zipo"),
    "23P01": (409, "CLASH", "This conflicts with an existing booking",
              "Hii inagongana na ratiba iliyopo"),
    "23503": (409, "INVALID_REFERENCE", "A referenced record does not exist or is still in use",
              "Taarifa inayorejelewa haipo au bado inatumika"),
    "23514": (422, "CHECK_FAILED", "A value is outside the allowed range or format",
              "Thamani haiko katika kiwango au muundo unaoruhusiwa"),
    "22000": (422, "INVALID_DATA", "Invalid data", "Data si sahihi"),
    "22P02": (422, "INVALID_DATA", "Invalid data", "Data si sahihi"),
    "P0001": (409, "RULE_VIOLATION", "This change is not allowed",
              "Mabadiliko haya hayaruhusiwi"),
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(DBAPIError)
    async def _db_error(_: Request, exc: DBAPIError) -> JSONResponse:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate not in _DB_ERRORS:
            raise exc
        status, code, en, sw = _DB_ERRORS[sqlstate]
        diag = getattr(exc.orig, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        db_message = getattr(diag, "message_primary", None)
        detail = {"code": code, "message_en": en, "message_sw": sw, "constraint": constraint}
        if sqlstate == "P0001":
            detail["reason"] = db_message
        return JSONResponse({"detail": detail}, status_code=status)
```

```python
# File: backend/app/routers/auth.py
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.deps import CurrentUser, DbSession, client_ip
from app.schemas.auth import MeOut, PasswordChangeIn, RefreshIn, TokenPair
from app.services import auth as svc
from app.services.common import RequestMeta

router = APIRouter(prefix="/auth", tags=["Authentication"])


def request_meta(request: Request) -> RequestMeta:
    return RequestMeta(ip=client_ip(request), user_agent=request.headers.get("user-agent"),
                       request_id=request.state.request_id)


Meta = Annotated[RequestMeta, Depends(request_meta)]


@router.post("/login", response_model=TokenPair)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession, meta: Meta):
    """Username (or email) + password. 401 on bad credentials, 423 while locked."""
    return svc.login(db, form.username, form.password, meta)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshIn, db: DbSession, meta: Meta):
    """Rotate the refresh token. Re-using an old token revokes the whole session chain."""
    return svc.refresh(db, body.refresh_token, meta)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshIn, user: CurrentUser, db: DbSession, meta: Meta):
    svc.logout(db, body.refresh_token, user, meta)


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser):
    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordChangeIn, user: CurrentUser, db: DbSession, meta: Meta):
    svc.change_password(db, user, body.current_password, body.new_password, meta)
```

```python
# File: backend/app/services/auth.py
"""Login with lockout, refresh-token rotation with reuse detection, logout, password change."""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, rule_violation
from app.core.security import (DUMMY_HASH, create_access_token, hash_password, is_strong_password,
                               new_refresh_token, sha256_hex, verify_password)
from app.db import set_audit_context
from app.models import RefreshToken, User
from app.schemas.auth import TokenPair
from app.services.common import RequestMeta, record_event

INVALID_LOGIN = AppError(401, "INVALID_CREDENTIALS", "Invalid username or password",
                         "Jina la mtumiaji au nenosiri si sahihi")
INVALID_TOKEN = AppError(401, "INVALID_TOKEN", "Session expired, please log in again",
                         "Muda wa kuingia umeisha, tafadhali ingia tena")


def _issue_tokens(db: Session, user: User, family_id: uuid.UUID, meta: RequestMeta) -> TokenPair:
    settings = get_settings()
    raw, digest = new_refresh_token()
    db.add(RefreshToken(
        user_id=user.user_id, token_hash=digest, family_id=family_id,
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        user_agent=(meta.user_agent or "")[:255] or None, ip_address=meta.ip,
    ))
    return TokenPair(access_token=create_access_token(user.user_id, user.role.value), refresh_token=raw,
                     expires_in=settings.access_token_minutes * 60)


def login(db: Session, username: str, password: str, meta: RequestMeta) -> TokenPair:
    settings = get_settings()
    name = username.strip().lower()
    user = db.scalar(select(User).where(or_(func.lower(User.username) == name, func.lower(User.email) == name)))
    now = datetime.now(UTC)

    if user is None or not user.is_active:
        verify_password(password, DUMMY_HASH)                 # same cost as a real check
        record_event(db, "LOGIN_FAILED", meta, details={"username": name[:50], "reason": "unknown_or_inactive"})
        db.commit()
        raise INVALID_LOGIN

    set_audit_context(db, user_id=user.user_id, user_role=user.role.value,
                      client_ip=meta.ip, request_id=meta.request_id)

    if user.locked_until and user.locked_until > now:
        record_event(db, "LOGIN_FAILED", meta, actor=user, entity_id=user.user_id, details={"reason": "locked"})
        db.commit()
        raise AppError(423, "ACCOUNT_LOCKED", "Account locked after too many failed attempts",
                       "Akaunti imefungwa kwa majaribio mengi yasiyo sahihi",
                       {"locked_until": user.locked_until.isoformat()})

    valid, new_hash = verify_password(password, user.password_hash)
    if not valid:
        user.failed_login_count += 1
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_login_count = 0
        record_event(db, "LOGIN_FAILED", meta, actor=user, entity_id=user.user_id, details={"reason": "password"})
        db.commit()
        raise INVALID_LOGIN

    if new_hash:                                              # Argon2 parameters were upgraded
        user.password_hash = new_hash
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    tokens = _issue_tokens(db, user, uuid.uuid4(), meta)
    record_event(db, "LOGIN", meta, actor=user, entity_id=user.user_id)
    db.commit()
    return tokens


def refresh(db: Session, raw_token: str, meta: RequestMeta) -> TokenPair:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw_token))
                      .with_for_update())
    now = datetime.now(UTC)
    if token is None:
        raise INVALID_TOKEN
    user = db.get(User, token.user_id)
    if token.revoked_at is not None:
        # A rotated token was used again: assume theft and end every session in this chain.
        db.execute(update(RefreshToken)
                   .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
                   .values(revoked_at=now))
        record_event(db, "TOKEN_REUSE", meta, actor=user, entity_id=token.user_id,
                     details={"family_id": str(token.family_id)})
        db.commit()
        raise INVALID_TOKEN
    if token.expires_at <= now or user is None or not user.is_active:
        raise INVALID_TOKEN
    token.revoked_at = now
    tokens = _issue_tokens(db, user, token.family_id, meta)
    record_event(db, "TOKEN_REFRESH", meta, actor=user, entity_id=user.user_id)
    db.commit()
    return tokens


def logout(db: Session, raw_token: str, user: User, meta: RequestMeta) -> None:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw_token),
                                                 RefreshToken.user_id == user.user_id))
    if token is not None:
        db.execute(update(RefreshToken)
                   .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
                   .values(revoked_at=datetime.now(UTC)))
    record_event(db, "LOGOUT", meta, actor=user, entity_id=user.user_id)
    db.commit()


def revoke_all_tokens(db: Session, user_id: int) -> None:
    db.execute(update(RefreshToken)
               .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=datetime.now(UTC)))


def change_password(db: Session, user: User, current: str, new: str, meta: RequestMeta) -> None:
    valid, _ = verify_password(current, user.password_hash)
    if not valid:
        raise INVALID_LOGIN
    if not is_strong_password(new):
        raise rule_violation("Password must be at least 10 characters with letters and digits",
                             "Nenosiri liwe na herufi 10 au zaidi, zikiwemo herufi na tarakimu")
    user.password_hash = hash_password(new)
    revoke_all_tokens(db, user.user_id)
    record_event(db, "PASSWORD_CHANGE", meta, actor=user, entity_id=user.user_id)
    db.commit()
```
