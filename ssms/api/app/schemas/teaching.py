"""Study materials, homework, lesson attendance and the monthly sheet (FR-82, FR-83, FR-90 .. FR-93)."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

LessonStatus = Literal["PRESENT", "ABSENT", "LATE", "EXCUSED"]


class MaterialIn(BaseModel):
    subject_id: uuid.UUID
    stream_ids: list[uuid.UUID] = Field(min_length=1, max_length=40)
    title: str = Field(min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    file_id: uuid.UUID | None = None
    link_url: HttpUrl | None = Field(default=None, description="https only")

    @model_validator(mode="after")
    def _one_source(self):
        if (self.file_id is None) == (self.link_url is None):
            raise ValueError("give a file or a link, not both")
        if self.link_url is not None and self.link_url.scheme != "https":
            raise ValueError("the link must start with https://")
        return self


class MaterialOut(BaseModel):
    id: uuid.UUID
    subject_id: uuid.UUID
    subject: str
    title: str
    description: str | None
    streams: list[str]
    file_name: str | None
    link_url: str | None
    published_by: str
    created_at: datetime
    mine: bool


class HomeworkIn(BaseModel):
    subject_id: uuid.UUID
    stream_ids: list[uuid.UUID] = Field(min_length=1, max_length=40)
    title: str = Field(min_length=2, max_length=150)
    instructions: str = Field(min_length=3, max_length=4000)
    file_id: uuid.UUID | None = None
    max_score: Decimal | None = Field(default=None, gt=0, le=1000, decimal_places=1)
    due_at: datetime
    notify_parents: bool = False


class HomeworkOut(BaseModel):
    id: uuid.UUID
    subject_id: uuid.UUID
    subject: str
    title: str
    instructions: str
    file_name: str | None
    max_score: Decimal | None
    due_at: datetime
    streams: list[str]
    set_by: str
    created_at: datetime
    expected: int = Field(description="Students in the target streams")
    submitted: int
    marked: int
    mine: bool


class MySubmission(BaseModel):
    id: uuid.UUID
    submitted_at: datetime
    is_late: bool
    file_name: str | None
    body: str | None
    score: Decimal | None
    feedback: str | None
    marked_at: datetime | None


class StudentHomework(BaseModel):
    """One homework as a student (or the student's parent) sees it."""

    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    subject: str
    title: str
    instructions: str
    file_name: str | None
    max_score: Decimal | None
    due_at: datetime
    overdue: bool
    submission: MySubmission | None


class SubmissionIn(BaseModel):
    body: str | None = Field(default=None, max_length=8000)
    file_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _content(self):
        if not (self.body and self.body.strip()) and self.file_id is None:
            raise ValueError("write an answer or attach a file")
        return self


class MarkIn(BaseModel):
    score: Decimal | None = Field(default=None, ge=0, le=1000, decimal_places=1)
    feedback: str | None = Field(default=None, max_length=2000)


class RosterRow(BaseModel):
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    stream: str
    submission: MySubmission | None


class LessonOut(BaseModel):
    slot_id: uuid.UUID
    time_start: time
    time_end: time
    subject: str
    stream: str
    marked: int
    expected: int


class LessonMarkRow(BaseModel):
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    status: LessonStatus | None


class LessonMark(BaseModel):
    student_id: uuid.UUID
    status: LessonStatus


class LessonIn(BaseModel):
    marks: list[LessonMark] = Field(min_length=1, max_length=200)


class SheetRow(BaseModel):
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    marks: dict[str, str] = Field(description="ISO date → P, A, L or E")
    present: int
    absent: int
    late: int
    excused: int


class MonthlySheet(BaseModel):
    stream: str
    year: int
    month: int
    days: list[date] = Field(description="Days with a class register")
    rows: list[SheetRow]
