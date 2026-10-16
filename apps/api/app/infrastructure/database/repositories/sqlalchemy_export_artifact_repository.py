from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import ExportArtifact
from app.infrastructure.database.models import ExportArtifactModel


class SqlAlchemyExportArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, artifact: ExportArtifact) -> ExportArtifact:
        model = ExportArtifactModel(
            id=artifact.id,
            user_id=artifact.user_id,
            format=artifact.format,
            download_url=artifact.download_url,
            content=artifact.content,
            content_type=artifact.content_type,
            filename=artifact.filename,
            row_count=artifact.row_count,
            report_schema_version=artifact.report_schema_version,
            file_sha256=artifact.file_sha256,
            expires_at=artifact.expires_at,
            created_at=artifact.created_at,
        )
        self._session.add(model)
        await self._session.commit()
        return artifact

    async def get_for_user(self, user_id: uuid.UUID, export_id: uuid.UUID) -> ExportArtifact | None:
        result = await self._session.execute(
            select(ExportArtifactModel).where(
                ExportArtifactModel.id == export_id,
                ExportArtifactModel.user_id == user_id,
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    @staticmethod
    def _to_entity(model: ExportArtifactModel) -> ExportArtifact:
        return ExportArtifact(
            id=model.id,
            user_id=model.user_id,
            download_url=model.download_url,
            expires_at=model.expires_at,
            created_at=model.created_at,
            format=model.format,
            content=model.content,
            content_type=model.content_type,
            filename=model.filename,
            row_count=model.row_count,
            report_schema_version=model.report_schema_version,
            file_sha256=model.file_sha256,
        )
