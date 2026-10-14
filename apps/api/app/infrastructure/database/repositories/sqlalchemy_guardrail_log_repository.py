from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import GuardrailLog
from app.infrastructure.database.models import GuardrailLogModel


class SqlAlchemyGuardrailLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, guardrail_log: GuardrailLog) -> GuardrailLog:
        model = GuardrailLogModel(
            id=guardrail_log.id,
            user_id=guardrail_log.user_id,
            thread_id=guardrail_log.thread_id,
            message=guardrail_log.message,
            intent=guardrail_log.intent,
            confidence=guardrail_log.confidence,
            triggered=guardrail_log.triggered,
            layer=guardrail_log.layer,
            expires_at=guardrail_log.expires_at,
        )
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: GuardrailLogModel) -> GuardrailLog:
        return GuardrailLog(
            id=model.id,
            user_id=model.user_id,
            thread_id=model.thread_id,
            message=model.message,
            intent=model.intent,
            confidence=model.confidence,
            triggered=model.triggered,
            layer=model.layer,
            created_at=model.created_at,
            expires_at=model.expires_at,
        )
