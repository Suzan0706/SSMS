"""Enrolment workflow and promotions."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import Gender, Relationship
from app.schemas.people import GuardianLinkIn, Identifier, PastDate, PersonName


class RequirementIn(BaseModel):
    education_level_id: uuid.UUID | None = Field(default=None, description="Empty = every level")
    class_id: uuid.UUID | None = Field(default=None, description="Empty = every class of the level")
    name_en: str = Field(min_length=2, max_length=100)
    name_sw: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    is_required: bool = True

    @model_validator(mode="after")
    def _level_or_class(self):
        if self.education_level_id and self.class_id:
            raise ValueError("Name the level or the class, not both: a class already belongs to one level")
        return self


class RequirementOut(RequirementIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class OfferingClass(BaseModel):
    class_id: uuid.UUID
    code: str
    name_en: str
    name_sw: str
    places_left: int
    requirements: list[RequirementOut]


class OfferingCombination(BaseModel):
    combination_id: uuid.UUID
    code: str
    name_en: str
    name_sw: str


class OfferingsOut(BaseModel):
    school_name: str
    academic_year: str
    open: bool
    classes: list[OfferingClass]
    combinations: list[OfferingCombination]


class ApplicantIn(BaseModel):
    first_name: PersonName
    middle_name: PersonName | None = None
    last_name: PersonName
    gender: Gender
    date_of_birth: PastDate
    birth_cert_no: Identifier | None = None


class ApplicationIn(BaseModel):
    class_id: uuid.UUID
    combination_id: uuid.UUID | None = None
    academic_year_id: uuid.UUID
    applicant: ApplicantIn
    guardians: list[GuardianLinkIn] = Field(
        default_factory=list, max_length=4, description="Staff path. A signed-in parent is added automatically."
    )
    relationship: Relationship = Field(
        default=Relationship.GUARDIAN, description="Parent path: the signed-in parent's relationship to the child"
    )
    consent_data_processing: bool

    @model_validator(mode="after")
    def _consent(self):
        if not self.consent_data_processing:
            raise ValueError("required")
        return self


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    requirement_id: uuid.UUID
    file_name: str
    mime_type: str
    size_bytes: int
    validation_status: str
    comment: str | None
    validated_at: datetime | None


class ChecklistItem(BaseModel):
    requirement_id: uuid.UUID
    name_en: str
    name_sw: str
    is_required: bool
    document_id: uuid.UUID | None
    status: str = Field(description="MISSING, PENDING, VALID or INVALID")


class ApplicantOut(BaseModel):
    id: uuid.UUID
    admission_no: str
    full_name: str
    gender: str
    date_of_birth: date | None


class ApplicationOut(BaseModel):
    id: uuid.UUID
    application_no: str
    status: str
    class_id: uuid.UUID
    combination_id: uuid.UUID | None
    academic_year_id: uuid.UUID
    submitted_at: datetime | None
    decided_at: datetime | None
    decision_reason: str | None
    student: ApplicantOut
    checklist: list[ChecklistItem]
    documents: list[DocumentOut]


class ApplicationListItem(BaseModel):
    id: uuid.UUID
    application_no: str
    status: str
    class_id: uuid.UUID
    student_name: str
    created_at: datetime
    submitted_at: datetime | None


class DocumentDecisionIn(BaseModel):
    status: str = Field(pattern=r"^(VALID|INVALID)$")
    comment: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _comment(self):
        if self.status == "INVALID" and not (self.comment or "").strip():
            raise ValueError("required")  # the family must learn what to fix
        return self


class ApproveIn(BaseModel):
    stream_id: uuid.UUID
    combination_id: uuid.UUID | None = None
    note: str = Field(default="Approved", min_length=2, max_length=300)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class PromotionIn(BaseModel):
    academic_year_from: uuid.UUID
    academic_year_to: uuid.UUID
    class_id: uuid.UUID | None = Field(default=None, description="Empty = every class")
    repeaters: list[uuid.UUID] = Field(default_factory=list, max_length=500, description="Student ids who repeat")

    @model_validator(mode="after")
    def _years(self):
        if self.academic_year_from == self.academic_year_to:
            raise ValueError("invalid_value")
        return self
