from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import Instructor
from app.models.enums import Gender
from app.schemas.common import Name, Stream, TzPhone


class InstructorCreate(BaseModel):
    first_name: Name
    middle_name: Name | None = None
    last_name: Name
    gender: Gender
    date_of_birth: date | None = None
    phone: TzPhone
    email: EmailStr | None = None
    preferred_language: Literal["sw", "en"] = "sw"
    employee_no: str = Field(max_length=20)
    department_id: int
    qualification: str = Field(max_length=100)
    employment_date: date | None = None
    max_periods_per_week: int = Field(default=30, ge=1, le=50)
    subject_ids: list[int] = Field(default_factory=list)


class InstructorUpdate(BaseModel):
    department_id: int | None = None
    qualification: str | None = Field(default=None, max_length=100)
    employment_status: Literal["ACTIVE", "ON_LEAVE", "TRANSFERRED", "RETIRED"] | None = None
    max_periods_per_week: int | None = Field(default=None, ge=1, le=50)
    phone: TzPhone | None = None
    email: EmailStr | None = None


class InstructorOut(BaseModel):
    instructor_id: int
    employee_no: str
    first_name: str
    last_name: str
    gender: Gender
    phone: str | None
    email: str | None
    department_code: str
    qualification: str
    employment_status: str
    max_periods_per_week: int
    subject_ids: list[int]

    @classmethod
    def of(cls, i: Instructor) -> "InstructorOut":
        return cls(
            instructor_id=i.instructor_id, employee_no=i.employee_no, first_name=i.user.first_name,
            last_name=i.user.last_name, gender=i.user.gender, phone=i.user.phone, email=i.user.email,
            department_code=i.department.code, qualification=i.qualification,
            employment_status=i.employment_status, max_periods_per_week=i.max_periods_per_week,
            subject_ids=sorted(s.subject_id for s in i.subjects),
        )


class InstructorCreated(InstructorOut):
    username: str
    initial_password: str


class DesignationAssign(BaseModel):
    designation_id: int
    academic_year_id: int
    department_id: int | None = None
    level_id: int | None = None
    stream: Stream | None = None
    assigned_on: date | None = None

    @model_validator(mode="after")
    def class_needs_stream(self) -> "DesignationAssign":
        if (self.level_id is None) != (self.stream is None):
            raise ValueError("level_id and stream must be given together")
        return self


class DesignationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instructor_designation_id: int
    instructor_id: int
    designation_id: int
    academic_year_id: int
    department_id: int | None
    level_id: int | None
    stream: str | None
    assigned_on: date
    ended_on: date | None
