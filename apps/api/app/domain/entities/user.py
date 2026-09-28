from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class User:
    id: uuid.UUID
    email: str
    name: str
    date_of_birth: date | None
    hashed_password: str | None
    google_sub: str | None
    created_at: datetime
