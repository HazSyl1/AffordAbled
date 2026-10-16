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
    format: str = 'pdf'
    content: bytes | None = None
    content_type: str | None = None
    filename: str | None = None
    row_count: int | None = None
    report_schema_version: int | None = None
    file_sha256: str | None = None
