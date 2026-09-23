"""Ports for capabilities the domain/application layers need but do not
implement themselves (password hashing, tokens, external identity providers).
Infrastructure adapts these ports; nothing here imports a framework."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
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


class SpeechToTextClient(Protocol):
    async def transcribe(self, audio_bytes: bytes, *, content_type: str, locale: str) -> str: ...


class GuardrailDecision(str, Enum):
    ALLOW = 'allow'
    BLOCK = 'block'
    NEEDS_CLASSIFICATION = 'needs_classification'


class DetectedIntent(str, Enum):
    LOG_TRANSACTION = 'log_transaction'
    QUERY_SPENDING = 'query_spending'
    SPLIT_REQUEST = 'split_request'
    GENERATE_REPORT = 'generate_report'
    ACCOUNT_QUERY = 'account_query'
    MEMORY_RELATED = 'memory_related'
    OFF_TOPIC = 'off_topic'


class SemanticGuardrail(Protocol):
    async def assess(self, message: str) -> GuardrailDecision: ...


class IntentClassifier(Protocol):
    async def classify(self, message: str) -> DetectedIntent: ...


class ChatOrchestrator(Protocol):
    async def run_turn(self, *, user_id: uuid.UUID, thread_id: str, message: str) -> str: ...
