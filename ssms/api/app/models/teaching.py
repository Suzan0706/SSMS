"""Study materials and homework with submissions (migration 0014)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin


class StudyMaterial(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "study_materials"
    academic_year_id: Mapped[uuid.UUID]
    subject_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(String(1000))
    file_id: Mapped[uuid.UUID | None]
    link_url: Mapped[str | None] = mapped_column(String(500))
    published_by: Mapped[uuid.UUID]


class StudyMaterialStream(TenantMixin, Base):
    __tablename__ = "study_material_streams"
    material_id: Mapped[uuid.UUID]
    stream_id: Mapped[uuid.UUID]


class Homework(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "homework"
    academic_year_id: Mapped[uuid.UUID]
    subject_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(150))
    instructions: Mapped[str] = mapped_column(String(4000))
    file_id: Mapped[uuid.UUID | None]
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notify_parents: Mapped[bool] = mapped_column(default=False)
    set_by: Mapped[uuid.UUID]


class HomeworkStream(TenantMixin, Base):
    __tablename__ = "homework_streams"
    homework_id: Mapped[uuid.UUID]
    stream_id: Mapped[uuid.UUID]


class HomeworkSubmission(TenantMixin, Base):
    __tablename__ = "homework_submissions"
    homework_id: Mapped[uuid.UUID]
    enrolment_id: Mapped[uuid.UUID]
    body: Mapped[str | None] = mapped_column(String(8000))
    file_id: Mapped[uuid.UUID | None]
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_late: Mapped[bool] = mapped_column(default=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    feedback: Mapped[str | None] = mapped_column(String(2000))
    marked_by: Mapped[uuid.UUID | None]
    marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
