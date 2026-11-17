from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import Student
from app.models.enums import Gender, GuardianRelationship, StudentStatus
from app.schemas.common import Name, NidaNo, TzPhone


class GuardianIn(BaseModel):
    first_name: Name
    last_name: Name
    gender: Gender
    phone: TzPhone
    relationship: GuardianRelationship
    is_primary: bool = False
    nida_no: NidaNo | None = None
    occupation: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=200)
    preferred_language: Literal["sw", "en"] = "sw"


class StudentCreate(BaseModel):
    first_name: Name
    middle_name: Name | None = None
    last_name: Name
    gender: Gender
    date_of_birth: date
    birth_cert_no: str | None = Field(default=None, max_length=30)
    necta_index_no: str | None = Field(default=None, max_length=20)
    phone: TzPhone | None = None
    region: str | None = Field(default=None, max_length=40)
    district: str | None = Field(default=None, max_length=40)
    home_address: str | None = Field(default=None, max_length=200)
    preferred_language: Literal["sw", "en"] = "sw"
    guardians: list[GuardianIn] = Field(min_length=1, max_length=4)

    @field_validator("date_of_birth")
    @classmethod
    def plausible_dob(cls, v: date) -> date:
        today = date.today()
        if v > today or today.year - v.year < 3:
            raise ValueError("date_of_birth must be at least 3 years ago")
        return v

    @model_validator(mode="after")
    def one_primary_guardian(self) -> "StudentCreate":
        primaries = [g for g in self.guardians if g.is_primary]
        if len(primaries) > 1:
            raise ValueError("only one guardian can be primary")
        if not primaries:
            self.guardians[0].is_primary = True
        return self


class StudentUpdate(BaseModel):
    first_name: Name | None = None
    middle_name: Name | None = None
    last_name: Name | None = None
    gender: Gender | None = None
    date_of_birth: date | None = None
    birth_cert_no: str | None = Field(default=None, max_length=30)
    necta_index_no: str | None = Field(default=None, max_length=20)
    phone: TzPhone | None = None
    region: str | None = Field(default=None, max_length=40)
    district: str | None = Field(default=None, max_length=40)
    home_address: str | None = Field(default=None, max_length=200)


class StudentOut(BaseModel):
    student_id: int
    admission_no: str
    first_name: str
    middle_name: str | None
    last_name: str
    gender: Gender
    date_of_birth: date | None
    age: int | None
    phone: str | None
    current_status: StudentStatus
    admission_date: date
    necta_index_no: str | None
    region: str | None
    district: str | None
    home_address: str | None

    @classmethod
    def of(cls, s: Student) -> "StudentOut":
        u = s.user
        return cls(
            student_id=s.student_id, admission_no=s.admission_no, first_name=u.first_name,
            middle_name=u.middle_name, last_name=u.last_name, gender=u.gender, date_of_birth=u.date_of_birth,
            age=u.age(), phone=u.phone, current_status=s.current_status, admission_date=s.admission_date,
            necta_index_no=s.necta_index_no, region=s.region, district=s.district, home_address=s.home_address,
        )


class StudentCreated(StudentOut):
    username: str
    initial_password: str = Field(description="Shown once so the registrar can print the login slip")


class StatusChangeIn(BaseModel):
    new_status: StudentStatus
    reason: str = Field(min_length=5, max_length=300)
    effective_date: date | None = None


class StatusChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    history_id: int
    student_id: int
    old_status: StudentStatus | None
    new_status: StudentStatus
    reason: str
    effective_date: date
    changed_by: int | None
    changed_at: datetime
