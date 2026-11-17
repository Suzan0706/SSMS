"""Request and response models for school settings, users, staff, students and guardians.

Personal identifiers (phone, birth certificate number, NIDA) are accepted on input but never returned in lists.
Phones are masked (****0021) unless the caller holds guardians.manage; identifiers are read through the audited
/students/{id}/identifiers endpoint only.
"""

import re
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.core.phone import normalise_phone
from app.models.enums import (
    ConsentChannel,
    ConsentPurpose,
    EmploymentType,
    Gender,
    QualificationLevel,
    Relationship,
    StaffStatus,
    StudentStatus,
)


def _phone(value: str) -> str:
    try:
        return normalise_phone(value)
    except ValueError:
        raise ValueError("invalid_phone") from None


def _name(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        raise ValueError("required")
    return value


def _nida(value: str) -> str:
    digits = re.sub(r"[\s-]", "", value)
    if not re.fullmatch(r"\d{20}", digits):  # NIDA number: 20 digits
        raise ValueError("invalid_nida")
    return digits


def _identifier(value: str) -> str:
    value = re.sub(r"\s+", "", value).upper()
    if not re.fullmatch(r"[A-Z0-9/-]{4,30}", value):
        raise ValueError("invalid_value")
    return value


def _past(value: date) -> date:
    if value > date.today():
        raise ValueError("future_date")
    return value


Phone = Annotated[str, AfterValidator(_phone)]
PersonName = Annotated[str, Field(min_length=1, max_length=50), AfterValidator(_name)]
Nida = Annotated[str, AfterValidator(_nida)]
Identifier = Annotated[str, AfterValidator(_identifier)]
PastDate = Annotated[date, AfterValidator(_past)]
Language = Annotated[str, Field(pattern=r"^(sw|en)$")]


# ---------------------------------------------------------------- school


class SchoolSettingsIn(BaseModel):
    motto: str | None = Field(default=None, max_length=150)
    postal_address: str | None = Field(default=None, max_length=150)
    physical_address: str | None = Field(default=None, max_length=200)
    phone: Phone | None = None
    email: EmailStr | None = None
    medium_of_instruction: str | None = Field(default=None, pattern=r"^(KISWAHILI|ENGLISH)$")
    default_language: Language | None = None
    sms_sender_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9 -]{3,11}$")
    gepg_sp_code: str | None = Field(default=None, max_length=10)
    gepg_sub_sp_code: str | None = Field(default=None, max_length=10)
    absence_sms_cutoff: time | None = None
    is_open_for_enrolment: bool | None = None
    admission_prefix: str | None = Field(default=None, pattern=r"^[A-Z]{2,4}$")


class SchoolSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    motto: str | None
    logo_file_key: str | None
    postal_address: str | None
    physical_address: str | None
    phone: str | None
    email: str | None
    medium_of_instruction: str
    default_language: str
    sms_sender_id: str | None
    gepg_sp_code: str | None
    gepg_sub_sp_code: str | None
    absence_sms_cutoff: time
    is_open_for_enrolment: bool
    admission_prefix: str


class SchoolOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    registration_no: str | None
    ownership: str
    region: str
    district: str
    status: str
    settings: SchoolSettingsOut


# ---------------------------------------------------------------- users


class UserListItem(BaseModel):
    id: uuid.UUID
    full_name: str
    username: str | None
    status: str
    roles: list[str]
    phone: str | None
    last_login_at: datetime | None


class UserUpdateIn(BaseModel):
    status: str | None = Field(default=None, pattern=r"^(ACTIVE|DISABLED)$")
    preferred_language: Language | None = None


class RoleIn(BaseModel):
    role_code: str = Field(pattern=r"^[a-z_]{3,30}$", examples=["teacher"])


class TemporaryPasswordOut(BaseModel):
    temporary_password: str = Field(description="Shown once; the user must change it at the next login")


# ---------------------------------------------------------------- staff


class PersonIn(BaseModel):
    first_name: PersonName
    middle_name: PersonName | None = None
    last_name: PersonName
    gender: Gender
    date_of_birth: PastDate | None = None
    phone: Phone
    email: EmailStr | None = None
    preferred_language: Language = "sw"


class StaffCreateIn(BaseModel):
    person: PersonIn
    staff_no: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9/-]+$")
    check_no: str | None = Field(default=None, max_length=20)
    department_id: uuid.UUID | None = None
    designation_id: uuid.UUID | None = None
    employment_type: EmploymentType = EmploymentType.PERMANENT
    employment_date: PastDate | None = None
    salary_tzs: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    max_periods_per_week: int = Field(default=30, ge=1, le=50)
    username: str | None = Field(default=None, pattern=r"^[a-z0-9._-]{3,50}$")
    roles: list[str] = Field(default_factory=lambda: ["teacher"], max_length=5)


class StaffUpdateIn(BaseModel):
    first_name: PersonName | None = None
    middle_name: PersonName | None = None
    last_name: PersonName | None = None
    phone: Phone | None = None
    email: EmailStr | None = None
    check_no: str | None = Field(default=None, max_length=20)
    department_id: uuid.UUID | None = None
    designation_id: uuid.UUID | None = None
    employment_type: EmploymentType | None = None
    salary_tzs: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    max_periods_per_week: int | None = Field(default=None, ge=1, le=50)
    status: StaffStatus | None = None


class QualificationIn(BaseModel):
    level: QualificationLevel
    title: str = Field(min_length=2, max_length=120)
    institution: str = Field(min_length=2, max_length=120)
    year_awarded: int = Field(ge=1950, le=2100)


