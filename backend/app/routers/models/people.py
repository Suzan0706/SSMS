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
