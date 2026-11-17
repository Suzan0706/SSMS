"""Student life: discipline records, clubs and memberships, library books and loans, health records
(design/sql/schema.sql §11). Library copies are enforced by fn_capacity_guard; health notes are encrypted."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin
from app.models.enums import ActivityKind, ActivityRole, DisciplineCategory, DisciplineStatus, HealthKind


class DisciplineRecord(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "discipline_records"
    student_id: Mapped[uuid.UUID]
    incident_date: Mapped[date]
    category: Mapped[DisciplineCategory]
    description: Mapped[str] = mapped_column(String(1000))
    action_taken: Mapped[str | None] = mapped_column(String(500))
    resolution: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[DisciplineStatus] = mapped_column(default=DisciplineStatus.OPEN)
    parent_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[uuid.UUID]


class Activity(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "extracurricular_activities"
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[ActivityKind]
    patron_staff_id: Mapped[uuid.UUID | None]
    meeting_day: Mapped[int | None] = mapped_column(SmallInteger)


class StudentActivity(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "student_activities"
    student_id: Mapped[uuid.UUID]
    activity_id: Mapped[uuid.UUID]
    academic_year_id: Mapped[uuid.UUID]
    role: Mapped[ActivityRole] = mapped_column(default=ActivityRole.MEMBER)


class LibraryBook(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "library_books"
    isbn: Mapped[str | None] = mapped_column(String(17))
    title: Mapped[str] = mapped_column(String(200))
    author: Mapped[str | None] = mapped_column(String(150))
    subject_id: Mapped[uuid.UUID | None]
    copies: Mapped[int] = mapped_column(SmallInteger, default=1)
    category_id: Mapped[uuid.UUID | None]
    publisher_id: Mapped[uuid.UUID | None]


class LibraryLoan(TenantMixin, Base):
    __tablename__ = "library_loans"
    book_id: Mapped[uuid.UUID]
    borrower_user_id: Mapped[uuid.UUID]
    loaned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())
    due_date: Mapped[date]
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by: Mapped[uuid.UUID]
    copy_id: Mapped[uuid.UUID | None]  # every loan since migration 0019 is of one physical copy
    renewals: Mapped[int] = mapped_column(SmallInteger, default=0)
    return_condition: Mapped[str | None] = mapped_column(String(10))  # GOOD | DAMAGED | LOST
    charge_tzs: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # for a damaged or lost copy


class HealthRecord(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "health_records"
    student_id: Mapped[uuid.UUID]
    record_date: Mapped[date]
    kind: Mapped[HealthKind]
    notes_enc: Mapped[bytes] = mapped_column(LargeBinary)
    recorded_by: Mapped[uuid.UUID]


class LibraryCategory(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "library_categories"
    name: Mapped[str] = mapped_column(String(80))


class LibraryPublisher(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "library_publishers"
    name: Mapped[str] = mapped_column(String(120))


class LibraryCopy(TenantMixin, Base):
    """One physical copy of a book, with its own accession number. On loan is not a status: an open loan says so."""

    __tablename__ = "library_copies"
    book_id: Mapped[uuid.UUID]
    accession_no: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), default="AVAILABLE")  # AVAILABLE | DAMAGED | LOST | WITHDRAWN
    condition: Mapped[str] = mapped_column(String(10), default="GOOD")  # GOOD | FAIR | DAMAGED
    shelf: Mapped[str | None] = mapped_column(String(30))
    acquired_on: Mapped[date | None]
    note: Mapped[str | None] = mapped_column(String(200))


class LibrarySettings(TimestampMixin, Base):
    """The borrowing rules of one school, and its next accession number."""

    __tablename__ = "library_settings"
    school_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    loan_days_student: Mapped[int] = mapped_column(SmallInteger, default=14)
    loan_days_staff: Mapped[int] = mapped_column(SmallInteger, default=30)
    max_loans_student: Mapped[int] = mapped_column(SmallInteger, default=2)
    max_loans_staff: Mapped[int] = mapped_column(SmallInteger, default=5)
    max_renewals: Mapped[int] = mapped_column(SmallInteger, default=1)
    block_when_overdue: Mapped[bool] = mapped_column(Boolean, default=True)
    next_accession: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None]


class LibraryCard(TenantMixin, Base):
    """A borrower's library card; one live card per person, numbers unique per school."""

    __tablename__ = "library_cards"
    user_id: Mapped[uuid.UUID]
    card_no: Mapped[str] = mapped_column(String(20))
    issued_on: Mapped[date]
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
