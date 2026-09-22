"""Ports for capabilities the domain/application layers need but do not
implement themselves (password hashing, tokens, external identity providers).
Infrastructure adapts these ports; nothing here imports a framework."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class PasswordHasher(Protocol):
    def hash(self, plain_password: str) -> str: ...
    def verify(self, plain_password: str, hashed_password: str) -> bool: ...


class TokenService(Protocol):
    def create_access_token(self, user_id: uuid.UUID) -> str: ...
    def create_refresh_token(self, user_id: uuid.UUID) -> tuple[str, str, datetime]: ...
    def decode_access_token(self, token: str) -> uuid.UUID: ...
    def decode_refresh_token(self, token: str) -> tuple[uuid.UUID, str]: ...


@dataclass
class GoogleProfile:
    sub: str
    email: str


class GoogleOAuthClient(Protocol):
    async def exchange_code(self, code: str, redirect_uri: str) -> GoogleProfile: ...
