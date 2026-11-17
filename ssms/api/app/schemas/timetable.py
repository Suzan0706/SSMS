"""Teaching assignments, timetable slots and generation, exam sessions and papers."""

import uuid
from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ExamKind


class AssignmentItem(BaseModel):
    subject_id: uuid.UUID
    staff_id: uuid.UUID


class AssignmentOut(BaseModel):
    id: uuid.UUID
    academic_year_id: uuid.UUID
    stream_id: uuid.UUID
    subject_id: uuid.UUID
    subject_code: str
    staff_id: uuid.UUID
    staff_name: str


class SlotIn(BaseModel):
    term_id: uuid.UUID
    stream_id: uuid.UUID
    subject_id: uuid.UUID
    staff_id: uuid.UUID
    room_id: uuid.UUID
    day_of_week: int = Field(ge=1, le=6, description="1 Monday … 6 Saturday")
    time_start: time
    time_end: time

    @model_validator(mode="after")
    def _times(self):
        if self.time_end <= self.time_start:
            raise ValueError("invalid_value")
        return self


class SlotCheckIn(SlotIn):
    exclude_slot_id: uuid.UUID | None = Field(default=None, description="The slot being edited")


class SlotUpdate(BaseModel):
    subject_id: uuid.UUID | None = None
    staff_id: uuid.UUID | None = None
    room_id: uuid.UUID | None = None
    day_of_week: int | None = Field(default=None, ge=1, le=6)
    time_start: time | None = None
    time_end: time | None = None


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    term_id: uuid.UUID
    stream_id: uuid.UUID
    subject_id: uuid.UUID
    staff_id: uuid.UUID
    room_id: uuid.UUID
    day_of_week: int
    time_start: time
    time_end: time


class Conflict(BaseModel):
    kind: str = Field(description="teacher, room or stream")
    slot_id: uuid.UUID
    stream_id: uuid.UUID
    subject_id: uuid.UUID
    time_start: time
    time_end: time


class Problem(BaseModel):
    code: str = Field(
        description="not_assigned, not_qualified, not_in_curriculum, room_type, room_capacity, teacher_load, "
        "teacher_inactive"
    )
    detail: str


class FreePeriod(BaseModel):
    time_start: time
    time_end: time


class CheckOut(BaseModel):
    ok: bool
    conflicts: list[Conflict]
    problems: list[Problem]
    free_periods: list[FreePeriod]


class GenerateIn(BaseModel):
    term_id: uuid.UUID
    stream_ids: list[uuid.UUID] = Field(min_length=1, max_length=60)
    persist: bool = False
    replace: bool = Field(default=False, description="Remove the existing slots of these streams first")


class Unplaced(BaseModel):
    stream_id: uuid.UUID
    subject_id: uuid.UUID
    periods: int
    reason: str = Field(description="not_assigned, not_qualified, no_room, no_free_period")


class GenerateOut(BaseModel):
    placed: list[SlotIn]
    unplaced: list[Unplaced]
    persisted: bool


class ExamSessionIn(BaseModel):
    term_id: uuid.UUID
    name_en: str = Field(min_length=2, max_length=60)
    name_sw: str = Field(min_length=2, max_length=60)
    kind: ExamKind
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date < self.start_date:
            raise ValueError("invalid_value")
        return self


class ExamSessionUpdate(BaseModel):
    name_en: str | None = Field(default=None, min_length=2, max_length=60)
    name_sw: str | None = Field(default=None, min_length=2, max_length=60)
    start_date: date | None = None
    end_date: date | None = None


class ExamSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    term_id: uuid.UUID
    name_en: str
    name_sw: str
    kind: str
    start_date: date
    end_date: date


class ExamIn(BaseModel):
    exam_session_id: uuid.UUID
    class_id: uuid.UUID
    subject_id: uuid.UUID
    room_id: uuid.UUID | None = None
    exam_date: date
    time_start: time
    time_end: time

    @model_validator(mode="after")
    def _times(self):
        if self.time_end <= self.time_start:
            raise ValueError("invalid_value")
        return self


class ExamUpdate(BaseModel):
    room_id: uuid.UUID | None = None
    exam_date: date | None = None
    time_start: time | None = None
    time_end: time | None = None


class ExamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    exam_session_id: uuid.UUID
    class_id: uuid.UUID
    subject_id: uuid.UUID
    room_id: uuid.UUID | None
    exam_date: date
    time_start: time
    time_end: time
