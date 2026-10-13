from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.entities import ExportArtifact
from app.domain.exceptions import ExportLinkExpiredError, ExportNotFoundError
from app.domain.repositories import ExportArtifactRepository


@dataclass
class ExportService:
    export_artifact_repository: ExportArtifactRepository

    async def get_download_url(self, *, user_id: uuid.UUID, export_id: uuid.UUID) -> ExportArtifact:
        export = await self.export_artifact_repository.get_for_user(user_id, export_id)
        if export is None:
            raise ExportNotFoundError(f'Export not found: {export_id}')

        expires_at = (
            export.expires_at
            if export.expires_at.tzinfo is not None
            else export.expires_at.replace(tzinfo=UTC)
        )
        if expires_at <= datetime.now(UTC):
            raise ExportLinkExpiredError('Export download link has expired')

        return export
