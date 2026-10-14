from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ChatMessage:
    id: uuid.UUID
    user_id: uuid.UUID
    thread_id: str
    role: str
    content: str
    created_at: datetime
