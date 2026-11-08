from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

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
    upi_id: str | None = None
    account_tier: Literal['free', 'subscribed', 'test'] = 'free'


class UsageMetricResponse(BaseModel):
    used: int
    limit: int | None
    remaining: int | None
    unlimited: bool


class UserUsageResponse(BaseModel):
    account_tier: Literal['free', 'subscribed', 'test']
    reset_at: datetime
    chat_turns: UsageMetricResponse
    ai_transactions: UsageMetricResponse
    notification_limits_bypassed: bool


class UpdateProfileRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    date_of_birth: date | None
    upi_id: str | None = Field(default=None, max_length=255)

    @field_validator('name')
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return RegisterRequest.normalize_name(value)

    @field_validator('date_of_birth')
    @classmethod
    def validate_dob_not_future(cls, value: date | None) -> date | None:
        if value is not None and value >= datetime.now(UTC).date():
            raise ValueError('Date of birth must be in the past')
        return value

    @field_validator('upi_id')
    @classmethod
    def validate_upi_id(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip()
        if any(character.isspace() for character in normalized) or normalized.count('@') != 1:
            raise ValueError('Enter a valid UPI ID, such as name@bank')
        payer, handle = normalized.split('@', 1)
        if not payer or not handle:
            raise ValueError('Enter a valid UPI ID, such as name@bank')
        return normalized


class ProfileTransactionSummaryResponse(BaseModel):
    message: str
    transaction_count: int
