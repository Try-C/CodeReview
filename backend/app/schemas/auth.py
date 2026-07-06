"""Authentication request and response contracts."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator

Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    ),
]
Password = Annotated[SecretStr, Field(min_length=8, max_length=128)]


class RegisterRequest(BaseModel):
    """Fields accepted when creating a local account."""

    username: Username
    password: Password
    email: str | None = Field(default=None, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or "@" not in normalized:
            raise ValueError("email must be a valid non-empty address")
        return normalized


class LoginRequest(BaseModel):
    """Credentials accepted by the JSON login endpoint."""

    username: Username
    password: Password


class UserResponse(BaseModel):
    """Public account fields; password hashes are never serialized."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    created_at: datetime


class TokenResponse(BaseModel):
    """Short-lived bearer token returned after successful authentication."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
