"""Academic structure needed in Phase 1 (onboarding defaults, admission into a stream)."""

import uuid
from datetime import date

from sqlalchemy import SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin
from app.models.enums import EducationLevelCode, EnrolmentStatus


class EducationLevel(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "education_levels"
    code: Mapped[EducationLevelCode]
    name_en: Mapped[str] = mapped_column(String(40))
    name_sw: Mapped[str] = mapped_column(String(40))
    sort_order: Mapped[int] = mapped_column(SmallInteger)


class AcademicYear(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "academic_years"
    name: Mapped[str] = mapped_column(String(9))
    start_date: Mapped[date]
    end_date: Mapped[date]
    is_current: Mapped[bool] = mapped_column(default=False)


class Term(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "terms"
    academic_year_id: Mapped[uuid.UUID]
    term_no: Mapped[int] = mapped_column(SmallInteger)
    name_en: Mapped[str] = mapped_column(String(30))
    name_sw: Mapped[str] = mapped_column(String(30))
    start_date: Mapped[date]
    end_date: Mapped[date]


class PublicHoliday(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "public_holidays"
    holiday_date: Mapped[date]
    name_en: Mapped[str] = mapped_column(String(80))
    name_sw: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(15), default="NATIONAL")


class SchoolClass(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "classes"
    education_level_id: Mapped[uuid.UUID]
    code: Mapped[str] = mapped_column(String(6))
    name_en: Mapped[str] = mapped_column(String(30))
    name_sw: Mapped[str] = mapped_column(String(30))
    sort_order: Mapped[int] = mapped_column(SmallInteger)
    next_class_id: Mapped[uuid.UUID | None]


class Stream(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "streams"
    class_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(10))
    capacity: Mapped[int] = mapped_column(SmallInteger)
    home_room_id: Mapped[uuid.UUID | None]


class Enrolment(TenantMixin, Base):
    __tablename__ = "enrolments"
    student_id: Mapped[uuid.UUID]
    stream_id: Mapped[uuid.UUID]
    academic_year_id: Mapped[uuid.UUID]
    combination_id: Mapped[uuid.UUID | None]
    application_id: Mapped[uuid.UUID | None]
    status: Mapped[EnrolmentStatus] = mapped_column(default=EnrolmentStatus.ACTIVE)
    started_on: Mapped[date]
    ended_on: Mapped[date | None]


class GradingScheme(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "grading_schemes"
    education_level_id: Mapped[uuid.UUID]
    academic_year_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(SmallInteger, default=1)
    best_n_subjects: Mapped[int | None] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(default=True)


class GradeBand(TenantMixin, Base):
    __tablename__ = "grade_bands"
    grading_scheme_id: Mapped[uuid.UUID]
    letter: Mapped[str] = mapped_column(String(2))
    min_score: Mapped[int] = mapped_column(SmallInteger)
    max_score: Mapped[int] = mapped_column(SmallInteger)
    points: Mapped[int] = mapped_column(SmallInteger)
    remark_en: Mapped[str] = mapped_column(String(20))
    remark_sw: Mapped[str] = mapped_column(String(20))


class DivisionRule(TenantMixin, Base):
    __tablename__ = "division_rules"
    grading_scheme_id: Mapped[uuid.UUID]
    division: Mapped[str] = mapped_column(String(3))
    min_points: Mapped[int] = mapped_column(SmallInteger)
    max_points: Mapped[int] = mapped_column(SmallInteger)
