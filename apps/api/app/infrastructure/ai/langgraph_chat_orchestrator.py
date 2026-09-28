from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from langsmith import traceable
from pydantic import BaseModel, Field

from app.application.dto import CreateTransactionInput
from app.application.services.transaction_service import TransactionService
from app.domain.entities import CategoryType, TransactionType
from app.domain.ports import (
    ChatTurnResult,
    DetectedIntent,
    GuardrailDecision,
    IntentClassifier,
    PendingTransactionProposal,
    SemanticGuardrail,
)
from app.domain.repositories import AccountRepository, CategoryRepository

_REFUSAL_MESSAGE = (
    "I'm your finance assistant - I can only help with money matters. "
    'Want me to log a transaction, check spending, or split a bill?'
)

_CURRENCY_PREFIX_PATTERN = re.compile(
    r'(?:\u20B9|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)',
    re.IGNORECASE,
)
_CURRENCY_SUFFIX_PATTERN = re.compile(
    r'([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:\u20B9|rs\.?|inr|rupees?)',
    re.IGNORECASE,
)
_ANY_NUMBER_PATTERN = re.compile(r'\b([0-9][0-9,]*(?:\.[0-9]{1,2})?)\b')
_MERCHANT_PATTERN = re.compile(
    r"\b(?:at|for|from)\s+([A-Za-z][A-Za-z0-9 &'\-.]{1,80})",
    re.IGNORECASE,
)

_EXPENSE_KEYWORDS = ('spent', 'paid', 'pay', 'bought', 'purchase', 'purchased', 'debited')
_INCOME_KEYWORDS = ('received', 'credited', 'salary', 'earned', 'income', 'got paid')
_REFUND_KEYWORDS = ('refund', 'refunded', 'reimbursed', 'reimbursement', 'cashback')


class TransactionExtractionOutput(BaseModel):
    is_transaction: bool = Field(default=False)
    transaction_type: str | None = Field(default=None)
    amount: float | None = Field(default=None)
    merchant: str | None = Field(default=None)
    note: str | None = Field(default=None)
    occurred_at: datetime | None = Field(default=None)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ChatGraphState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    workflow_action: str
    pending_proposal: dict[str, Any] | None
    extracted_candidate: dict[str, Any] | None
    runtime_user_id: str
    transaction_logged: bool
    manual_transaction_input_required: bool
    hitl_active: bool
    hitl_attempt_count: int
    hitl_context_message: str | None
    hitl_missing_fields: list[str]
    manual_prefill_proposal: dict[str, Any] | None


