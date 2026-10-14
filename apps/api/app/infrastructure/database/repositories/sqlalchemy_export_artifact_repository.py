from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import ExportArtifact
from app.infrastructure.database.models import ExportArtifactModel


class SqlAlchemyExportArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        )
