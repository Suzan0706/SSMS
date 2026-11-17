import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.phone import normalise_phone


class LoginIn(BaseModel):
    school_code: str = Field(min_length=2, max_length=20, examples=["mfano-sec"])
    username: str = Field(min_length=1, max_length=50, examples=["admin"])
    password: str = Field(min_length=1, max_length=128, examples=["Mfano@2026"])


class PhoneIn(BaseModel):
    phone: str = Field(examples=["0754000021"], description="07XXXXXXXX, +2557XXXXXXXX or 2557XXXXXXXX")

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        try:
            return normalise_phone(value)
        except ValueError:
            raise ValueError("invalid_phone") from None


class OtpVerifyIn(PhoneIn):
    code: str = Field(pattern=r"^\d{6}$", examples=["482913"])


class SelectSchoolIn(BaseModel):
    selection_token: str
    school_id: uuid.UUID


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class SchoolBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    status: str


class UserBrief(BaseModel):
    id: uuid.UUID
    full_name: str
    username: str | None
    language: str
    must_change_password: bool


class MeOut(BaseModel):
    user: UserBrief
    school: SchoolBrief
    roles: list[str]
    permissions: list[str]


class TokenOut(MeOut):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class SchoolChoice(BaseModel):
    school_id: uuid.UUID
    name: str


class SchoolSelectionOut(BaseModel):
    choose: list[SchoolChoice]
    selection_token: str
    expires_in: int


class OtpRequestOut(BaseModel):
    sent: bool = True
    message: str
