from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from langsmith import traceable

from app.domain.entities import AgentCorrection, ChatMessage, ChatThread, GuardrailLog
from app.domain.exceptions import InvalidChatInputError
from app.domain.ports import ChatOrchestrator, PendingTransactionProposal
from app.domain.repositories import (
    AgentCorrectionRepository,
    ChatMessageRepository,
    ChatThreadRepository,
    GuardrailLogRepository,
    TransactionRepository,
    UserRepository,
)


@dataclass
class ChatResponseOutput:
    thread_id: str
    message: str
    tasks_completed: bool = False
    show_completion_popup: bool = False
    pending_transaction_proposal: PendingTransactionProposal | None = None
    pending_transaction_proposals: list[PendingTransactionProposal] | None = None
    transaction_logged: bool = False
    created_transaction_id: str | None = None
    manual_transaction_input_required: bool = False
    intent: str | None = None
    guardrail_decision: str = "allow"
    guardrail_confidence: float = 1.0
    guardrail_layer: str = "semantic"
    insights: list[dict[str, str]] | None = None


@dataclass
class ChatService:
    orchestrator: ChatOrchestrator
    user_repository: UserRepository
    chat_thread_repository: ChatThreadRepository
    chat_message_repository: ChatMessageRepository
    agent_correction_repository: AgentCorrectionRepository
    guardrail_log_repository: GuardrailLogRepository
    transaction_repository: TransactionRepository | None = None

    @traceable(name="chat_service.send_message", run_type="chain")
    async def send_message(
        self,
        *,
        user_id: uuid.UUID,
        message: str,
        thread_id: str | None = None,
        timezone: str | None = None,
    ) -> ChatResponseOutput:
        normalized_message = message.strip()
        if not normalized_message:
            raise InvalidChatInputError("Message cannot be empty")

        user = await self.user_repository.get_by_id(user_id)
        resolved_thread_id = (thread_id or "").strip() or str(uuid.uuid4())
        result = await self.orchestrator.run_turn(
            user_id=user_id,
            thread_id=resolved_thread_id,
            message=normalized_message,
            owner_name=user.name if user is not None else None,
            timezone=timezone,
        )

        if user is not None and user.conversation_storage_enabled:
            now = datetime.now(UTC)
            existing_thread = await self.chat_thread_repository.get_for_user(user_id, resolved_thread_id)
            created_transaction = None
            if result.created_transaction_id and self.transaction_repository is not None:
                try:
                    created_transaction = await self.transaction_repository.get_for_user(
                        uuid.UUID(result.created_transaction_id), user_id,
                    )
                except (ValueError, TypeError):
                    created_transaction = None
            transaction_title = None
            if created_transaction is not None:
                transaction_title = (
                    f'{created_transaction.merchant or "Expense"} - '
                    f'INR {created_transaction.amount_paise / 100:,.2f}'
                )[:160]
            if existing_thread is None:
                await self.chat_thread_repository.create(
                    ChatThread(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        thread_id=resolved_thread_id,
                        title=transaction_title or normalized_message[:160],
                        created_at=now,
                        updated_at=now,
                        transaction_id=created_transaction.id if created_transaction else None,
                    )
                )
            else:
                await self.chat_thread_repository.touch_for_user(user_id, resolved_thread_id)
                if created_transaction is not None and existing_thread.transaction_id is None:
                    await self.chat_thread_repository.link_transaction_for_user(
                        user_id, resolved_thread_id, created_transaction.id, transaction_title or 'Transaction chat',
                    )

            await self.chat_message_repository.create(
                ChatMessage(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    thread_id=resolved_thread_id,
                    role="user",
                    content=normalized_message,
                    created_at=now,
                )
            )
            await self.chat_message_repository.create(
                ChatMessage(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    thread_id=resolved_thread_id,
                    role="assistant",
                    content=result.message,
                    created_at=now,
                )
            )

            agent_correction_payload = result.agent_correction
            if isinstance(agent_correction_payload, dict):
                original_proposal = agent_correction_payload.get("original_proposal")
                corrected_proposal = agent_correction_payload.get("corrected_proposal")
                if isinstance(original_proposal, dict) and isinstance(corrected_proposal, dict):
                    await self.agent_correction_repository.create(
                        AgentCorrection(
                            id=uuid.uuid4(),
                            user_id=user_id,
                            thread_id=resolved_thread_id,
                            original_proposal=original_proposal,
                            corrected_proposal=corrected_proposal,
                            user_message=str(agent_correction_payload.get("user_message") or normalized_message),
                            created_at=now,
                        )
                    )

            expires_at = now + timedelta(days=365 if result.guardrail_decision == "block" else 90)
            await self.guardrail_log_repository.create(
                GuardrailLog(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    thread_id=resolved_thread_id,
                    message=normalized_message[:500],
                    intent=result.intent,
                    confidence=float(result.guardrail_confidence),
                    triggered=result.guardrail_decision == "block",
                    layer=result.guardrail_layer,
                    created_at=now,
                    expires_at=expires_at,
                )
            )

        return ChatResponseOutput(
            thread_id=resolved_thread_id,
            message=result.message,
            tasks_completed=result.tasks_completed,
            show_completion_popup=result.show_completion_popup,
            pending_transaction_proposal=result.pending_transaction_proposal,
            pending_transaction_proposals=result.pending_transaction_proposals,
            transaction_logged=result.transaction_logged,
            created_transaction_id=result.created_transaction_id,
            manual_transaction_input_required=result.manual_transaction_input_required,
            intent=result.intent,
            guardrail_decision=result.guardrail_decision,
            guardrail_confidence=result.guardrail_confidence,
            guardrail_layer=result.guardrail_layer,
            insights=result.insights,
        )