class QualificationOut(QualificationIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class StaffOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    staff_no: str
    check_no: str | None
    full_name: str
    gender: str
    phone: str | None
    email: str | None
    username: str | None
    department_id: uuid.UUID | None
    designation_id: uuid.UUID | None
    employment_type: str
    employment_date: date | None
    salary_tzs: Decimal | None = Field(description="Only with payroll.read")
    max_periods_per_week: int
    status: str
    roles: list[str] = []
    qualifications: list[QualificationOut] = []


class StaffListItem(BaseModel):
    id: uuid.UUID
    staff_no: str
    full_name: str
    department_id: uuid.UUID | None
    designation_id: uuid.UUID | None
    employment_type: str
    status: str


class StaffSubjectsIn(BaseModel):
    subject_ids: list[uuid.UUID] = Field(max_length=100, description="Replaces the teacher's whole list")


class StaffSubjectOut(BaseModel):
    subject_id: uuid.UUID
    code: str
    name_en: str
    name_sw: str


class StaffCreatedOut(StaffOut):
    temporary_password: str


class CodeNameIn(BaseModel):
    code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Z0-9_]+$")
    name_en: str = Field(min_length=2, max_length=80)
    name_sw: str = Field(min_length=2, max_length=80)


class DepartmentIn(CodeNameIn):
    code: str = Field(min_length=2, max_length=10, pattern=r"^[A-Z0-9_]+$")
    head_staff_id: uuid.UUID | None = None


class DepartmentUpdateIn(BaseModel):
    name_en: str | None = Field(default=None, min_length=2, max_length=80)
    name_sw: str | None = Field(default=None, min_length=2, max_length=80)
    head_staff_id: uuid.UUID | None = None


class DesignationIn(CodeNameIn):
    name_en: str = Field(min_length=2, max_length=60)
    name_sw: str = Field(min_length=2, max_length=60)


class CodeNameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name_en: str
    name_sw: str


class DepartmentOut(CodeNameOut):
    head_staff_id: uuid.UUID | None


# ---------------------------------------------------------------- guardians and students


class GuardianLinkIn(BaseModel):
    """Either an existing guardian (guardian_id) or a new person. A known phone reuses the existing guardian."""

    guardian_id: uuid.UUID | None = None
    first_name: PersonName | None = None
    middle_name: PersonName | None = None
    last_name: PersonName | None = None
    gender: Gender | None = None
    phone: Phone | None = None
    email: EmailStr | None = None
    occupation: str | None = Field(default=None, max_length=80)
    relationship: Relationship
    is_primary: bool = False
    receives_sms: bool = True
    sms_consent: bool = Field(default=False, description="Guardian agreed to receive SMS (PDPA consent record)")

    @model_validator(mode="after")
    def _who(self):
        if self.guardian_id is None and not (self.first_name and self.last_name and self.gender and self.phone):
            raise ValueError("required")
        return self


class StudentCreateIn(BaseModel):
    first_name: PersonName
    middle_name: PersonName | None = None
    last_name: PersonName
    gender: Gender
    date_of_birth: PastDate
    birth_cert_no: Identifier | None = Field(default=None, description="RITA birth certificate number")
    nida: Nida | None = None
    prem_number: str | None = Field(default=None, max_length=20)
    admission_date: PastDate | None = None
    stream_id: uuid.UUID | None = Field(default=None, description="Enrol now (status ACTIVE); omit for APPLICANT")
    preferred_language: Language = "sw"
    consent_data_processing: bool = Field(description="Primary guardian consents to processing (PDPA 2022)")
    guardians: list[GuardianLinkIn] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _rules(self):
        age = (date.today() - self.date_of_birth).days // 365
        if not 3 <= age <= 30:
            raise ValueError("student_age")
        if not self.consent_data_processing:
            raise ValueError("required")
        return self


class StudentUpdateIn(BaseModel):
    first_name: PersonName | None = None
    middle_name: PersonName | None = None
    last_name: PersonName | None = None
    gender: Gender | None = None
    date_of_birth: PastDate | None = None
    birth_cert_no: Identifier | None = None
    nida: Nida | None = None
    prem_number: str | None = Field(default=None, max_length=20)
    preferred_language: Language | None = None


class StatusChangeIn(BaseModel):
    new_status: StudentStatus
    reason: str = Field(min_length=3, max_length=300)
    effective_date: PastDate


class StatusHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    old_status: str | None
    new_status: str
    reason: str
    effective_date: date


class GuardianOut(BaseModel):
    guardian_id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    phone: str | None
    relationship: str
    is_primary: bool
    receives_sms: bool


class EnrolmentOut(BaseModel):
    stream_id: uuid.UUID
    stream_name: str
    class_id: uuid.UUID
    class_code: str
    academic_year: str


class StudentOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    admission_no: str
    first_name: str
    middle_name: str | None
    last_name: str
    full_name: str
    gender: str
    date_of_birth: date | None
    status: str
    admission_date: date | None
    prem_number: str | None
    has_birth_cert_no: bool
    has_nida: bool
    preferred_language: str
    enrolment: EnrolmentOut | None
    guardians: list[GuardianOut]


class StudentListItem(BaseModel):
    id: uuid.UUID
    admission_no: str
    full_name: str
    gender: str
    status: str
    class_code: str | None
    stream_name: str | None


class IdentifiersOut(BaseModel):
    birth_cert_no: str | None
    nida: str | None


class ConsentIn(BaseModel):
    purpose: ConsentPurpose
    granted: bool
    channel: ConsentChannel
    student_id: uuid.UUID | None = None


class ConsentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    guardian_id: uuid.UUID
    student_id: uuid.UUID | None
    purpose: str
    granted: bool
    channel: str
    recorded_at: datetime
