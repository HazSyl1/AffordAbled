from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ExportArtifact:
    id: uuid.UUID
    user_id: uuid.UUID
    download_url: str
    expires_at: datetime
    created_at: datetime
