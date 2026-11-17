from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import DocumentStatus, EnrolmentStatus
from app.schemas.common import Stream
from app.schemas.courses import RequirementOut


class EnrolmentCreate(BaseModel):
    offering_id: int
    student_id: int | None = Field(default=None, description="Registrar only; students apply for themselves")


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    requirement_id: int
    file_name: str
    mime_type: str
    file_size_bytes: int
    sha256: str
    status: DocumentStatus
    remarks: str | None
    uploaded_at: datetime
    validated_at: datetime | None


class EnrolmentOut(BaseModel):
    enrolment_id: int
    enrolment_no: str
    student_id: int
    offering_id: int
    course_code: str
    level_code: str
    academic_year: str
    stream: str | None
    status: EnrolmentStatus
    applied_at: datetime
    submitted_at: datetime | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    requirements: list[RequirementOut] = []
    documents: list[DocumentOut] = []


class DocumentValidateIn(BaseModel):
    status: Literal["VALID", "INVALID"]
    remarks: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def invalid_needs_remarks(self) -> "DocumentValidateIn":
        if self.status == "INVALID" and not self.remarks:
            raise ValueError("remarks are required when a document is INVALID")
        return self


class ConfirmIn(BaseModel):
    stream: Stream


class CancelIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


class ConfirmOut(BaseModel):
    enrolment: EnrolmentOut
    schedules_linked: int
    invoice_no: str | None