class LangGraphChatOrchestrator:
    def __init__(
        self,
        *,
        checkpointer: Any,
        semantic_guardrail: SemanticGuardrail,
        intent_classifier: IntentClassifier,
        transaction_service: TransactionService,
        account_repository: AccountRepository,
        category_repository: CategoryRepository,
        extraction_llm: Any | None = None,
        proposal_confidence_threshold: int = 80,
        hitl_max_turns: int = 5,
    ) -> None:
        self._semantic_guardrail = semantic_guardrail
        self._intent_classifier = intent_classifier
        self._transaction_service = transaction_service
        self._account_repository = account_repository
        self._category_repository = category_repository
        self._proposal_confidence_threshold = max(0, min(int(proposal_confidence_threshold), 100))
        self._hitl_max_turns = max(1, int(hitl_max_turns))

        self._guardrail_chain = (
            ChatPromptTemplate.from_messages(
                [
                    ('system', 'Classify whether this user message is in finance scope.'),
                    ('human', '{message}'),
                ]
            )
            | RunnableLambda(self._extract_message_from_prompt)
            | RunnableLambda(self._semantic_guardrail.assess)
        )

        self._intent_chain = (
            ChatPromptTemplate.from_messages(
                [
                    ('system', 'Classify the finance intent for this user message.'),
                    ('human', '{message}'),
                ]
            )
            | RunnableLambda(self._extract_message_from_prompt)
            | RunnableLambda(self._intent_classifier.classify)
        )

        self._llm_extraction_chain = None
        if extraction_llm is not None:
            extraction_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        'system',
                        (
                            'Extract transaction details from the user message. '
                            'Mark is_transaction=true only when the user is asking to log a real transaction. '
                            'transaction_type must be one of: expense, income, refund, transfer. '
                            'amount must be positive in major currency units (for example 250.75). '
                            'Infer merchant when it is implied in the text; otherwise keep merchant=null. '
                            'Infer a short note from context when useful; otherwise keep note=null. '
                            'If occurred_at is missing, return null. '
                            'Set confidence between 0 and 1 for extraction certainty.'
                        ),
                    ),
                    ('human', 'Today is {today_utc}. User message: {message}'),
                ]
            )
            self._llm_extraction_chain = extraction_prompt | extraction_llm.with_structured_output(
                TransactionExtractionOutput
            )

        builder = StateGraph(ChatGraphState)
        builder.add_node('analyze_turn', self._analyze_turn)
        builder.add_node('extract_transaction_candidate', self._extract_transaction_candidate_node)
        builder.add_node('evaluate_transaction_candidate', self._evaluate_transaction_candidate)
        builder.add_node('hitl_clarification', self._hitl_clarification_node)
        builder.add_node('transaction_flow', self._transaction_flow)
        builder.add_node('assistant_default', self._assistant_default)
        builder.add_node('assistant_refusal', self._assistant_refusal)

        builder.add_edge(START, 'analyze_turn')
        builder.add_conditional_edges(
            'analyze_turn',
            self._route_after_analysis,
            {
                'extract_transaction_candidate': 'extract_transaction_candidate',
                'transaction_flow': 'transaction_flow',
                'assistant_default': 'assistant_default',
                'assistant_refusal': 'assistant_refusal',
            },
        )
        builder.add_edge('extract_transaction_candidate', 'evaluate_transaction_candidate')
        builder.add_conditional_edges(
            'evaluate_transaction_candidate',
            self._route_after_candidate_evaluation,
            {
                'hitl_clarification': 'hitl_clarification',
                'transaction_flow': 'transaction_flow',
                'assistant_default': 'assistant_default',
            },
        )
        builder.add_conditional_edges(
            'hitl_clarification',
            self._route_after_hitl_clarification,
            {
                'extract_transaction_candidate': 'extract_transaction_candidate',
                'transaction_flow': 'transaction_flow',
            },
        )
        builder.add_edge('transaction_flow', END)
        builder.add_edge('assistant_default', END)
        builder.add_edge('assistant_refusal', END)

        self._graph = builder.compile(checkpointer=checkpointer)

    def graph_mermaid(self) -> str:
        return self._graph.get_graph().draw_mermaid()

    def graph_png(self, output_file_path: str | None = None) -> bytes:
        return self._graph.get_graph().draw_mermaid_png(output_file_path=output_file_path)

    def save_graph_assets(self, output_dir: str | Path) -> tuple[Path, Path | None]:
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        mermaid_path = target_dir / 'chat_langgraph.mmd'
        mermaid_path.write_text(self.graph_mermaid(), encoding='utf-8')

        png_path = target_dir / 'chat_langgraph.png'
        try:
            self.graph_png(str(png_path))
            rendered_png_path: Path | None = png_path
        except Exception:
            rendered_png_path = None

        return mermaid_path, rendered_png_path

    @traceable(name='langgraph_chat_turn', run_type='chain')
    async def run_turn(self, *, user_id: uuid.UUID, thread_id: str, message: str) -> ChatTurnResult:
        checkpoint_thread_id = f'{user_id}:{thread_id}'
        config = {
            'configurable': {
                'thread_id': checkpoint_thread_id,
                'checkpoint_ns': str(user_id),
            }
        }
        state_config = {'configurable': {'thread_id': checkpoint_thread_id}}

        state_snapshot = await self._graph.aget_state(config=state_config)
        if state_snapshot.interrupts:
            graph_input: dict[str, Any] | Command = Command(
                resume=message,
                update={
                    'messages': [HumanMessage(content=message)],
                    'transaction_logged': False,
                    'manual_transaction_input_required': False,
                },
            )
        else:
            graph_input = {
                'messages': [HumanMessage(content=message)],
                'runtime_user_id': str(user_id),
                'transaction_logged': False,
                'manual_transaction_input_required': False,
            }

        result = await self._graph.ainvoke(graph_input, config=config)

        assistant_message = _REFUSAL_MESSAGE
        graph_interrupts = result.get('__interrupt__', [])
        if graph_interrupts:
            first_interrupt = graph_interrupts[0]
            interrupt_payload = getattr(first_interrupt, 'value', None)
            if isinstance(interrupt_payload, dict):
                assistant_message = str(interrupt_payload.get('question') or _REFUSAL_MESSAGE)
            else:
                assistant_message = _REFUSAL_MESSAGE

        for item in reversed(result.get('messages', [])):
            if isinstance(item, AIMessage):
                assistant_message = str(item.content)
                break

        pending_proposal_raw = result.get('pending_proposal')
        if pending_proposal_raw is None and bool(result.get('manual_transaction_input_required', False)):
            pending_proposal_raw = result.get('manual_prefill_proposal')
        pending_proposal: PendingTransactionProposal | None = None
        if pending_proposal_raw is not None:
            pending_proposal = PendingTransactionProposal(
                type=str(pending_proposal_raw['type']),
                amount_paise=int(pending_proposal_raw['amount_paise']),
                occurred_at=str(pending_proposal_raw['occurred_at']),
                merchant=pending_proposal_raw.get('merchant'),
                note=pending_proposal_raw.get('note'),
                account_id=str(pending_proposal_raw['account_id']),
                account_name=str(pending_proposal_raw['account_name']),
                category_id=str(pending_proposal_raw['category_id']),
                category_name=str(pending_proposal_raw['category_name']),
                confidence_score=int(pending_proposal_raw.get('confidence_score', 0)),
            )

        return ChatTurnResult(
            message=assistant_message,
            pending_transaction_proposal=pending_proposal,
            transaction_logged=bool(result.get('transaction_logged', False)),
            manual_transaction_input_required=bool(result.get('manual_transaction_input_required', False)),
        )

    async def _analyze_turn(self, state: ChatGraphState) -> dict[str, Any]:
        latest_user_message = self._latest_user_message(state.get('messages', []))
        if not latest_user_message:
            return {'workflow_action': 'default'}

        pending_proposal = state.get('pending_proposal')
        if pending_proposal is not None:
            proposal_action = self._proposal_action(latest_user_message)
            if proposal_action is not None:
                return {'workflow_action': proposal_action}
            return {'workflow_action': 'proposal_wait'}

        if state.get('hitl_active'):
            proposal_action = self._proposal_action(latest_user_message)
            if proposal_action == 'cancel_proposal':
                return {'workflow_action': 'cancel_hitl'}
            return {'workflow_action': 'build_proposal'}

        guardrail_decision = self._as_guardrail_decision(
            await self._guardrail_chain.ainvoke({'message': latest_user_message})
        )
        detected_intent = self._as_detected_intent(await self._intent_chain.ainvoke({'message': latest_user_message}))

        if guardrail_decision == GuardrailDecision.BLOCK:
            if detected_intent == DetectedIntent.LOG_TRANSACTION:
                return {'workflow_action': 'build_proposal'}
            return {'workflow_action': 'refusal'}

        if guardrail_decision == GuardrailDecision.NEEDS_CLASSIFICATION and detected_intent == DetectedIntent.OFF_TOPIC:
            return {'workflow_action': 'refusal'}

        if detected_intent == DetectedIntent.LOG_TRANSACTION:
            return {'workflow_action': 'build_proposal'}

        return {'workflow_action': 'default'}

    @staticmethod
    def _route_after_analysis(state: ChatGraphState) -> str:
        action = state.get('workflow_action')
        if action == 'build_proposal':
            return 'extract_transaction_candidate'
        if action in {
            'confirm_proposal',
            'cancel_proposal',
            'edit_proposal',
            'proposal_wait',
            'cancel_hitl',
        }:
            return 'transaction_flow'
        if action == 'refusal':
            return 'assistant_refusal'
        return 'assistant_default'

    async def _extract_transaction_candidate_node(self, state: ChatGraphState) -> dict[str, Any]:
        if state.get('workflow_action') != 'build_proposal':
            return {'extracted_candidate': None}

        latest_user_message = self._latest_user_message(state.get('messages', []))
        if not latest_user_message:
            return {'extracted_candidate': None}

        context_message = state.get('hitl_context_message') if state.get('hitl_active') else None
        extraction_message = self._merge_hitl_context(context_message, latest_user_message)
        candidate = await self._extract_candidate(extraction_message)

        return {
            'extracted_candidate': candidate,
            'hitl_context_message': extraction_message if state.get('hitl_active') else context_message,
        }

    async def _evaluate_transaction_candidate(self, state: ChatGraphState) -> dict[str, Any]:
        if state.get('workflow_action') != 'build_proposal':
            return {'workflow_action': 'default'}

        candidate = state.get('extracted_candidate')
        latest_user_message = self._latest_user_message(state.get('messages', []))
        hitl_attempt_count = int(state.get('hitl_attempt_count', 0))
        hitl_context_message = state.get('hitl_context_message')

        if candidate is None:
            return self._next_hitl_step(
                latest_user_message=latest_user_message,
                current_context=hitl_context_message,
                current_hitl_attempt_count=hitl_attempt_count,
                candidate=None,
            )

        candidate_confidence_score = int(candidate.get('confidence_score', 0))
        if candidate_confidence_score < self._proposal_confidence_threshold:
            return self._next_hitl_step(
                latest_user_message=latest_user_message,
                current_context=hitl_context_message,
                current_hitl_attempt_count=hitl_attempt_count,
                candidate=candidate,
            )

        return {
            'workflow_action': 'build_proposal_ready',
            'manual_transaction_input_required': False,
        }

    @staticmethod
    def _route_after_candidate_evaluation(state: ChatGraphState) -> str:
        action = state.get('workflow_action')
        if action == 'hitl_clarification':
            return 'hitl_clarification'
        if action in {'build_proposal_ready', 'manual_fallback'}:
            return 'transaction_flow'
        return 'assistant_default'

    @staticmethod
    def _route_after_hitl_clarification(state: ChatGraphState) -> str:
        if state.get('workflow_action') == 'cancel_hitl':
            return 'transaction_flow'
        return 'extract_transaction_candidate'

    async def _hitl_clarification_node(self, state: ChatGraphState) -> dict[str, Any]:
        missing_fields = state.get('hitl_missing_fields', [])
        attempt_number = max(1, int(state.get('hitl_attempt_count', 1)))
        question = self._build_hitl_question(missing_fields=missing_fields, attempt_number=attempt_number)

        human_response = interrupt(
            {
                'question': question,
                'attempt': attempt_number,
                'max_turns': self._hitl_max_turns,
                'missing_fields': missing_fields,
            }
        )

        if self._proposal_action(str(human_response)) == 'cancel_proposal':
            return {
                'workflow_action': 'cancel_hitl',
                'hitl_active': False,
                'hitl_attempt_count': 0,
                'hitl_context_message': None,
                'hitl_missing_fields': [],
                'manual_transaction_input_required': False,
            }

        merged_context = self._merge_hitl_context(state.get('hitl_context_message'), str(human_response))
        return {
            'hitl_context_message': merged_context,
            'workflow_action': 'build_proposal',
            'manual_transaction_input_required': False,
        }

    async def _transaction_flow(self, state: ChatGraphState) -> dict[str, Any]:
        action = state.get('workflow_action')
        latest_user_message = self._latest_user_message(state.get('messages', []))
        pending_proposal = state.get('pending_proposal')

        if action in {'build_proposal', 'build_proposal_ready'}:
            candidate = state.get('extracted_candidate')
            if candidate is None:
                return {
                    'extracted_candidate': None,
                    'transaction_logged': False,
                    'manual_transaction_input_required': False,
                    'messages': [AIMessage(content='Unable to build a proposal from this message yet.')],
                }

            proposal = await self._build_proposal(user_id=self._user_id_from_state(state), candidate=candidate)
            if isinstance(proposal, str):
                return {
                    'extracted_candidate': None,
                    'hitl_active': False,
                    'hitl_attempt_count': 0,
                    'hitl_context_message': None,
                    'hitl_missing_fields': [],
                    'transaction_logged': False,
                    'manual_transaction_input_required': False,
                    'messages': [AIMessage(content=proposal)],
                }

            return {
                'pending_proposal': proposal,
                'extracted_candidate': None,
                'hitl_active': False,
                'hitl_attempt_count': 0,
                'hitl_context_message': None,
                'hitl_missing_fields': [],
                'transaction_logged': False,
                'manual_transaction_input_required': False,
                'messages': [AIMessage(content=self._format_proposal_message(proposal))],
            }

        if action == 'manual_fallback':
            fallback_message = self._format_manual_fallback_message(state.get('hitl_missing_fields', []))
            manual_prefill_proposal = await self._build_manual_prefill_proposal(
                user_id=self._user_id_from_state(state),
                candidate=state.get('extracted_candidate'),
                context_message=state.get('hitl_context_message'),
            )
            return {
                'pending_proposal': manual_prefill_proposal,
                'extracted_candidate': None,
                'hitl_active': False,
                'hitl_attempt_count': 0,
                'hitl_context_message': None,
                'hitl_missing_fields': [],
                'transaction_logged': False,
                'manual_transaction_input_required': True,
                'messages': [AIMessage(content=fallback_message)],
            }

        if action == 'cancel_hitl':
            return {
                'pending_proposal': None,
                'extracted_candidate': None,
                'hitl_active': False,
                'hitl_attempt_count': 0,
                'hitl_context_message': None,
                'hitl_missing_fields': [],
                'transaction_logged': False,
                'manual_transaction_input_required': False,
                'messages': [AIMessage(content='Okay, I stopped this transaction draft. Nothing was logged.')],
            }

        if action == 'confirm_proposal':
            if pending_proposal is None:
                return {
                    'extracted_candidate': None,
                    'transaction_logged': False,
                    'messages': [AIMessage(content='There is no pending proposal to confirm.')],
                }

            transaction = await self._transaction_service.create_transaction(
                CreateTransactionInput(
                    user_id=self._user_id_from_state(state),
                    account_id=uuid.UUID(pending_proposal['account_id']),
                    type=TransactionType(pending_proposal['type']),
                    amount_paise=int(pending_proposal['amount_paise']),
                    occurred_at=datetime.fromisoformat(pending_proposal['occurred_at']),
                    category_id=uuid.UUID(pending_proposal['category_id']),
                    merchant=pending_proposal.get('merchant'),
                    note=pending_proposal.get('note') or 'Logged via chat confirmation',
                )
            )

            amount_inr = f'{transaction.amount_paise / 100:.2f}'
            merchant = transaction.merchant or 'merchant not provided'
            return {
                'pending_proposal': None,
                'extracted_candidate': None,
                'hitl_active': False,
                'hitl_attempt_count': 0,
                'hitl_context_message': None,
                'hitl_missing_fields': [],
                'transaction_logged': True,
                'manual_transaction_input_required': False,
                'messages': [
                    AIMessage(
                        content=(
                            f'Logged transaction: {transaction.type.value} INR {amount_inr} '
                            f'(merchant: {merchant}).'
                        )
                    )
                ],
            }

        if action == 'cancel_proposal':
            return {
                'pending_proposal': None,
                'extracted_candidate': None,
                'hitl_active': False,
                'hitl_attempt_count': 0,
                'hitl_context_message': None,
                'hitl_missing_fields': [],
                'transaction_logged': False,
                'manual_transaction_input_required': False,
                'messages': [AIMessage(content='Proposal discarded. Nothing was logged.')],
            }

        if action == 'edit_proposal':
            if pending_proposal is None:
                return {
                    'extracted_candidate': None,
                    'transaction_logged': False,
                    'messages': [AIMessage(content='There is no pending proposal to edit.')],
                }

            updated = dict(pending_proposal)
            updated_amount = self._extract_amount_paise(latest_user_message)
            if updated_amount is not None:
                updated['amount_paise'] = updated_amount

            updated_merchant = self._extract_merchant(latest_user_message)
            if updated_merchant is not None:
                updated['merchant'] = updated_merchant

            return {
                'pending_proposal': updated,
                'extracted_candidate': None,
                'hitl_active': False,
                'hitl_attempt_count': 0,
                'hitl_context_message': None,
                'hitl_missing_fields': [],
                'transaction_logged': False,
                'manual_transaction_input_required': False,
                'messages': [AIMessage(content=f'Updated proposal. {self._format_proposal_message(updated)}')],
            }

        if pending_proposal is not None:
            return {
                'extracted_candidate': None,
                'hitl_active': False,
                'transaction_logged': False,
                'manual_transaction_input_required': False,
                'messages': [
                    AIMessage(
                        content=(
                            f'{self._format_proposal_summary(pending_proposal)} '
                            "Reply 'confirm' to log, 'cancel' to discard, or send an edit "
                            "like 'make it INR 250'."
                        )
                    )
                ],
            }

        return {
            'extracted_candidate': None,
            'hitl_active': False,
            'transaction_logged': False,
            'manual_transaction_input_required': False,
            'messages': [AIMessage(content='No pending transaction proposal right now.')],
        }

    def _next_hitl_step(
        self,
        *,
        latest_user_message: str,
        current_context: str | None,
        current_hitl_attempt_count: int,
        candidate: dict[str, Any] | None,
    ) -> dict[str, Any]:
        updated_context = self._merge_hitl_context(current_context, latest_user_message)
        missing_fields = self._infer_missing_fields(updated_context, candidate)
        next_attempt_count = current_hitl_attempt_count + 1

        if next_attempt_count > self._hitl_max_turns:
            return {
                'workflow_action': 'manual_fallback',
                'hitl_active': False,
                'hitl_attempt_count': 0,
                'hitl_context_message': updated_context,
                'extracted_candidate': candidate,
                'hitl_missing_fields': missing_fields,
                'manual_transaction_input_required': True,
            }

        return {
            'workflow_action': 'hitl_clarification',
            'hitl_active': True,
            'hitl_attempt_count': next_attempt_count,
            'hitl_context_message': updated_context,
            'hitl_missing_fields': missing_fields,
            'manual_transaction_input_required': False,
        }

    def _infer_missing_fields(self, message: str, candidate: dict[str, Any] | None) -> list[str]:
        normalized_message = message.lower()
        detected_type = self._detect_transaction_type(normalized_message)
        transaction_type = (candidate or {}).get('type') or (detected_type.value if detected_type is not None else None)
        amount_paise = (candidate or {}).get('amount_paise') or self._extract_amount_paise(message)
        merchant = (candidate or {}).get('merchant') or self._extract_merchant(message)

        has_date_hint = self._has_date_hint(normalized_message)

        missing_fields: list[str] = []
        if transaction_type is None:
            missing_fields.append('type')
        if amount_paise is None:
            missing_fields.append('amount')
        if merchant is None:
            missing_fields.append('merchant')
        if not has_date_hint:
            missing_fields.append('date')

        if not missing_fields:
            missing_fields.append('context')

        return missing_fields

    def _build_hitl_question(self, *, missing_fields: list[str], attempt_number: int) -> str:
        primary_missing = missing_fields[0]
        attempts_label = f'({attempt_number}/{self._hitl_max_turns})'

        if primary_missing == 'type':
            return f"To log this correctly {attempts_label}, is this an expense, income, refund, or transfer?"
        if primary_missing == 'amount':
            return f"I need the exact amount {attempts_label}. How much was it in INR?"
        if primary_missing == 'merchant':
            return f"I can continue once I know the merchant {attempts_label}. Which store/person was this with?"
        if primary_missing == 'date':
            return f"Please confirm when this happened {attempts_label} (today, yesterday, or a date)."

        return (
            f"I still need one more detail {attempts_label} to be confident. "
            'Please share a complete sentence with amount, type, merchant, and date.'
        )

    def _format_manual_fallback_message(self, missing_fields: list[str]) -> str:
        unresolved_labels = ', '.join(missing_fields)
        return (
            f"I still can't reach {self._proposal_confidence_threshold}% confidence after "
            f'{self._hitl_max_turns} clarification turns. '
            f'Please add this manually using the Add Transaction form (unclear: {unresolved_labels}).'
        )

    @staticmethod
    def _merge_hitl_context(current_context: str | None, latest_message: str) -> str:
        normalized_latest_message = latest_message.strip()
        if not current_context:
            return normalized_latest_message

        normalized_context = current_context.strip()
        if normalized_latest_message and normalized_latest_message.lower() in normalized_context.lower():
            return normalized_context

        if not normalized_latest_message:
            return normalized_context

        return f'{normalized_context}\n{normalized_latest_message}'

    async def _assistant_default(self, state: ChatGraphState) -> dict[str, list[AIMessage]]:
        latest_user_message = self._latest_user_message(state.get('messages', []))
        if not latest_user_message:
            return {'messages': [AIMessage(content=_REFUSAL_MESSAGE)]}

        previous_user_message = self._previous_user_message(state.get('messages', []))
        if previous_user_message:
            reply = f'Got it. You said: "{latest_user_message}". Earlier you mentioned: "{previous_user_message}".'
        else:
            reply = f'Got it. You said: "{latest_user_message}".'

        return {'messages': [AIMessage(content=reply)]}

    @staticmethod
    async def _assistant_refusal(_: ChatGraphState) -> dict[str, list[AIMessage]]:
        return {'messages': [AIMessage(content=_REFUSAL_MESSAGE)]}

    async def _build_proposal(self, *, user_id: uuid.UUID, candidate: dict[str, Any]) -> dict[str, Any] | str:
        if candidate['type'] == TransactionType.TRANSFER.value:
            return 'Transfer extraction is detected, but transfer proposal flow is not enabled yet.'

        accounts = await self._account_repository.list_for_user(user_id)
        if not accounts:
            return 'I can log this transaction, but please create an account first.'

        account = next((item for item in accounts if item.is_active), accounts[0])

        category_type = (
            CategoryType.EXPENSE if candidate['type'] == TransactionType.EXPENSE.value else CategoryType.INCOME
        )
        categories = await self._category_repository.list_for_user(user_id)
        category = next((item for item in categories if item.type == category_type), None)
        if category is None:
            label = 'expense' if category_type == CategoryType.EXPENSE else 'income'
            return f'I can log this transaction, but please create an {label} category first.'

        return {
            'type': candidate['type'],
            'amount_paise': candidate['amount_paise'],
            'occurred_at': candidate['occurred_at'],
            'merchant': candidate.get('merchant'),
            'note': candidate.get('note'),
            'confidence_score': int(candidate.get('confidence_score', 0)),
            'account_id': str(account.id),
            'account_name': account.name,
            'category_id': str(category.id),
            'category_name': category.name,
        }

    async def _build_manual_prefill_proposal(
        self,
        *,
        user_id: uuid.UUID,
        candidate: dict[str, Any] | None,
        context_message: str | None,
    ) -> dict[str, Any]:
        normalized_candidate = candidate or {}

        accounts = await self._account_repository.list_for_user(user_id)
        account = next((item for item in accounts if item.is_active), accounts[0]) if accounts else None

        raw_type = str(normalized_candidate.get('type') or '').strip().lower()
        parsed_type = self._map_transaction_type(raw_type)
        transaction_type = parsed_type or TransactionType.EXPENSE

        categories = await self._category_repository.list_for_user(user_id)
        if transaction_type == TransactionType.EXPENSE:
            desired_category_type = CategoryType.EXPENSE
        elif transaction_type in {TransactionType.INCOME, TransactionType.REFUND}:
            desired_category_type = CategoryType.INCOME
        else:
            desired_category_type = None

        category = None
        if desired_category_type is not None:
            category = next((item for item in categories if item.type == desired_category_type), None)
        if category is None and categories:
            category = categories[0]

        amount_paise = 0
        raw_amount = normalized_candidate.get('amount_paise')
        if isinstance(raw_amount, int) and raw_amount > 0:
            amount_paise = raw_amount

        occurred_at = str(normalized_candidate.get('occurred_at') or datetime.now(UTC).isoformat())
        merchant = self._sanitize_merchant(normalized_candidate.get('merchant'))
        note = self._sanitize_note(normalized_candidate.get('note')) or self._infer_note_from_message(
            context_message or ''
        )
        confidence_score = int(normalized_candidate.get('confidence_score', 0))

        return {
            'type': transaction_type.value,
            'amount_paise': amount_paise,
            'occurred_at': occurred_at,
            'merchant': merchant,
            'note': note,
            'account_id': str(account.id) if account else '',
            'account_name': account.name if account else 'Select account',
            'category_id': str(category.id) if category else '',
            'category_name': category.name if category else 'Select category',
            'confidence_score': max(0, min(100, confidence_score)),
        }

    async def _extract_candidate(self, message: str) -> dict[str, Any] | None:
        llm_candidate = await self._extract_candidate_with_llm(message)
        if llm_candidate is not None:
            return llm_candidate
        return self._extract_candidate_rule_based(message)

    async def _extract_candidate_with_llm(self, message: str) -> dict[str, Any] | None:
        if self._llm_extraction_chain is None:
            return None

        try:
            extracted = await self._llm_extraction_chain.ainvoke(
                {'message': message, 'today_utc': datetime.now(UTC).isoformat()}
            )
        except Exception:
            return None

        if not extracted.is_transaction:
            return None

        if extracted.confidence < 0.55:
            return None

        transaction_type = self._map_transaction_type(extracted.transaction_type)
        if transaction_type is None or extracted.amount is None:
            return None

        amount_paise = self._to_paise(extracted.amount)
        if amount_paise is None:
            return None

        occurred_at = extracted.occurred_at or datetime.now(UTC)
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)

        inferred_note = self._sanitize_note(extracted.note) or self._infer_note_from_message(message)

        return {
            'type': transaction_type.value,
            'amount_paise': amount_paise,
            'occurred_at': occurred_at.isoformat(),
            'merchant': self._sanitize_merchant(extracted.merchant),
            'note': inferred_note,
            'confidence_score': max(0, min(100, int(round(extracted.confidence * 100)))),
        }

    def _extract_candidate_rule_based(self, message: str) -> dict[str, Any] | None:
        normalized = message.lower()
        transaction_type = self._detect_transaction_type(normalized)
        if transaction_type is None:
            return None

        amount_paise = self._extract_amount_paise(message)
        if amount_paise is None:
            return None

        occurred_at = datetime.now(UTC)
        has_date_hint = False
        if 'yesterday' in normalized:
            occurred_at -= timedelta(days=1)
            has_date_hint = True
        elif 'today' in normalized:
            has_date_hint = True

        merchant = self._extract_merchant(message)

        return {
            'type': transaction_type.value,
            'amount_paise': amount_paise,
            'occurred_at': occurred_at.isoformat(),
            'merchant': merchant,
            'note': self._infer_note_from_message(message),
            'confidence_score': self._confidence_score_from_rule_based(
                message=message,
                merchant=merchant,
                has_date_hint=has_date_hint,
            ),
        }

    @staticmethod
    def _map_transaction_type(value: str | None) -> TransactionType | None:
        if value is None:
            return None
        normalized_value = value.strip().lower()
        for txn_type in TransactionType:
            if txn_type.value == normalized_value:
                return txn_type
        return None

    @staticmethod
    def _sanitize_merchant(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip(' .,!?;:')
        if not cleaned:
            return None
        return cleaned[:255]

    @staticmethod
    def _sanitize_note(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = ' '.join(value.strip().split())
        if not cleaned:
            return None
        return cleaned[:500]

    @staticmethod
    def _infer_note_from_message(message: str) -> str | None:
        cleaned_message = ' '.join(message.strip().split())
        if len(cleaned_message) < 18:
            return None
        return cleaned_message[:500]

    @staticmethod
    def _has_explicit_currency_hint(message: str) -> bool:
        has_currency_prefix = _CURRENCY_PREFIX_PATTERN.search(message) is not None
        has_currency_suffix = _CURRENCY_SUFFIX_PATTERN.search(message) is not None
        return has_currency_prefix or has_currency_suffix

    @staticmethod
    def _has_date_hint(message: str) -> bool:
        if 'today' in message or 'yesterday' in message:
            return True
        return bool(re.search(r'\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b', message))

    @staticmethod
    def _confidence_score_from_rule_based(*, message: str, merchant: str | None, has_date_hint: bool) -> int:
        score = 68
        if merchant:
            score += 12
        if LangGraphChatOrchestrator._has_explicit_currency_hint(message):
            score += 10
        if has_date_hint:
            score += 6
        return min(score, 89)

    @staticmethod
    def _proposal_action(message: str) -> str | None:
        normalized = ' '.join(message.lower().split())
        if normalized in {'confirm', 'yes', 'y', 'ok', 'okay', 'proceed', 'log it'} or 'confirm' in normalized:
            return 'confirm_proposal'
        if normalized in {'cancel', 'no', 'discard', 'stop'} or 'cancel' in normalized or 'discard' in normalized:
            return 'cancel_proposal'
        if any(keyword in normalized for keyword in ('edit', 'change', 'instead', 'make it', 'update')):
            return 'edit_proposal'
        if LangGraphChatOrchestrator._extract_amount_paise(message) is not None:
            return 'edit_proposal'
        return None

    @staticmethod
    def _format_proposal_summary(proposal: dict[str, Any]) -> str:
        amount_inr = f"{int(proposal['amount_paise']) / 100:.2f}"
        merchant = proposal.get('merchant') or 'merchant not provided'
        date_label = proposal['occurred_at'][:10]
        confidence_score = int(proposal.get('confidence_score', 0))
        details = f'merchant: {merchant}, date: {date_label}, confidence: {confidence_score}%'
        return (
            f"Proposed {proposal['type']} transaction: INR {amount_inr} in {proposal['account_name']} "
            f"under {proposal['category_name']} ({details})."
        )

    @staticmethod
    def _format_proposal_message(proposal: dict[str, Any]) -> str:
        summary = LangGraphChatOrchestrator._format_proposal_summary(proposal)
        return f"{summary} Reply 'confirm' to log, 'cancel' to discard, or send edits."

    @staticmethod
    def _detect_transaction_type(message: str) -> TransactionType | None:
        if any(keyword in message for keyword in _REFUND_KEYWORDS):
            return TransactionType.REFUND
        if any(keyword in message for keyword in _INCOME_KEYWORDS):
            return TransactionType.INCOME
        if any(keyword in message for keyword in _EXPENSE_KEYWORDS):
            return TransactionType.EXPENSE
        return None

    @staticmethod
    def _extract_amount_paise(message: str) -> int | None:
        amount_token = None

        for pattern in (_CURRENCY_PREFIX_PATTERN, _CURRENCY_SUFFIX_PATTERN, _ANY_NUMBER_PATTERN):
            match = pattern.search(message)
            if match:
                amount_token = match.group(1)
                break

        if amount_token is None:
            return None

        return LangGraphChatOrchestrator._to_paise(amount_token)

    @staticmethod
    def _to_paise(value: float | int | str) -> int | None:
        normalized_amount = str(value).replace(',', '').strip()
        try:
            amount_decimal = Decimal(normalized_amount)
        except InvalidOperation:
            return None

        amount_paise = int((amount_decimal * Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        if amount_paise <= 0:
            return None
        return amount_paise

    @staticmethod
    def _extract_merchant(message: str) -> str | None:
        match = _MERCHANT_PATTERN.search(message)
        if not match:
            return None

        merchant = match.group(1).strip(' .,!?;:')
        lowered = merchant.lower()

        for marker in (' today', ' yesterday', ' on ', ' via ', ' using '):
            marker_index = lowered.find(marker)
            if marker_index > 0:
                merchant = merchant[:marker_index].strip(' .,!?;:')
                break

        if not merchant:
            return None

        return merchant[:255]

    @staticmethod
    def _extract_message_from_prompt(prompt_value: Any) -> str:
        messages = getattr(prompt_value, 'messages', [])
        if not messages:
            return ''
        return str(messages[-1].content)

    @staticmethod
    def _latest_user_message(messages: list[BaseMessage]) -> str:
        for item in reversed(messages):
            if isinstance(item, HumanMessage):
                return str(item.content)
        return ''

    @staticmethod
    def _previous_user_message(messages: list[BaseMessage]) -> str:
        seen_latest_user = False
        for item in reversed(messages):
            if not isinstance(item, HumanMessage):
                continue
            if not seen_latest_user:
                seen_latest_user = True
                continue
            return str(item.content)
        return ''

    @staticmethod
    def _user_id_from_state(state: ChatGraphState) -> uuid.UUID:
        user_id_value = state.get('runtime_user_id')
        if not user_id_value:
            raise ValueError('Missing runtime_user_id in graph state')
        return uuid.UUID(str(user_id_value))

    @staticmethod
    def _as_guardrail_decision(value: GuardrailDecision | str) -> GuardrailDecision:
        if isinstance(value, GuardrailDecision):
            return value
        normalized_value = str(value).strip().lower()
        for decision in GuardrailDecision:
            if decision.value == normalized_value:
                return decision
        return GuardrailDecision.BLOCK

    @staticmethod
    def _as_detected_intent(value: DetectedIntent | str) -> DetectedIntent:
        if isinstance(value, DetectedIntent):
            return value
        normalized_value = str(value).strip().lower()
        for intent in DetectedIntent:
            if intent.value == normalized_value:
                return intent
        return DetectedIntent.OFF_TOPIC
