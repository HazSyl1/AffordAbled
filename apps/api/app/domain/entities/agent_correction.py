from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class AgentCorrection:
    id: uuid.UUID
    user_id: uuid.UUID
    thread_id: str
    original_proposal: dict[str, Any]
    corrected_proposal: dict[str, Any]
    user_message: str
    created_at: datetime
