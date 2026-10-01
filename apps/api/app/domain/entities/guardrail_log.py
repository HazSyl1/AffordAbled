from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class GuardrailLog:
    id: uuid.UUID
    user_id: uuid.UUID
    thread_id: str
    message: str
    intent: str | None
    confidence: float
    triggered: bool
    layer: str
    created_at: datetime
    expires_at: datetime
