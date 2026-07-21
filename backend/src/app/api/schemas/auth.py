import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.db.models.enums import OperatorRole


def normalize_email(value: str) -> str:
    normalized = value.strip().casefold()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise ValueError("Adresa de e-mail nu este validă.")
    return normalized


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class PasswordResetCompletionRequest(BaseModel):
    email: str
    reset_token: str = Field(min_length=20, max_length=512)
    new_password: str = Field(min_length=12, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class MembershipResponse(BaseModel):
    membership_id: UUID
    project_id: str
    project_name: str
    role: OperatorRole


class AuthenticatedUserResponse(BaseModel):
    account_id: UUID
    email: str
    must_change_password: bool
    memberships: list[MembershipResponse]


class OperatorCreateRequest(BaseModel):
    email: str
    role: OperatorRole
    temporary_password: str | None = Field(default=None, min_length=12, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class OperatorResponse(BaseModel):
    account_id: UUID
    membership_id: UUID
    email: str
    role: OperatorRole
    membership_active: bool
    account_disabled: bool
    must_change_password: bool


class OperatorCreateResponse(OperatorResponse):
    temporary_password: str | None


class MembershipStatusRequest(BaseModel):
    is_active: bool


class PasswordResetIssuedResponse(BaseModel):
    reset_token: str
    expires_at: datetime
