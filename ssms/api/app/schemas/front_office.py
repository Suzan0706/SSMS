"""Front office, school calendar, staff attendance and leave (FR-77, FR-80, FR-81, FR-99)."""

import uuid
from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.phone import normalise_phone
from app.schemas.enrolment import ApplicationIn

Source = Literal["WALK_IN", "PHONE", "WEBSITE", "REFERRAL", "OTHER"]
Audience = Literal["ALL", "STAFF", "PARENTS", "STUDENTS"]
StaffStatus = Literal["PRESENT", "ABSENT", "LATE", "ON_LEAVE"]


class InquiryIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    class_id: uuid.UUID | None = None
    source: Source = "WALK_IN"
    message: str | None = Field(default=None, max_length=500)
    follow_up_on: date | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return normalise_phone(value)
        except ValueError:
            raise ValueError("invalid_phone") from None

    @model_validator(mode="after")
    def _contact(self):
        if not self.phone and not self.email:
            raise ValueError("phone or email is required")
        return self


class InquiryUpdate(BaseModel):
    class_id: uuid.UUID | None = None
    follow_up_on: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    status: Literal["OPEN", "CLOSED"] | None = None


class InquiryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    class_id: uuid.UUID | None
    source: str
    message: str | None
    follow_up_on: date | None
    notes: str | None
    status: str
    application_id: uuid.UUID | None
    created_at: datetime


class ConvertIn(BaseModel):
    """The enrolment application made from an inquiry (the same fields as POST /enrolment-applications)."""

    application: ApplicationIn


class EventIn(BaseModel):
    title_en: str = Field(min_length=2, max_length=120)
    title_sw: str = Field(min_length=2, max_length=120)
    starts_on: date
    ends_on: date
    audience: Audience = "ALL"

    @model_validator(mode="after")
    def _dates(self):
        if self.ends_on < self.starts_on:
            raise ValueError("ends_on is before starts_on")
        return self


class EventOut(EventIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class StaffDayRow(BaseModel):
    staff_id: uuid.UUID
    staff_no: str
    full_name: str
    status: StaffStatus | None = Field(description="Recorded status; None = not marked yet")
    on_leave: bool = Field(description="Approved leave covers this day")
    time_in: time | None
    time_out: time | None
    note: str | None


class StaffMark(BaseModel):
    staff_id: uuid.UUID
    status: StaffStatus
    time_in: time | None = None
    time_out: time | None = None
    note: str | None = Field(default=None, max_length=200)


class StaffDayIn(BaseModel):
    marks: list[StaffMark] = Field(min_length=1, max_length=500)


class StaffMonthRow(BaseModel):
    staff_id: uuid.UUID
    full_name: str
    present: int
    late: int
    absent: int
    on_leave: int


class LeaveTypeIn(BaseModel):
    name_en: str = Field(min_length=2, max_length=60)
    name_sw: str = Field(min_length=2, max_length=60)
    applies_to: Literal["STAFF", "STUDENT"]
    days_per_year: int | None = Field(default=None, ge=1, le=366)


class LeaveTypeOut(LeaveTypeIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class LeaveIn(BaseModel):
    leave_type_id: uuid.UUID
    student_id: uuid.UUID | None = Field(default=None, description="For a student; omit to request leave for yourself")
    start_date: date
    end_date: date
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date is before start_date")
        return self


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=300)


class LeaveOut(BaseModel):
    id: uuid.UUID
    leave_type_id: uuid.UUID
    type_name: str
    person: str
    staff_id: uuid.UUID | None
    student_id: uuid.UUID | None
    start_date: date
    end_date: date
    days: int
    reason: str
    status: str
    decision_note: str | None
    requested_by_me: bool
    created_at: datetime
