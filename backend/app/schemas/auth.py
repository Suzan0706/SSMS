from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Role


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access-token lifetime in seconds")


class RefreshIn(BaseModel):
    refresh_token: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    username: str
    role: Role
    first_name: str
    middle_name: str | None
    last_name: str
    phone: str | None
    email: str | None
    preferred_language: str
