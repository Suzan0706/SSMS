"""Registers, offline sync, gate devices and cards, attendance reports."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import AttendanceStatus, CardKind, DeviceKind


class RegisterStudent(BaseModel):
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    status: AttendanceStatus | None
    captured_at: datetime | None
    gate_in_at: datetime | None = Field(description="First gate tap today, if any")


class RegisterOut(BaseModel):
    session_id: uuid.UUID | None
    session_date: date
    stream_id: uuid.UUID
    stream_label: str
    closed_at: datetime | None
    school_day: bool
    reason: str | None = Field(description="weekend, holiday or outside_term when school_day is false")
    students: list[RegisterStudent]


class MyStream(BaseModel):
    stream_id: uuid.UUID
    label: str
    class_teacher: bool


class AttendanceItem(BaseModel):
    client_record_id: uuid.UUID
    session_date: date
    stream_id: uuid.UUID
    student_id: uuid.UUID
    status: AttendanceStatus
    captured_at: datetime = Field(description="When the teacher marked it (device clock)")


class SyncIn(BaseModel):
    items: list[AttendanceItem] = Field(min_length=1, max_length=500)


class ServerRecord(BaseModel):
    status: AttendanceStatus
    captured_at: datetime


class SyncResult(BaseModel):
    client_record_id: uuid.UUID
    result: Literal["synced", "conflict", "error"]
    code: str | None = None
    server: ServerRecord | None = None


class SyncOut(BaseModel):
    results: list[SyncResult]


class StreamReportRow(BaseModel):
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    present: int
    late: int
    absent: int
    excused: int
    rate_pct: float | None = Field(description="(present + late) / marked days, None when never marked")


class StreamReportOut(BaseModel):
    stream_id: uuid.UUID
    date_from: date
    date_to: date
    register_days: int
    rows: list[StreamReportRow]


class StudentDay(BaseModel):
    day: date
    status: AttendanceStatus | None
    gate_in_at: datetime | None


class StudentAttendanceOut(BaseModel):
    student_id: uuid.UUID
    date_from: date
    date_to: date
    present: int
    late: int
    absent: int
    excused: int
    days: list[StudentDay]
    absent_this_week: int


class ChronicRow(BaseModel):
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    stream_label: str | None
    week_start: date
    days_absent: int


# ---------------------------------------------------------------- devices and cards


class DeviceIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    kind: DeviceKind
    location: str | None = Field(default=None, max_length=100)


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    location: str | None = Field(default=None, max_length=100)
    status: Literal["ACTIVE", "DISABLED"] | None = None


class DeviceOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    location: str | None
    status: str
    last_seen_at: datetime | None


class DeviceCreated(DeviceOut):
    api_key: str = Field(description="Shown once; only its SHA-256 is stored")


class CardIn(BaseModel):
    student_id: uuid.UUID
    kind: CardKind
    token: str = Field(min_length=4, max_length=128, description="Card UID or QR payload; only its SHA-256 is stored")


class CardUpdate(BaseModel):
    status: Literal["LOST", "REVOKED"]


class CardOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    kind: str
    status: str
    issued_at: datetime


class Tap(BaseModel):
    token: str = Field(min_length=4, max_length=128)
    captured_at: datetime
    client_record_id: uuid.UUID


class TapsIn(BaseModel):
    taps: list[Tap] = Field(min_length=1, max_length=200)


class TapResult(BaseModel):
    client_record_id: uuid.UUID
    result: Literal["present", "late", "duplicate", "unknown_card", "not_school_day", "out_of_window"]
    student_name: str | None = None


class TapsOut(BaseModel):
    results: list[TapResult]
