from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class User:
    id: uuid.UUID
    email: str
    hashed_password: str | None
    google_sub: str | None
    created_at: datetime
