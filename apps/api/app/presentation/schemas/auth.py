from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=120)
    date_of_birth: date
    password: str = Field(min_length=8, max_length=128)

    @field_validator('name')
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = ' '.join(value.strip().split())
        if len(normalized) < 2:
            raise ValueError('Name must be at least 2 characters long')
        return normalized

    @field_validator('date_of_birth')
    @classmethod
    def validate_dob_not_future(cls, value: date) -> date:
        if value >= datetime.now(UTC).date():
            raise ValueError('Date of birth must be in the past')
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginRequest(BaseModel):
    code: str
    redirect_uri: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    date_of_birth: date | None
