from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ChatThread:
    id: uuid.UUID
    user_id: uuid.UUID
    thread_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    transaction_id: uuid.UUID | None = None
