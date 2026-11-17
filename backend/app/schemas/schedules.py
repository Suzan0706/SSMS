from datetime import time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import Stream


class ScheduleIn(BaseModel):
    offering_id: int
    stream: Stream = "A"
    term_id: int
    subject_id: int
    instructor_id: int
    room_id: int
    day_of_week: int = Field(ge=1, le=6, description="1 = Monday ... 6 = Saturday")
    time_start: time
    time_end: time

    @model_validator(mode="after")
    def end_after_start(self) -> "ScheduleIn":
        if self.time_end <= self.time_start:
            raise ValueError("time_end must be after time_start")
        return self


class ScheduleOut(ScheduleIn):
    model_config = ConfigDict(from_attributes=True)

    schedule_id: int


class ConflictOut(BaseModel):
    kind: str = Field(description="INSTRUCTOR, ROOM, CLASS or STUDENT")
    schedule_id: int
    message: str


class CheckResult(BaseModel):
    ok: bool
    conflicts: list[ConflictOut]
    problems: list[str] = Field(description="Rule failures: qualification, room type, capacity, load")


class GenerateIn(BaseModel):
    term_id: int
    offering_ids: list[int] = Field(min_length=1)
    streams: list[Stream] = ["A"]
    persist: bool = Field(default=False, description="false = return a draft only")


class DraftLesson(BaseModel):
    offering_id: int
    stream: str
    subject_id: int
    instructor_id: int | None
    room_id: int | None
    day_of_week: int | None
    time_start: time | None
    time_end: time | None


class GenerateOut(BaseModel):
    placed: list[DraftLesson]
    unplaced: list[DraftLesson]
    persisted: bool
