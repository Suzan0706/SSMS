"""Reports, compliance exports, data-subject requests."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import DsrStatus, DsrType


class ReportFilters(BaseModel):
    academic_year_id: uuid.UUID | None = None
    term_id: uuid.UUID | None = None
    class_id: uuid.UUID | None = None
    stream_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    status: str | None = Field(default=None, max_length=20)


class ReportPreview(BaseModel):
    report: str
    columns: list[str]
    rows: list[dict] = Field(description="First 50 rows; values as text")
    total: int


class ExportIn(ReportFilters):
    format: Literal["xlsx", "csv", "pdf"] = "xlsx"


class ComplianceIn(BaseModel):
    templates: list[Literal["ENROLMENT", "ATTENDANCE", "RESULTS", "STAFF"]] = Field(min_length=1)
    academic_year_id: uuid.UUID
    format: Literal["xlsx", "csv", "pdf"] = "xlsx"


class DsrIn(BaseModel):
    subject_user_id: uuid.UUID
    request_type: DsrType
    details: str | None = Field(default=None, max_length=500)


class DsrUpdate(BaseModel):
    status: Literal[DsrStatus.IN_PROGRESS, DsrStatus.COMPLETED, DsrStatus.REJECTED]
    note: str | None = Field(default=None, max_length=300)


class DsrOut(BaseModel):
    id: uuid.UUID
    subject_user_id: uuid.UUID
    subject_name: str
    request_type: str
    status: str
    details: str | None
    requested_at: datetime
    due_at: datetime
    completed_at: datetime | None
    overdue: bool
    has_file: bool
