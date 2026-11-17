"""Curriculum and teaching: subjects, combinations, class subjects, rooms, class teachers, assignments, components."""

import uuid
from decimal import Decimal

from sqlalchemy import Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin
from app.models.enums import ComponentCode, RoomType


class Subject(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "subjects"
    code: Mapped[str] = mapped_column(String(10))
    necta_code: Mapped[str | None] = mapped_column(String(5))
    name_en: Mapped[str] = mapped_column(String(80))
    name_sw: Mapped[str] = mapped_column(String(80))
    department_id: Mapped[uuid.UUID | None]
    room_type: Mapped[RoomType] = mapped_column(default=RoomType.CLASSROOM)


class Combination(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "combinations"
    education_level_id: Mapped[uuid.UUID]
    code: Mapped[str] = mapped_column(String(6))
    name_en: Mapped[str] = mapped_column(String(100))
    name_sw: Mapped[str] = mapped_column(String(100))


class CombinationSubject(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "combination_subjects"
    combination_id: Mapped[uuid.UUID]
    subject_id: Mapped[uuid.UUID]
    is_principal: Mapped[bool] = mapped_column(default=True)


class ClassSubject(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "class_subjects"
    class_id: Mapped[uuid.UUID]
    subject_id: Mapped[uuid.UUID]
    is_compulsory: Mapped[bool] = mapped_column(default=True)
    periods_per_week: Mapped[int] = mapped_column(SmallInteger, default=4)


class Room(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "rooms"
    code: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(60))
    room_type: Mapped[RoomType] = mapped_column(default=RoomType.CLASSROOM)
    capacity: Mapped[int] = mapped_column(SmallInteger)


class EquipmentItem(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "equipment_items"
    name: Mapped[str] = mapped_column(String(60))


class RoomEquipment(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "room_equipment"
    room_id: Mapped[uuid.UUID]
    equipment_id: Mapped[uuid.UUID]
    quantity: Mapped[int] = mapped_column(SmallInteger, default=1)


class StreamClassTeacher(TenantMixin, Base):
    __tablename__ = "stream_class_teachers"
    stream_id: Mapped[uuid.UUID]
    academic_year_id: Mapped[uuid.UUID]
    staff_id: Mapped[uuid.UUID]


class TeachingAssignment(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "teaching_assignments"
    academic_year_id: Mapped[uuid.UUID]
    stream_id: Mapped[uuid.UUID]
    subject_id: Mapped[uuid.UUID]
    staff_id: Mapped[uuid.UUID]


class StaffSubject(TenantMixin, SoftDeleteMixin, Base):
    """A subject the teacher is qualified to teach; timetable slots and the generator require it."""

    __tablename__ = "staff_subjects"
    staff_id: Mapped[uuid.UUID]
    subject_id: Mapped[uuid.UUID]


class AssessmentComponent(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "assessment_components"
    term_id: Mapped[uuid.UUID]
    education_level_id: Mapped[uuid.UUID]
    subject_id: Mapped[uuid.UUID | None]
    code: Mapped[ComponentCode]
    name_en: Mapped[str] = mapped_column(String(40))
    name_sw: Mapped[str] = mapped_column(String(40))
    max_score: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 2))
