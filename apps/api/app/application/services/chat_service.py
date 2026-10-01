from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from langsmith import traceable

from app.domain.entities import GuardrailLog
from app.domain.exceptions import InvalidChatInputError
from app.domain.ports import ChatOrchestrator, PendingTransactionProposal
from app.domain.repositories import GuardrailLogRepository, UserRepository


@dataclass
class ChatResponseOutput:
    thread_id: str
    message: str
    pending_transaction_proposal: PendingTransactionProposal | None = None
    transaction_logged: bool = False
    manual_transaction_input_required: bool = False
    intent: str | None = None
    guardrail_decision: str = 'allow'
    guardrail_confidence: float = 1.0
    guardrail_layer: str = 'semantic'
    insights: list[dict[str, str]] | None = None


@dataclass
class ChatService:
    orchestrator: ChatOrchestrator
    user_repository: UserRepository
    guardrail_log_repository: GuardrailLogRepository

    @traceable(name='chat_service.send_message', run_type='chain')
    async def send_message(
        self,
        *,
        user_id: uuid.UUID,
        message: str,
        thread_id: str | None = None,
    ) -> ChatResponseOutput:
        normalized_message = message.strip()
        if not normalized_message:
            raise InvalidChatInputError('Message cannot be empty')

        resolved_thread_id = (thread_id or '').strip() or str(uuid.uuid4())
        result = await self.orchestrator.run_turn(
            user_id=user_id,
            thread_id=resolved_thread_id,
            message=normalized_message,
        )

        user = await self.user_repository.get_by_id(user_id)
        if user is not None and user.conversation_storage_enabled:
            expires_at = datetime.now(UTC) + timedelta(days=365 if result.guardrail_decision == 'block' else 90)
            await self.guardrail_log_repository.create(
                GuardrailLog(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    thread_id=resolved_thread_id,
                    message=normalized_message[:500],
                    intent=result.intent,
                    confidence=float(result.guardrail_confidence),
                    triggered=result.guardrail_decision == 'block',
                    layer=result.guardrail_layer,
                    created_at=datetime.now(UTC),
                    expires_at=expires_at,
                )
            )

        return ChatResponseOutput(
            thread_id=resolved_thread_id,
            message=result.message,
            pending_transaction_proposal=result.pending_transaction_proposal,
            transaction_logged=result.transaction_logged,
            manual_transaction_input_required=result.manual_transaction_input_required,
            intent=result.intent,
            guardrail_decision=result.guardrail_decision,
            guardrail_confidence=result.guardrail_confidence,
            guardrail_layer=result.guardrail_layer,
            insights=result.insights,
        )

