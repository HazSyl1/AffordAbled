from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import AgentCorrection
from app.infrastructure.database.models import AgentCorrectionModel


class SqlAlchemyAgentCorrectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, agent_correction: AgentCorrection) -> AgentCorrection:
        model = AgentCorrectionModel(
            id=agent_correction.id,
            user_id=agent_correction.user_id,
            thread_id=agent_correction.thread_id,
            original_proposal=agent_correction.original_proposal,
            corrected_proposal=agent_correction.corrected_proposal,
            user_message=agent_correction.user_message,
        )
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: AgentCorrectionModel) -> AgentCorrection:
        return AgentCorrection(
            id=model.id,
            user_id=model.user_id,
            thread_id=model.thread_id,
            original_proposal=model.original_proposal,
            corrected_proposal=model.corrected_proposal,
            user_message=model.user_message,
            created_at=model.created_at,
        )
