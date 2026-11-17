import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.phone import normalise_phone
from app.models.enums import EducationLevelCode, Gender, Ownership, SchoolStatus

Name = Field(min_length=1, max_length=50)


class PlatformLoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    totp: str | None = Field(default=None, pattern=r"^\d{6}$", description="Authenticator app code")


class PlatformAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    full_name: str
    email: str


class PlatformTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    admin: PlatformAdminOut


class SchoolAdminIn(BaseModel):
    first_name: str = Name
    middle_name: str | None = Field(default=None, max_length=50)
    last_name: str = Name
    gender: Gender
    phone: str = Field(examples=["0754123456"])
    email: EmailStr | None = None
    username: str = Field(default="admin", pattern=r"^[a-z0-9._-]{3,50}$")

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        try:
            return normalise_phone(value)
        except ValueError:
            raise ValueError("invalid_phone") from None


class DistrictOut(BaseModel):
    id: uuid.UUID
    name: str


class RegionOut(BaseModel):
    id: uuid.UUID
    name: str
    districts: list[DistrictOut]


class SchoolCreateIn(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9-]{3,20}$", examples=["tumaini-sec"], description="Login code / sub-domain")
    name: str = Field(min_length=3, max_length=150, examples=["Shule ya Sekondari Tumaini"])
    registration_no: str | None = Field(default=None, max_length=30, examples=["S.5120"])
    ownership: Ownership
    district_id: uuid.UUID = Field(description="From GET /platform/regions; the district decides the region")
    levels: list[EducationLevelCode] = Field(min_length=1, examples=[["O_LEVEL"]])
    admission_prefix: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{2,4}$",
        description="Admission numbers look like TU-2026-0001; default from the code",
    )
    admin: SchoolAdminIn


class SchoolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    registration_no: str | None
    ownership: Ownership
    region: str
    district: str
    status: SchoolStatus
    created_at: datetime


class SchoolCreatedOut(BaseModel):
    school: SchoolOut
    admin_user_id: uuid.UUID
    admin_username: str
    temporary_password: str = Field(description="Shown once; also sent by SMS. Must be changed at first login.")
    defaults: dict[str, int]


class SchoolStatusIn(BaseModel):
    status: SchoolStatus
    reason: str = Field(min_length=5, max_length=300)
