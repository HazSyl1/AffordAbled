from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import RefreshSession
from app.infrastructure.database.models import RefreshSessionModel


class SqlAlchemyRefreshSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, session_entity: RefreshSession) -> RefreshSession:
        model = RefreshSessionModel(
            id=session_entity.id,
            user_id=session_entity.user_id,
            jti=session_entity.jti,
            expires_at=session_entity.expires_at,
            revoked_at=session_entity.revoked_at,
        )
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def get_by_jti(self, jti: str) -> RefreshSession | None:
        result = await self._session.execute(select(RefreshSessionModel).where(RefreshSessionModel.jti == jti))
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def revoke(self, jti: str) -> None:
        await self._session.execute(
            update(RefreshSessionModel)
            .where(RefreshSessionModel.jti == jti)
            .values(revoked_at=datetime.now(UTC))
        )
        await self._session.commit()

    @staticmethod
    def _to_entity(model: RefreshSessionModel) -> RefreshSession:
        return RefreshSession(
            id=model.id,
            user_id=model.user_id,
            jti=model.jti,
            expires_at=model.expires_at,
            revoked_at=model.revoked_at,
        )
