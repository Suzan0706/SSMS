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
