from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MemoryResponse(BaseModel):
    id: uuid.UUID
    scope: str
    subject_key: str
    memory_type: str
    value: dict[str, Any]
    status: str
    confidence: float
    evidence_count: int
    created_at: datetime
    updated_at: datetime


class MemoryReviewEventRequest(BaseModel):
    action: str = Field(pattern='^(accepted|edited|rejected|discarded)$')
    source: str = Field(default='manual', min_length=1, max_length=32)
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    transaction_id: uuid.UUID | None = None
    split_id: uuid.UUID | None = None


class MemoryUpdateRequest(BaseModel):
    value: dict[str, Any] = Field(min_length=1)


class MemoryEventResponse(BaseModel):
    id: uuid.UUID
    status: str = 'queued'
