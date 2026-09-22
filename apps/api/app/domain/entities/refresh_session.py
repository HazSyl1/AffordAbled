from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class RefreshSession:
    id: uuid.UUID
    user_id: uuid.UUID
    jti: str
    expires_at: datetime
    revoked_at: datetime | None
