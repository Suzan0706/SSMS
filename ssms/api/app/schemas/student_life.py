"""Discipline, clubs, library, health records."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ActivityKind, ActivityRole, DisciplineCategory, HealthKind


class DisciplineIn(BaseModel):
    student_id: uuid.UUID
    incident_date: date
    category: DisciplineCategory
    description: str = Field(min_length=3, max_length=1000)
    action_taken: str | None = Field(default=None, max_length=500)
    notify_parent: bool = Field(default=True, description="SMS to the primary guardian (if they receive SMS)")


class DisciplineUpdate(BaseModel):
    action_taken: str | None = Field(default=None, max_length=500)
    resolution: str | None = Field(default=None, min_length=3, max_length=500)
    resolve: bool = Field(default=False, description="Mark RESOLVED (a resolution is required)")


class DisciplineOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    incident_date: date
    category: str
    description: str
    action_taken: str | None
    resolution: str | None
    status: str
    parent_notified_at: datetime | None
    recorded_by: uuid.UUID
    recorded_by_name: str


class ActivityIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    kind: ActivityKind
    patron_staff_id: uuid.UUID | None = None
    meeting_day: int | None = Field(default=None, ge=1, le=7, description="1 = Monday")


class ActivityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    patron_staff_id: uuid.UUID | None = None
    meeting_day: int | None = Field(default=None, ge=1, le=7)


class ActivityOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    patron_staff_id: uuid.UUID | None
    patron_name: str | None
    meeting_day: int | None
    members: int


class MemberIn(BaseModel):
    student_id: uuid.UUID
    role: ActivityRole = ActivityRole.MEMBER


class MemberOut(BaseModel):
    id: uuid.UUID
    activity_id: uuid.UUID
    activity_name: str
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    role: str
    academic_year_id: uuid.UUID


class BookIn(BaseModel):
    isbn: str | None = Field(default=None, pattern=r"^[0-9X-]{10,17}$")
    title: str = Field(min_length=2, max_length=200)
    author: str | None = Field(default=None, max_length=150)
    subject_id: uuid.UUID | None = None
    copies: int = Field(default=1, ge=0, le=10000)
    category_id: uuid.UUID | None = None
    publisher_id: uuid.UUID | None = None


class BookUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    author: str | None = Field(default=None, max_length=150)
    copies: int | None = Field(default=None, ge=0, le=10000)
    category_id: uuid.UUID | None = None
    publisher_id: uuid.UUID | None = None


class BookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    isbn: str | None
    title: str
    author: str | None
    subject_id: uuid.UUID | None
    category_id: uuid.UUID | None = None
    publisher_id: uuid.UUID | None = None
    copies: int
    on_loan: int = 0
    available: int = 0


class LoanIn(BaseModel):
    book_id: uuid.UUID
    borrower_user_id: uuid.UUID | None = None
    admission_no: str | None = Field(
        default=None, max_length=20, description="A student borrower, instead of the user id"
    )
    card_no: str | None = Field(default=None, max_length=20, description="A library card, instead of the user id")
    due_date: date | None = Field(default=None, description="Default 14 days")


class LoanOut(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    title: str
    borrower_user_id: uuid.UUID
    borrower_name: str
    loaned_at: datetime
    due_date: date
    returned_at: datetime | None
    overdue: bool
    fine_tzs: Decimal | None = Field(default=None, description="Charged on the term invoice for a late return")


class HealthIn(BaseModel):
    record_date: date
    kind: HealthKind
    notes: str = Field(min_length=2, max_length=1000)


class HealthOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    record_date: date
    kind: str
    notes: str | None = Field(description="None when the stored text cannot be decrypted")
    recorded_by_name: str
    created_at: datetime
