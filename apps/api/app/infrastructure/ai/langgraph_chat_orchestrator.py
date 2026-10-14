from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import Command, interrupt
from langsmith import traceable
from pydantic import BaseModel, Field

from app.application.dto import CreateTransactionInput
from app.application.services.transaction_service import TransactionService
from app.domain.entities import CategoryType, TransactionType
from app.domain.ports import (
    ChatTurnResult,
    DetectedIntent,
    GuardrailAssessment,
    GuardrailDecision,
    IntentClassifier,
    PendingTransactionProposal,
    SemanticGuardrail,
)
from app.domain.repositories import AccountRepository, CategoryRepository
from app.infrastructure.ai.tools import CategoryTools, LangGraphFinanceTools, TransactionQueryTools

logger = logging.getLogger(__name__)

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

_EXPENSE_KEYWORDS = ('spend', 'spent', 'paid', 'pay', 'bought', 'purchase', 'purchased', 'debited')
_INCOME_KEYWORDS = ('received', 'credited', 'salary', 'earned', 'income', 'got paid')
_REFUND_KEYWORDS = ('refund', 'refunded', 'reimbursed', 'reimbursement', 'cashback')

_TRANSACTION_ACTION_KEYWORDS = (
    'spend',
    'spent',
    'pay',
    'paid',
    'bought',
    'purchase',
    'purchased',
    'debit',
    'debited',
    'credit',
    'credited',
    'received',
    'salary',
    'income',
    'refund',
    'transfer',
    'transaction',
    'log',
)

_STRONG_TRANSACTION_ACTION_KEYWORDS = (
    'spend',
    'spent',
    'pay',
    'paid',
    'bought',
    'purchase',
    'purchased',
    'debit',
    'debited',
    'credit',
    'credited',
    'received',
    'salary',
    'income',
    'refund',
    'transfer',
)

_NON_TRANSACTION_QUERY_CUES = (
    'what did i',
    'how much',
    'show',
    'summary',
    'this week',
    'this month',
    'weekly',
    'monthly',
    'trend',
    'total',
    'budget',
    'report',
)

_FINANCE_QUERY_HINTS = (
    'spend',
    'spent',
    'spending',
    'transaction',
    'transactions',
    'account',
    'balance',
    'budget',
    'history',
)


class TransactionExtractionOutput(BaseModel):
    is_transaction: bool = Field(
        default=False,
        description=(
            'True only when the user is reporting or asking to record an actual financial transaction. '
            'Questions about spending history or hypothetical examples are not transactions.'
        ),
    )
    transaction_type: str | None = Field(
        default=None,
        description=(
            'Transaction direction/type: expense, income, refund, or transfer. '
            'Use the meaning of the user message; return null if it cannot be determined.'
        ),
    )
    amount: float | None = Field(
        default=None,
        description=(
            'Positive amount in major currency units (INR rupees, not paise). '
            'Convert spoken or formatted amounts to a number; return null if no amount is stated or inferable.'
        ),
    )
    selected_account: str | None = Field(
        default=None,
        description=(
            'Exact name of one account from the supplied account catalog when the user explicitly names or '
            'clearly selects it. Never invent an account or silently substitute another account. Return null '
            'when no account preference is stated or the match is ambiguous.'
        ),
    )
    account_hint: str | None = Field(
        default=None,
        description=(
            'The account or institution name/description the user explicitly mentions as the payment source, '
            'even if it does not exactly match one catalog account (for example, "SBI"). Return null when the '
            'user gives no account preference.'
        ),
    )
    selected_category: str | None = Field(
        default=None,
        description=(
            'Exact name of an existing user category from the supplied category catalog, only when it is an '
            'appropriate match explicitly stated or strongly supported by the transaction context. '
            'Never choose a merely closest or default category; otherwise return null.'
        ),
    )
    category: str | None = Field(
        default=None,
        description=(
            'The category concept expressed or strongly implied by the user, including a useful category name '
            'that could be offered for creation when no existing category matches (for example, Hotel or '
            'Electronics). Do not copy a merchant or location as a category. Return null when no category '
            'concept is supported by the message.'
        ),
    )
    merchant: str | None = Field(
        default=None,
        description=(
            'Name of the store, business, person, or other identifiable payee/merchant if stated or reliably '
            'implied (for example, Amazon). Do not invent a business name from a generic venue type or location; '
            'put useful context such as "hotel in Delhi" in note instead. Merchant is optional; return null '
            'rather than asking the user when it cannot be identified.'
        ),
    )
    note: str | None = Field(
        default=None,
        description=(
            'Brief transaction context not represented by type, amount, date, merchant, or category, such as '
            '"hotel stay in Delhi" or "new phone". Preserve useful purpose/location details without inventing facts.'
        ),
    )
    occurred_at: datetime | None = Field(
        default=None,
        description=(
            'Date and time when the transaction occurred, as an ISO-8601-compatible datetime. Resolve relative '
            'dates such as today, yesterday, or 2 days ago using the supplied current datetime as the reference. '
            'If the user gives no date, return null; the application will default it to the current datetime.'
        ),
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            'Overall confidence from 0.0 to 1.0 that the transaction is real and the extracted type, amount, '
            'date, merchant, and category are supported by the message. Missing optional merchant/category '
            'information alone should not make an otherwise clear transaction invalid.'
        ),
    )


class HitlCategoryResolutionOutput(BaseModel):
    selected_category: str | None = Field(default=None)
    create_category: str | None = Field(default=None)


class FinanceQueryPlan(BaseModel):
    action: Literal['query', 'drill_down', 'format_previous'] = Field(
        default='query',
        description=(
            'Choose query for a new database question, drill_down to fetch records behind a prior summary, '
            'or format_previous to sort/reformat stored prior results without querying again.'
        ),
    )
    query_kind: Literal['summary', 'transaction_list'] = Field(
        description=(
            'summary when the user asks how much, totals, or category spend; transaction_list when asking '
            'what transactions/items occurred in a time period.'
        )
    )
    date_period: Literal[
        'today',
        'yesterday',
        'this_week',
        'last_week',
        'this_month',
        'last_month',
        'last_n_days',
        'last_n_weeks',
        'recent_default',
    ] = Field(description='The calendar period requested by the user.')
    period_count: int | None = Field(
        default=None,
        ge=1,
        le=180,
        description='Number of days or weeks when date_period is last_n_days or last_n_weeks.',
    )
    category_names: list[str] = Field(
        default_factory=list,
        max_length=5,
        description=(
            'Every expense category explicitly or clearly requested, such as Food and Transport. '
            'Return an empty list when no category is requested.'
        ),
    )
    category_scope: Literal['all', 'selected', 'unspecified'] = Field(
        default='all',
        description=(
            'Use all when no category filter is requested, selected when one or more category names are supplied, '
            'and unspecified when the user requests particular categories but does not identify them.'
        ),
    )
    transaction_type: Literal['expense', 'income', 'all'] = Field(
        default='all',
        description='Filter transaction-list results by direction; use expense when drilling down into spending.',
    )
    result_format: Literal['table', 'list'] = Field(
        default='list',
        description='Requested presentation for prior transaction rows when action is format_previous.',
    )
    sort_order: Literal['newest_first', 'oldest_first'] = Field(
        default='newest_first',
        description='Chronological order for transaction rows; newest_first is the default unless user asks ascending.',
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class FinanceQueryReply(BaseModel):
    reply: str = Field(
        description=(
            'A concise, natural answer to the user using only the supplied computed facts. Preserve amounts, '
            'periods, category names, and counts exactly; do not add calculations or unsupported claims.'
        )
    )


class SupervisorDecision(BaseModel):
    workflow: Literal['transaction', 'analytics', 'format_previous', 'respond', 'refuse'] = Field(
        description=(
            'Select exactly one registered workflow for the current user request. Do not select unavailable split, '
            'memory, account, or file workflows.'
        )
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = Field(default='', max_length=240)
    response: str | None = Field(
        default=None,
        max_length=600,
        description=(
            'Short user-facing clarification or capability notice for respond; '
            'do not include unverified facts.'
        ),
    )


class ChatGraphState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    workflow_action: str
    pending_proposal: dict[str, Any] | None
    extracted_candidate: dict[str, Any] | None
    user_accounts: list[dict[str, Any]]
    user_categories: list[dict[str, Any]]
    runtime_user_id: str
    runtime_timezone: str
    query_plan: dict[str, Any] | None
    last_finance_query_plan: dict[str, Any] | None
    last_finance_query_result: dict[str, Any] | None
    supervisor_workflow: str | None
    supervisor_confidence: float
    supervisor_rationale: str
    supervisor_response: str | None
    query_tool_call_ids: list[str]
    transaction_logged: bool
    manual_transaction_input_required: bool
    hitl_active: bool
    hitl_attempt_count: int
    hitl_context_message: str | None
    hitl_missing_fields: list[str]
    hitl_category_options: list[str]
    hitl_account_options: list[str]
    hitl_suggested_category: str | None
    manual_prefill_proposal: dict[str, Any] | None
    query_tool_call_id: str | None
    intent: str | None
    guardrail_decision: str
    guardrail_confidence: float
    guardrail_layer: str
    insights: list[dict[str, str]] | None
    agent_correction: dict[str, Any] | None


class CategoryToolGraphState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    runtime_user_id: str
    user_categories: list[dict[str, Any]]
    requested_category_name: str
    requested_category_type: str
    category_tool_call_id: str | None
    created_category: dict[str, Any] | None


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
        category_tools: CategoryTools | None = None,
        transaction_query_tools: TransactionQueryTools | None = None,
        extraction_llm: Any | None = None,
        proposal_confidence_threshold: int = 80,
        hitl_max_turns: int = 5,
        deterministic_transaction_first: bool = True,
    ) -> None:
        self._semantic_guardrail = semantic_guardrail
        self._intent_classifier = intent_classifier
        self._transaction_service = transaction_service
        self._account_repository = account_repository
        self._category_repository = category_repository
        self._category_tools = category_tools or CategoryTools(category_repository=category_repository)
        self._transaction_query_tools = transaction_query_tools or TransactionQueryTools(
            transaction_repository=transaction_service.transaction_repository,
            account_repository=account_repository,
            category_repository=category_repository,
        )
        self._langgraph_finance_tools = LangGraphFinanceTools(
            category_tools=self._category_tools,
            transaction_query_tools=self._transaction_query_tools,
        )
        self._category_tool_node = ToolNode(
            self._langgraph_finance_tools.build_category_tools(),
            messages_key='messages',
        )
        self._query_tool_node = ToolNode(
            self._langgraph_finance_tools.build_query_tools(),
            messages_key='messages',
        )
        self._proposal_confidence_threshold = max(0, min(int(proposal_confidence_threshold), 100))
        self._hitl_max_turns = max(1, int(hitl_max_turns))
        self._deterministic_transaction_first = bool(deterministic_transaction_first)

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
        self._llm_hitl_category_resolution_chain = None
        self._supervisor_workflow_chain = None
        self._llm_query_plan_chain = None
        self._llm_query_reply_chain = None
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
                            'Choose selected_account only from the supplied accounts catalog. Capture an explicit '
                            'but unresolved account/institution name in account_hint; do not replace it with the '
                            'default account. If the user gives no account preference, leave both fields null. '
                            'Resolve occurred_at from relative date language using the supplied current datetime; '
                            'return null only when the user gives no date. '
                            'For selected_category, choose only an appropriate exact existing category from the '
                            'catalog; never choose a merely closest or default category. '
                            'For category, extract the user-supported category concept even if it is not in the '
                            'catalog, so the application can offer to create it; return null if no category concept '
                            'is supported. '
                            'Extract a merchant only when an identifiable merchant is stated or reliably implied; '
                            'do not invent a business from a venue type or location. Preserve details such as '
                            '"hotel in Delhi" or "new phone" in note. Merchant is optional. '
                            'Set confidence between 0 and 1 for extraction certainty.'
                        ),
                    ),
                    (
                        'human',
                        'Today is {today_utc}. User message: {message}. '
                        'Available accounts (JSON): {accounts_catalog}. '
                        'Available categories (JSON): {categories_catalog}',
                    ),
                ]
            )
            self._llm_extraction_chain = extraction_prompt | extraction_llm.with_structured_output(
                TransactionExtractionOutput
            )

            hitl_category_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        'system',
                        (
                            'You resolve user replies during a category clarification step. '
                            'Return selected_category when user picks an existing category from options. '
                            'Return create_category when user clearly asks or confirms creating a new category. '
                            'Treat semantic matches and short replies (for example yes transport, first one) as valid. '
                            'If uncertain, keep both fields null. '
                            'Never hallucinate categories outside the user reply/options.'
                        ),
                    ),
                    (
                        'human',
                        'User reply: {user_reply}. '
                        'Available category options (JSON): {category_options_json}. '
                        'Suggested new category name: {suggested_category_name}.',
                    ),
                ]
            )
            self._llm_hitl_category_resolution_chain = (
                hitl_category_prompt | extraction_llm.with_structured_output(HitlCategoryResolutionOutput)
            )

            supervisor_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        'system',
                        (
                            'You are the central workflow supervisor for a personal finance assistant. '
                            'Choose exactly one registered workflow: transaction (propose a user-reported transaction; '
                            'writes still require explicit confirmation), analytics (answer a new financial question '
                            'with database tools), format_previous (sort or present an existing structured analytics '
                            'result without re-querying), respond (safe conversational reply or ask clarification), or '
                            'refuse (clearly off-topic request). Choose only workflows in this registry. '
                            'Split, memory, '
                            'account-balance specialist, and file-export workflows are not registered yet; do not '
                            'pretend they are available. Use recent conversation and the prior query result to resolve '
                            'follow-ups. If prior results exist and the user asks to format them, '
                            'choose format_previous. '
                            'If the user reports a new transaction with an amount, choose transaction even if earlier '
                            'messages discussed spending. If uncertain, choose respond rather than '
                            'inventing an action. '
                            'Your decision only routes to a specialist; it does not execute writes, calculate money, '
                            'override guardrails, or change authenticated user scope. For respond, provide a brief '
                            'clarification or explain which registered capability is missing; never invent results.'
                        ),
                    ),
                    (
                        'human',
                        'Current message: {message}\nRecent conversation: {conversation_context}\n'
                        'Classified intent hint: {intent}\nGuardrail: {guardrail_decision}\n'
                        'Previous query plan: {previous_plan}\nPrevious structured result: {previous_result}',
                    ),
                ]
            )
            self._supervisor_workflow_chain = (
                supervisor_prompt | extraction_llm.with_structured_output(SupervisorDecision)
            )

            query_plan_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        'system',
                        (
                            'Interpret a personal-finance query into a structured plan. Choose summary when the '
                            'user asks how much they spent, totals, or spending by category. Choose transaction_list '
                            'when they ask what transactions happened or simply name a period such as yesterday. '
                            'Extract every category the user asks about, including multiple categories joined by '
                            'and, or, commas. Set category_scope=all when no category filter is requested, '
                            'selected when category names are supplied, and unspecified when the user asks about '
                            'some categories but does not identify them; never treat unspecified as all spending. '
                            'Resolve short follow-up messages such as “where?” using recent conversation and the '
                            'previous query plan. When the user asks where a prior spending total went, return '
                            'action=drill_down, set query_kind=transaction_list, preserve that plan’s date/category '
                            'scope, and set transaction_type=expense. When the user asks to sort, format, or show '
                            'previously returned records as a table/list, choose action=format_previous, preserve '
                            'the prior result and do not request a new query. Choose sort_order=oldest_first for '
                            'ascending/oldest first and newest_first otherwise. '
                            'Resolve phrases like today, '
                            'yesterday, this week, last week, this month, last month, and the last N days/weeks '
                            'relative to the supplied local date and timezone. Do not calculate money or invent '
                            'transactions; the database tools do that.'
                        ),
                    ),
                    (
                        'human',
                        'Recent conversation: {conversation_context}\n'
                        'Previous finance query plan: {previous_query_plan}\n'
                        'Previous structured result: {previous_query_result}\n'
                        'Local now: {local_now}. Timezone: {timezone}. Current user query: {message}',
                    ),
                ]
            )
            self._llm_query_plan_chain = query_plan_prompt | extraction_llm.with_structured_output(FinanceQueryPlan)

            query_reply_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        'system',
                        (
                            'Write one concise, natural answer to the finance query using only the supplied facts. '
                            'The facts were computed by database tools and are authoritative. Do not recalculate, '
                            'round, infer, or invent any amount, count, date, category, merchant, or comparison. '
                            'Mention the requested category and period when provided. Avoid canned insight labels '
                            'and do not claim a trend unless trend data is present. When the user asks for details, '
                            'a breakdown, or multiple records, prefer a compact Markdown table when the facts share '
                            'consistent fields and a table is readable (for example date, merchant, amount, category). '
                            'Otherwise use concise labeled sections or bullets. Honor explicit format or sort order. '
                            'For a single fact, use a short sentence rather than forcing a table. Do not output raw '
                            'JSON '
                            'or add fields absent from the computed facts.'
                        ),
                    ),
                    ('human', 'User query: {question}\nComputed facts (JSON): {facts_json}'),
                ]
            )
            self._llm_query_reply_chain = query_reply_prompt | extraction_llm.with_structured_output(FinanceQueryReply)

        builder = StateGraph(ChatGraphState)
        builder.add_node('analyze_turn', self._analyze_turn)
        builder.add_node('supervisor', self._supervisor_node)
        builder.add_node('populate_user_context', self._populate_user_context)
        builder.add_node('extract_transaction_candidate', self._extract_transaction_candidate_node)
        builder.add_node('evaluate_transaction_candidate', self._evaluate_transaction_candidate)
        builder.add_node('hitl_clarification', self._hitl_clarification_node)
        builder.add_node('transaction_flow', self._transaction_flow)
        builder.add_node('query_planner', self._query_planner_node)
        builder.add_node('format_previous_result', self._format_previous_result_node)
        builder.add_node('query_orchestrator', self._query_orchestrator_node)
        builder.add_node('query_tool_executor', self._query_tool_node)
        builder.add_node('query_tool_finalize', self._query_tool_finalize)
        builder.add_node('assistant_default', self._assistant_default)
        builder.add_node('assistant_refusal', self._assistant_refusal)

        builder.add_edge(START, 'analyze_turn')
        builder.add_conditional_edges(
            'analyze_turn',
            self._route_after_analysis,
            {
                'populate_user_context': 'populate_user_context',
                'transaction_flow': 'transaction_flow',
                'query_tool_agent': 'query_planner',
                'supervisor': 'supervisor',
                'assistant_default': 'assistant_default',
                'assistant_refusal': 'assistant_refusal',
            },
        )
        builder.add_conditional_edges(
            'supervisor',
            self._route_after_supervisor,
            {
                'populate_user_context': 'populate_user_context',
                'query_tool_agent': 'query_planner',
                'format_previous_result': 'format_previous_result',
                'assistant_default': 'assistant_default',
                'assistant_refusal': 'assistant_refusal',
            },
        )
        builder.add_edge('populate_user_context', 'extract_transaction_candidate')
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
        builder.add_conditional_edges(
            'query_planner',
            self._route_after_query_plan,
            {
                'query_orchestrator': 'query_orchestrator',
                'format_previous_result': 'format_previous_result',
                'assistant_default': 'assistant_default',
            },
        )
        builder.add_edge('format_previous_result', END)
        builder.add_conditional_edges(
            'query_orchestrator',
            tools_condition,
            {
                'tools': 'query_tool_executor',
                '__end__': 'query_tool_finalize',
            },
        )
        builder.add_edge('query_tool_executor', 'query_tool_finalize')
        builder.add_edge('transaction_flow', END)
        builder.add_edge('query_tool_finalize', END)
        builder.add_edge('assistant_default', END)
        builder.add_edge('assistant_refusal', END)

        self._graph = builder.compile(checkpointer=checkpointer)

        category_tool_builder = StateGraph(CategoryToolGraphState)
        category_tool_builder.add_node('category_tool_agent', self._category_tool_agent)
        category_tool_builder.add_node('category_tool_executor', self._category_tool_node)
        category_tool_builder.add_node('category_tool_finalize', self._category_tool_finalize)
        category_tool_builder.add_edge(START, 'category_tool_agent')
        category_tool_builder.add_conditional_edges(
            'category_tool_agent',
            tools_condition,
            {
                'tools': 'category_tool_executor',
                '__end__': 'category_tool_finalize',
            },
        )
        category_tool_builder.add_edge('category_tool_executor', 'category_tool_finalize')
        category_tool_builder.add_edge('category_tool_finalize', END)
        self._category_tool_graph = category_tool_builder.compile()

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
    async def run_turn(
        self,
        *,
        user_id: uuid.UUID,
        thread_id: str,
        message: str,
        timezone: str | None = None,
    ) -> ChatTurnResult:
        checkpoint_thread_id = f'{user_id}:{thread_id}'
        timezone_name = self._validated_timezone_name(timezone)
        config = {
            'configurable': {
                'thread_id': checkpoint_thread_id,
            }
        }

        state_snapshot = await self._graph.aget_state(config=config)
        if state_snapshot.interrupts:
            graph_input: dict[str, Any] | Command = Command(
                resume=message,
                update={
                    'messages': [HumanMessage(content=message)],
                    'transaction_logged': False,
                    'manual_transaction_input_required': False,
                    'insights': None,
                    'agent_correction': None,
                    'runtime_timezone': timezone_name,
                },
            )
        else:
            graph_input = {
                'messages': [HumanMessage(content=message)],
                'runtime_user_id': str(user_id),
                'transaction_logged': False,
                'manual_transaction_input_required': False,
                'insights': None,
                'agent_correction': None,
                'runtime_timezone': timezone_name,
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
        else:
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
            intent=result.get('intent'),
            guardrail_decision=str(result.get('guardrail_decision', GuardrailDecision.ALLOW.value)),
            guardrail_confidence=float(result.get('guardrail_confidence', 1.0)),
            guardrail_layer=str(result.get('guardrail_layer', 'semantic')),
            insights=result.get('insights'),
            agent_correction=result.get('agent_correction'),
        )

    async def _analyze_turn(self, state: ChatGraphState) -> dict[str, Any]:
        latest_user_message = self._latest_user_message(state.get('messages', []))
        if not latest_user_message:
            return {
                'workflow_action': 'default',
                'intent': state.get('intent'),
                'guardrail_decision': state.get('guardrail_decision', GuardrailDecision.ALLOW.value),
                'guardrail_confidence': float(state.get('guardrail_confidence', 1.0)),
                'guardrail_layer': state.get('guardrail_layer', 'semantic'),
            }

        pending_proposal = state.get('pending_proposal')
        if pending_proposal is not None:
            proposal_action = self._proposal_action(latest_user_message)
            if proposal_action is not None:
                return {
                    'workflow_action': proposal_action,
                    'intent': state.get('intent'),
                    'guardrail_decision': state.get('guardrail_decision', GuardrailDecision.ALLOW.value),
                    'guardrail_confidence': float(state.get('guardrail_confidence', 1.0)),
                    'guardrail_layer': state.get('guardrail_layer', 'semantic'),
                }
            return {
                'workflow_action': 'proposal_wait',
                'intent': state.get('intent'),
                'guardrail_decision': state.get('guardrail_decision', GuardrailDecision.ALLOW.value),
                'guardrail_confidence': float(state.get('guardrail_confidence', 1.0)),
                'guardrail_layer': state.get('guardrail_layer', 'semantic'),
            }

        if state.get('hitl_active'):
            proposal_action = self._proposal_action(latest_user_message)
            if proposal_action == 'cancel_proposal':
                return {
                    'workflow_action': 'cancel_hitl',
                    'intent': state.get('intent'),
                    'guardrail_decision': state.get('guardrail_decision', GuardrailDecision.ALLOW.value),
                    'guardrail_confidence': float(state.get('guardrail_confidence', 1.0)),
                    'guardrail_layer': state.get('guardrail_layer', 'semantic'),
                }
            return {
                'workflow_action': 'build_proposal',
                'intent': state.get('intent'),
                'guardrail_decision': state.get('guardrail_decision', GuardrailDecision.ALLOW.value),
                'guardrail_confidence': float(state.get('guardrail_confidence', 1.0)),
                'guardrail_layer': state.get('guardrail_layer', 'semantic'),
            }

        if self._deterministic_transaction_first and self._is_deterministic_transaction_candidate(latest_user_message):
            return {
                'workflow_action': 'build_proposal',
                'intent': DetectedIntent.LOG_TRANSACTION.value,
                'guardrail_decision': GuardrailDecision.ALLOW.value,
                'guardrail_confidence': 1.0,
                'guardrail_layer': 'classifier',
            }

        routing_message = self._conversation_aware_message(state.get('messages', []))
        guardrail_assessment = self._as_guardrail_assessment(
            await self._guardrail_chain.ainvoke({'message': routing_message})
        )
        detected_intent = self._as_detected_intent(await self._intent_chain.ainvoke({'message': routing_message}))
        metadata = {
            'intent': detected_intent.value,
            'guardrail_decision': guardrail_assessment.decision.value,
            'guardrail_confidence': guardrail_assessment.confidence,
            'guardrail_layer': guardrail_assessment.layer,
        }

        if guardrail_assessment.decision == GuardrailDecision.BLOCK:
            if (
                detected_intent == DetectedIntent.LOG_TRANSACTION
                and self._is_deterministic_transaction_candidate(latest_user_message)
            ):
                return {'workflow_action': 'build_proposal', **metadata}
            return {'workflow_action': 'refusal', **metadata}

        if guardrail_assessment.decision == GuardrailDecision.NEEDS_CLASSIFICATION:
            if (
                detected_intent == DetectedIntent.OFF_TOPIC
                and not state.get('last_finance_query_result')
            ):
                return {'workflow_action': 'refusal', **metadata}

        return {'workflow_action': 'supervisor', **metadata}

    @staticmethod
    def _route_after_analysis(state: ChatGraphState) -> str:
        action = state.get('workflow_action')
        if action == 'build_proposal':
            return 'populate_user_context'
        if action in {
            'confirm_proposal',
            'cancel_proposal',
            'edit_proposal',
            'proposal_wait',
            'cancel_hitl',
        }:
            return 'transaction_flow'
        if action == 'query_transactions':
            return 'query_tool_agent'
        if action == 'supervisor':
            return 'supervisor'
        if action == 'refusal':
            return 'assistant_refusal'
        return 'assistant_default'

    async def _supervisor_node(self, state: ChatGraphState) -> dict[str, Any]:
        latest_user_message = self._latest_user_message(state.get('messages', []))
        if not latest_user_message:
            return {'workflow_action': 'default', 'supervisor_workflow': 'respond'}

        detected_intent = self._as_detected_intent(state.get('intent'))
        if getattr(self, '_supervisor_workflow_chain', None) is not None:
            try:
                decision = await self._supervisor_workflow_chain.ainvoke(
                    {
                        'message': latest_user_message,
                        'conversation_context': self._conversation_context(state.get('messages', []))
                        or 'No earlier conversation.',
                        'intent': detected_intent.value,
                        'guardrail_decision': state.get('guardrail_decision', GuardrailDecision.ALLOW.value),
                        'previous_plan': json.dumps(
                            state.get('last_finance_query_plan') or state.get('query_plan'),
                            ensure_ascii=False,
                        ),
                        'previous_result': json.dumps(
                            state.get('last_finance_query_result'),
                            ensure_ascii=False,
                        ),
                    }
                )
                if decision.confidence >= 0.55:
                    return self._supervisor_decision_update(decision, state)
            except Exception:
                logger.exception('Workflow supervisor failed; falling back to safe registered intent routing.')

        return self._supervisor_fallback_update(latest_user_message, detected_intent, state)

    def _supervisor_decision_update(
        self,
        decision: SupervisorDecision,
        state: ChatGraphState,
    ) -> dict[str, Any]:
        has_previous_result = bool(state.get('last_finance_query_result'))
        workflow = decision.workflow
        latest_user_message = self._latest_user_message(state.get('messages', []))
        detected_intent = self._as_detected_intent(state.get('intent'))
        if (
            workflow in {'respond', 'refuse'}
            and state.get('guardrail_decision') != GuardrailDecision.BLOCK.value
            and self._should_route_to_query_transactions(
                latest_user_message=latest_user_message,
                detected_intent=detected_intent,
            )
        ):
            workflow = 'analytics'
        if workflow == 'format_previous' and not has_previous_result:
            workflow = 'analytics' if self._should_route_to_query_transactions(
                latest_user_message=latest_user_message,
                detected_intent=detected_intent,
            ) else 'respond'

        workflow_action = {
            'transaction': 'build_proposal',
            'analytics': 'query_transactions',
            'format_previous': 'query_transactions',
            'respond': 'default',
            'refuse': 'refusal',
        }[workflow]
        return {
            'workflow_action': workflow_action,
            'supervisor_workflow': workflow,
            'supervisor_confidence': decision.confidence,
            'supervisor_rationale': decision.rationale,
            'supervisor_response': decision.response,
        }

    def _supervisor_fallback_update(
        self,
        latest_user_message: str,
        detected_intent: DetectedIntent,
        state: ChatGraphState,
    ) -> dict[str, Any]:
        latest_is_transaction = self._is_deterministic_transaction_candidate(latest_user_message)
        if detected_intent == DetectedIntent.OFF_TOPIC:
            workflow = 'refuse'
        elif (
            state.get('last_finance_query_result')
            and not latest_is_transaction
            and self._is_result_format_followup(' '.join(latest_user_message.lower().split()))
        ):
            workflow = 'format_previous'
        elif state.get('last_finance_query_result') and not latest_is_transaction:
            workflow = 'analytics'
        elif detected_intent == DetectedIntent.LOG_TRANSACTION:
            workflow = 'transaction'
        elif detected_intent == DetectedIntent.QUERY_SPENDING:
            workflow = 'analytics'
        else:
            workflow = 'respond'

        unsupported_responses = {
            DetectedIntent.SPLIT_REQUEST: 'Split workflows are not available in chat yet.',
            DetectedIntent.GENERATE_REPORT: 'Report generation is not available in chat yet.',
            DetectedIntent.ACCOUNT_QUERY: 'Account-balance questions are not available in chat yet.',
            DetectedIntent.MEMORY_RELATED: 'Long-term memory workflows are not available in chat yet.',
        }
        return {
            'workflow_action': {
                'transaction': 'build_proposal',
                'analytics': 'query_transactions',
                'format_previous': 'query_transactions',
                'respond': 'default',
                'refuse': 'refusal',
            }[workflow],
            'supervisor_workflow': workflow,
            'supervisor_confidence': 0.0,
            'supervisor_rationale': 'Registered intent fallback',
            'supervisor_response': unsupported_responses.get(detected_intent),
        }

    @staticmethod
    def _route_after_supervisor(state: ChatGraphState) -> str:
        action = state.get('workflow_action')
        if action == 'build_proposal':
            return 'populate_user_context'
        if action == 'query_transactions':
            return 'query_tool_agent'
        if action == 'refusal':
            return 'assistant_refusal'
        return 'assistant_default'

    async def _populate_user_context(self, state: ChatGraphState) -> dict[str, Any]:
        if state.get('workflow_action') != 'build_proposal':
            return {}

        user_id = self._user_id_from_state(state)
        accounts = await self._list_user_accounts_for_state(user_id)
        categories = await self._list_user_categories_for_state(user_id)
        return {
            'user_accounts': accounts,
            'user_categories': categories,
        }

    async def _extract_transaction_candidate_node(self, state: ChatGraphState) -> dict[str, Any]:
        if state.get('workflow_action') != 'build_proposal':
            return {'extracted_candidate': None}

        latest_user_message = self._latest_user_message(state.get('messages', []))
        if not latest_user_message:
            return {'extracted_candidate': None}

        context_message = state.get('hitl_context_message') if state.get('hitl_active') else None
        extraction_message = self._merge_hitl_context(context_message, latest_user_message)
        candidate = await self._extract_candidate(
            extraction_message,
            accounts=self._normalize_state_accounts(state.get('user_accounts')),
            categories=self._normalize_state_categories(state.get('user_categories')),
        )

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
        user_id = self._user_id_from_state(state)
        user_accounts = self._normalize_state_accounts(state.get('user_accounts'))
        if not user_accounts:
            user_accounts = await self._list_user_accounts_for_state(user_id)
        user_categories = self._normalize_state_categories(state.get('user_categories'))
        if not user_categories:
            user_categories = await self._list_user_categories_for_state(user_id)

        if candidate is None:
            hitl_result = self._next_hitl_step(
                latest_user_message=latest_user_message,
                current_context=hitl_context_message,
                current_hitl_attempt_count=hitl_attempt_count,
                candidate=None,
                available_accounts=user_accounts,
                available_categories=user_categories,
            )
            hitl_result['user_categories'] = user_categories
            hitl_result['user_accounts'] = user_accounts
            return hitl_result

        resolved_account, account_needs_clarification = self._resolve_candidate_account(
            candidate=candidate,
            accounts=user_accounts,
            latest_user_message=latest_user_message,
            hitl_active=bool(state.get('hitl_active', False)),
        )
        if resolved_account is not None:
            candidate['resolved_account_id'] = resolved_account['id']
            candidate['resolved_account_name'] = resolved_account['name']
        if account_needs_clarification:
            hitl_result = self._next_hitl_step(
                latest_user_message=latest_user_message,
                current_context=hitl_context_message,
                current_hitl_attempt_count=hitl_attempt_count,
                candidate=candidate,
                available_accounts=user_accounts,
                available_categories=user_categories,
                forced_missing_fields=['account'],
            )
            hitl_result['user_categories'] = user_categories
            hitl_result['user_accounts'] = user_accounts
            return hitl_result

        resolved_category, suggested_category_name, user_categories = await self._resolve_candidate_category(
            user_id=user_id,
            latest_user_message=latest_user_message,
            candidate=candidate,
            categories=user_categories,
            hitl_active=bool(state.get('hitl_active', False)),
            existing_suggested_category_name=state.get('hitl_suggested_category'),
        )
        if resolved_category is not None:
            candidate['resolved_category_id'] = resolved_category['id']
            candidate['resolved_category_name'] = resolved_category['name']
        if suggested_category_name is not None and not candidate.get('category'):
            candidate['category'] = suggested_category_name

        if not user_accounts:
            return {
                'workflow_action': 'build_proposal_ready',
                'manual_transaction_input_required': False,
                'extracted_candidate': candidate,
                'user_accounts': user_accounts,
                'user_categories': user_categories,
            }

        candidate_transaction_type = self._map_transaction_type(str(candidate.get('type') or ''))
        if self._requires_category(candidate_transaction_type) and resolved_category is None:
            hitl_result = self._next_hitl_step(
                latest_user_message=latest_user_message,
                current_context=hitl_context_message,
                current_hitl_attempt_count=hitl_attempt_count,
                candidate=candidate,
                available_accounts=user_accounts,
                available_categories=user_categories,
                suggested_category_name=suggested_category_name,
                forced_missing_fields=['category'],
            )
            hitl_result['user_categories'] = user_categories
            hitl_result['user_accounts'] = user_accounts
            return hitl_result

        completeness_message = hitl_context_message or latest_user_message
        missing_fields = self._infer_missing_fields(
            completeness_message,
            candidate,
            available_categories=user_categories,
        )
        if missing_fields and missing_fields != ['context']:
            hitl_result = self._next_hitl_step(
                latest_user_message=latest_user_message,
                current_context=hitl_context_message,
                current_hitl_attempt_count=hitl_attempt_count,
                candidate=candidate,
                available_accounts=user_accounts,
                available_categories=user_categories,
                suggested_category_name=suggested_category_name,
                forced_missing_fields=missing_fields,
            )
            hitl_result['user_categories'] = user_categories
            hitl_result['user_accounts'] = user_accounts
            return hitl_result

        candidate_confidence_score = int(candidate.get('confidence_score', 0))
        if candidate_confidence_score < self._proposal_confidence_threshold:
            hitl_result = self._next_hitl_step(
                latest_user_message=latest_user_message,
                current_context=hitl_context_message,
                current_hitl_attempt_count=hitl_attempt_count,
                candidate=candidate,
                available_accounts=user_accounts,
                available_categories=user_categories,
                suggested_category_name=suggested_category_name,
            )
            hitl_result['user_categories'] = user_categories
            hitl_result['user_accounts'] = user_accounts
            return hitl_result

        return {
            'workflow_action': 'build_proposal_ready',
            'manual_transaction_input_required': False,
            'extracted_candidate': candidate,
            'user_accounts': user_accounts,
            'user_categories': user_categories,
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
        question = self._build_hitl_question(
            missing_fields=missing_fields,
            attempt_number=attempt_number,
            category_options=state.get('hitl_category_options', []),
            account_options=state.get('hitl_account_options', []),
            suggested_category_name=state.get('hitl_suggested_category'),
        )

        human_response = interrupt(
            {
                'question': question,
                'attempt': attempt_number,
                'max_turns': self._hitl_max_turns,
                'missing_fields': missing_fields,
                'category_options': state.get('hitl_category_options', []),
                'account_options': state.get('hitl_account_options', []),
                'suggested_category_name': state.get('hitl_suggested_category'),
            }
        )

        if self._proposal_action(str(human_response)) == 'cancel_proposal':
            return {
                'workflow_action': 'cancel_hitl',
                'hitl_active': False,
                'hitl_attempt_count': 0,
                'hitl_context_message': None,
                'hitl_missing_fields': [],
                'hitl_category_options': [],
                'hitl_account_options': [],
                'hitl_suggested_category': None,
                'manual_transaction_input_required': False,
            }

        merged_context = self._merge_hitl_context(state.get('hitl_context_message'), str(human_response))
        return {
            'hitl_context_message': merged_context,
            'workflow_action': 'build_proposal',
            'hitl_category_options': [],
            'hitl_account_options': [],
            'hitl_suggested_category': None,
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

            proposal = await self._build_proposal(
                user_id=self._user_id_from_state(state),
                candidate=candidate,
                user_accounts=self._normalize_state_accounts(state.get('user_accounts')),
                user_categories=self._normalize_state_categories(state.get('user_categories')),
            )
            if isinstance(proposal, str):
                return {
                    'extracted_candidate': None,
                    'hitl_active': False,
                    'hitl_attempt_count': 0,
                    'hitl_context_message': None,
                    'hitl_missing_fields': [],
                    'hitl_category_options': [],
                    'hitl_suggested_category': None,
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
                'hitl_category_options': [],
                'hitl_suggested_category': None,
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
                user_accounts=self._normalize_state_accounts(state.get('user_accounts')),
                user_categories=self._normalize_state_categories(state.get('user_categories')),
            )
            return {
                'pending_proposal': manual_prefill_proposal,
                'extracted_candidate': None,
                'hitl_active': False,
                'hitl_attempt_count': 0,
                'hitl_context_message': None,
                'hitl_missing_fields': [],
                'hitl_category_options': [],
                'hitl_suggested_category': None,
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
                'hitl_category_options': [],
                'hitl_suggested_category': None,
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
                'hitl_category_options': [],
                'hitl_suggested_category': None,
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
                'hitl_category_options': [],
                'hitl_suggested_category': None,
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

            correction_payload: dict[str, Any] | None = None
            if updated != pending_proposal:
                correction_payload = {
                    'original_proposal': dict(pending_proposal),
                    'corrected_proposal': dict(updated),
                    'user_message': latest_user_message,
                }

            return {
                'pending_proposal': updated,
                'extracted_candidate': None,
                'hitl_active': False,
                'hitl_attempt_count': 0,
                'hitl_context_message': None,
                'hitl_missing_fields': [],
                'agent_correction': correction_payload,
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
        available_accounts: list[dict[str, Any]] | None = None,
        available_categories: list[dict[str, Any]] | None = None,
        suggested_category_name: str | None = None,
        forced_missing_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        updated_context = self._merge_hitl_context(current_context, latest_user_message)
        if forced_missing_fields:
            missing_fields = list(forced_missing_fields)
        else:
            missing_fields = self._infer_missing_fields(
                updated_context,
                candidate,
                available_categories=available_categories,
            )

        resolved_suggested_category = self._sanitize_category(suggested_category_name)
        category_options = (
            self._category_options_for_hitl(available_categories or [], candidate)
            if 'category' in missing_fields
            else []
        )
        account_options = (
            [
                str(account.get('name') or '')
                for account in self._normalize_state_accounts(available_accounts or [])
                if account.get('is_active')
            ]
            if 'account' in missing_fields
            else []
        )
        next_attempt_count = current_hitl_attempt_count + 1

        if next_attempt_count > self._hitl_max_turns:
            return {
                'workflow_action': 'manual_fallback',
                'hitl_active': False,
                'hitl_attempt_count': 0,
                'hitl_context_message': updated_context,
                'extracted_candidate': candidate,
                'hitl_missing_fields': missing_fields,
                'hitl_category_options': category_options,
                'hitl_account_options': account_options,
                'hitl_suggested_category': resolved_suggested_category,
                'manual_transaction_input_required': True,
            }

        return {
            'workflow_action': 'hitl_clarification',
            'hitl_active': True,
            'hitl_attempt_count': next_attempt_count,
            'hitl_context_message': updated_context,
            'hitl_missing_fields': missing_fields,
            'hitl_category_options': category_options,
            'hitl_account_options': account_options,
            'hitl_suggested_category': resolved_suggested_category,
            'manual_transaction_input_required': False,
        }

    def _infer_missing_fields(
        self,
        message: str,
        candidate: dict[str, Any] | None,
        *,
        available_categories: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        normalized_message = message.lower()
        detected_type = self._detect_transaction_type(normalized_message)
        transaction_type = (candidate or {}).get('type') or (detected_type.value if detected_type is not None else None)
        amount_paise = (candidate or {}).get('amount_paise') or self._extract_amount_paise(message)

        has_date_hint = self._has_date_hint(normalized_message)
        has_candidate_date = self._has_candidate_date(candidate)

        missing_fields: list[str] = []
        if transaction_type is None:
            missing_fields.append('type')
        if amount_paise is None:
            missing_fields.append('amount')
        if not has_candidate_date and not has_date_hint:
            missing_fields.append('date')

        parsed_transaction_type = self._map_transaction_type(str(transaction_type)) if transaction_type else None
        if self._requires_category(parsed_transaction_type):
            matched_category = self._select_category_by_hint(
                available_categories or [],
                category_type=self._category_type_for_transaction_type(parsed_transaction_type),
                hint_values=[
                    (candidate or {}).get('resolved_category_name'),
                    (candidate or {}).get('category'),
                    (candidate or {}).get('note'),
                    message,
                ],
                allow_default=False,
            )
            if matched_category is None:
                missing_fields.append('category')

        if not missing_fields:
            missing_fields.append('context')

        return missing_fields

    def _build_hitl_question(
        self,
        *,
        missing_fields: list[str],
        attempt_number: int,
        category_options: list[str] | None = None,
        account_options: list[str] | None = None,
        suggested_category_name: str | None = None,
    ) -> str:
        primary_missing = missing_fields[0]
        attempts_label = f'({attempt_number}/{self._hitl_max_turns})'

        if primary_missing == 'type':
            return f"To log this correctly {attempts_label}, is this an expense, income, refund, or transfer?"
        if primary_missing == 'amount':
            return f"I need the exact amount {attempts_label}. How much was it in INR?"
        if primary_missing == 'account':
            options = ', '.join(account_options or [])
            if options:
                return f"Which account should I use {attempts_label}? Choose one of: {options}."
            return f"Which account should I use {attempts_label}? Please provide the account name."
        if primary_missing == 'merchant':
            return f"I can continue once I know the merchant {attempts_label}. Which store/person was this with?"
        if primary_missing == 'date':
            return f"Please confirm when this happened {attempts_label} (today, yesterday, or a date)."
        if primary_missing == 'category':
            options = ', '.join(category_options or [])
            if options and suggested_category_name:
                return (
                    f"I couldn't match the category {attempts_label}. Choose one of: {options}. "
                    f"Or reply `create {suggested_category_name}` to add a new category."
                )
            if options:
                return (
                    f"I couldn't match the category {attempts_label}. "
                    f"Please choose one of: {options}, or say `create <name>`."
                )
            if suggested_category_name:
                return (
                    f"I couldn't match the category {attempts_label}. "
                    f"Reply `create {suggested_category_name}` to create it, or provide an existing category name."
                )
            return (
                f"I still need a category {attempts_label}. "
                'Please provide an existing category name, or reply `create <name>`. '
            )

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

    async def _query_planner_node(self, state: ChatGraphState) -> dict[str, Any]:
        latest_user_message = self._latest_user_message(state.get('messages', []))
        if not latest_user_message:
            return {
                'messages': [AIMessage(content='Please tell me what transaction history you want to see.')],
                'query_tool_call_ids': [],
            }

        timezone_name = self._validated_timezone_name(state.get('runtime_timezone'))
        try:
            local_now = datetime.now(ZoneInfo(timezone_name)).isoformat()
        except (ZoneInfoNotFoundError, ValueError):
            timezone_name = 'UTC'
            local_now = datetime.now(UTC).isoformat()

        plan = await self._create_query_plan(
            latest_user_message,
            timezone_name=timezone_name,
            local_now=local_now,
            conversation_context=self._conversation_context(state.get('messages', [])),
            previous_plan=state.get('last_finance_query_plan') or state.get('query_plan'),
            previous_result=state.get('last_finance_query_result'),
        )
        return {
            'query_plan': plan.model_dump(),
            'runtime_timezone': timezone_name,
        }

    async def _query_orchestrator_node(self, state: ChatGraphState) -> dict[str, Any]:
        latest_user_message = self._latest_user_message(state.get('messages', []))
        plan_data = state.get('query_plan')
        if not latest_user_message or not isinstance(plan_data, dict):
            return {'query_tool_call_ids': []}

        plan = FinanceQueryPlan.model_validate(plan_data)
        if plan.category_scope == 'unspecified' and not plan.category_names:
            return {
                'messages': [
                    AIMessage(content='Which expense categories should I include? Please name the categories.')
                ],
                'query_tool_call_ids': [],
            }
        use_summary_tool = plan.query_kind == 'summary'
        tool_name = 'query_spending_summary' if use_summary_tool else 'query_transactions'
        timezone_name = self._validated_timezone_name(state.get('runtime_timezone'))
        category_names = list(dict.fromkeys(name.strip() for name in plan.category_names if name.strip()))
        categories: list[str | None] = category_names or [None]
        tool_calls = []
        tool_call_ids: list[str] = []
        for category_name in categories:
            tool_call_id = f'query-tool-{uuid.uuid4().hex}'
            tool_call_ids.append(tool_call_id)
            tool_args: dict[str, Any] = {
                'message': latest_user_message,
                'date_period': plan.date_period,
                'period_count': plan.period_count,
                'timezone_name': timezone_name,
                'category_hint': category_name,
            }
            if not use_summary_tool:
                tool_args['limit'] = 10
                tool_args['transaction_type'] = plan.transaction_type
            tool_calls.append({'name': tool_name, 'args': tool_args, 'id': tool_call_id, 'type': 'tool_call'})

        return {
            'messages': [AIMessage(content='', tool_calls=tool_calls)],
            'query_tool_call_ids': tool_call_ids,
        }

    async def _create_query_plan(
        self,
        message: str,
        *,
        timezone_name: str,
        local_now: str,
        conversation_context: str = '',
        previous_plan: dict[str, Any] | None = None,
        previous_result: dict[str, Any] | None = None,
    ) -> FinanceQueryPlan:
        if self._llm_query_plan_chain is not None:
            try:
                plan = await self._llm_query_plan_chain.ainvoke(
                    {
                        'message': message,
                        'timezone': timezone_name,
                        'local_now': local_now,
                        'conversation_context': conversation_context or 'No earlier conversation.',
                        'previous_query_plan': json.dumps(previous_plan, ensure_ascii=False)
                        if previous_plan
                        else 'None',
                        'previous_query_result': json.dumps(previous_result, ensure_ascii=False)
                        if previous_result
                        else 'None',
                    }
                )
                if plan.confidence >= 0.55:
                    if plan.action == 'drill_down' and previous_plan:
                        return self._inherit_previous_query_scope(plan, previous_plan)
                    return plan
            except Exception:
                logger.exception('Finance query planning failed; falling back to basic query interpretation.')
        return self._fallback_query_plan(
            message,
            previous_plan=previous_plan,
            previous_result=previous_result,
        )

    @staticmethod
    def _fallback_query_plan(
        message: str,
        *,
        previous_plan: dict[str, Any] | None = None,
        previous_result: dict[str, Any] | None = None,
    ) -> FinanceQueryPlan:
        normalized = ' '.join(message.lower().split())
        if LangGraphChatOrchestrator._is_transaction_drilldown_followup(normalized) and previous_plan:
            try:
                previous = FinanceQueryPlan.model_validate(previous_plan)
                return LangGraphChatOrchestrator._inherit_previous_query_scope(
                    previous.model_copy(update={'confidence': 0.5}), previous_plan
                )
            except (TypeError, ValueError):
                logger.warning('Previous finance query plan was invalid; falling back to standalone interpretation.')

        if previous_result and LangGraphChatOrchestrator._is_result_format_followup(normalized):
            previous = previous_plan or {}
            return FinanceQueryPlan(
                action='format_previous',
                query_kind='transaction_list',
                date_period=previous.get('date_period', 'recent_default'),
                period_count=previous.get('period_count'),
                category_names=previous.get('category_names', []),
                category_scope=previous.get('category_scope', 'all'),
                transaction_type=previous.get('transaction_type', 'all'),
                result_format='table' if 'table' in normalized else 'list',
                sort_order='oldest_first'
                if any(term in normalized for term in ('oldest first', 'oldest to newest', 'ascending'))
                else 'newest_first',
                confidence=0.5,
            )

        summary_cues = ('how much', 'total', 'spent', 'spend', 'spending', 'summary')
        query_kind: Literal['summary', 'transaction_list'] = (
            'summary' if any(cue in normalized for cue in summary_cues) else 'transaction_list'
        )

        period_count: int | None = None
        if 'yesterday' in normalized:
            date_period = 'yesterday'
        elif 'today' in normalized:
            date_period = 'today'
        elif 'last week' in normalized:
            date_period = 'last_week'
        elif 'this week' in normalized or 'this weeks' in normalized:
            date_period = 'this_week'
        elif 'last month' in normalized:
            date_period = 'last_month'
        elif 'this month' in normalized or 'this months' in normalized:
            date_period = 'this_month'
        else:
            weeks_match = re.search(r'\b(\d{1,2})\s+weeks?\b', normalized)
            days_match = re.search(r'\b(\d{1,3})\s+days?\b', normalized)
            if weeks_match:
                date_period = 'last_n_weeks'
                period_count = int(weeks_match.group(1))
            elif days_match:
                date_period = 'last_n_days'
                period_count = int(days_match.group(1))
            else:
                date_period = 'recent_default'
        category_match = re.search(
            r'\b(?:on|in|for|under|of)\s+([a-z][a-z0-9 &,\-]{1,80}?)'
            r'(?=\s+(?:this|last|today|yesterday|over|during)\b|[?!.]|$)',
            normalized,
        )
        category_names = (
            [
                part.strip()
                for part in re.split(r'\s*(?:,|&|\band\b)\s*', category_match.group(1))
                if part.strip()
            ]
            if category_match
            else []
        )
        return FinanceQueryPlan(
            query_kind=query_kind,
            date_period=date_period,
            period_count=period_count,
            category_names=category_names[:5],
            category_scope=(
                'selected'
                if category_names
                else 'unspecified'
                if re.search(r'\b(?:category|categories)\b', normalized)
                else 'all'
            ),
            confidence=0.5,
        )

    @staticmethod
    def _route_after_query_plan(state: ChatGraphState) -> str:
        plan = state.get('query_plan')
        if not isinstance(plan, dict):
            return 'assistant_default'
        if plan.get('action') == 'format_previous':
            return 'format_previous_result'
        if plan.get('action') in {'query', 'drill_down'}:
            return 'query_orchestrator'
        return 'assistant_default'

    async def _format_previous_result_node(self, state: ChatGraphState) -> dict[str, Any]:
        plan_data = state.get('query_plan') or {}
        result = state.get('last_finance_query_result') or {}
        transactions = result.get('transactions')
        if not isinstance(transactions, list) or not transactions:
            return {
                'messages': [AIMessage(content='There are no transaction rows in the previous result to format.')],
            }

        sorted_transactions = sorted(
            (item for item in transactions if isinstance(item, dict)),
            key=lambda item: str(item.get('occurred_at') or item.get('date') or ''),
            reverse=plan_data.get('sort_order', 'newest_first') != 'oldest_first',
        )
        if plan_data.get('result_format', 'list') == 'table':
            lines = [
                '| Date | Merchant | Amount | Category |',
                '| --- | --- | ---: | --- |',
            ]
            for item in sorted_transactions:
                cells = (item.get('date'), item.get('merchant'), item.get('amount'), item.get('category'))
                lines.append('| ' + ' | '.join(self._markdown_table_cell(value) for value in cells) + ' |')
            content = '\n'.join(lines)
        else:
            content = '\n'.join(
                f"{item.get('date')}: {item.get('merchant')} — {item.get('amount')} ({item.get('category')})"
                for item in sorted_transactions
            )

        return {'messages': [AIMessage(content=content)]}

    @staticmethod
    def _markdown_table_cell(value: Any) -> str:
        normalized = str(value if value is not None else '—').strip()
        return normalized.replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ')

    @staticmethod
    def _is_result_format_followup(message: str) -> bool:
        return any(
            term in message
            for term in (
                'table',
                'sort these',
                'sort them',
                'sort by date',
                'format these',
                'format them',
                'show these',
                'show them',
            )
        )

    @staticmethod
    def _inherit_previous_query_scope(
        plan: FinanceQueryPlan,
        previous_plan_data: dict[str, Any],
    ) -> FinanceQueryPlan:
        previous = FinanceQueryPlan.model_validate(previous_plan_data)
        return plan.model_copy(
            update={
                'action': 'drill_down',
                'query_kind': 'transaction_list',
                'date_period': previous.date_period,
                'period_count': previous.period_count,
                'category_names': previous.category_names,
                'category_scope': previous.category_scope,
                'transaction_type': 'expense'
                if previous.query_kind == 'summary'
                else plan.transaction_type,
            }
        )

    @staticmethod
    def _is_transaction_drilldown_followup(message: str) -> bool:
        normalized = ' '.join(message.lower().split()).strip('?.!, ')
        return normalized in {'where', 'where exactly', 'show me where'} or bool(
            re.search(r'\b(where did i spend|where was (?:it|that|this)|show me where i spent)\b', normalized)
        )

    @staticmethod
    def _conversation_context(messages: list[BaseMessage], *, limit: int = 6) -> str:
        relevant_messages = [
            message
            for message in messages
            if isinstance(message, (HumanMessage, AIMessage))
            and isinstance(message.content, str)
            and message.content.strip()
            and not (isinstance(message, AIMessage) and message.tool_calls)
        ]
        if len(relevant_messages) < 2:
            return ''
        prior_messages = relevant_messages[-(limit + 1) : -1]
        return '\n'.join(
            f"{'User' if isinstance(message, HumanMessage) else 'Assistant'}: {message.content.strip()}"
            for message in prior_messages
        )

    @classmethod
    def _conversation_aware_message(cls, messages: list[BaseMessage]) -> str:
        latest_user_message = cls._latest_user_message(messages)
        context = cls._conversation_context(messages)
        if not context:
            return latest_user_message
        return f'Recent conversation (context only):\n{context}\nCurrent user message: {latest_user_message}'

    async def _query_tool_finalize(self, state: ChatGraphState) -> dict[str, Any]:
        tool_call_ids = state.get('query_tool_call_ids', [])
        if not tool_call_ids:
            return {'query_tool_call_ids': []}

        tool_messages = {
            str(message.tool_call_id): message
            for message in state.get('messages', [])
            if isinstance(message, ToolMessage) and str(message.tool_call_id) in tool_call_ids
        }
        if len(tool_messages) != len(tool_call_ids):
            return {'query_tool_call_ids': []}

        payloads = [self._parse_tool_payload(tool_messages[call_id].content) for call_id in tool_call_ids]
        failed_categories = [
            str(payload.get('category_hint') or '')
            for payload in payloads
            if payload.get('error') in {'category_ambiguous', 'category_not_found'}
        ]
        if failed_categories:
            failed_label = ', '.join(name for name in failed_categories if name) or 'the requested category'
            reply = f"I couldn't resolve {failed_label} to a unique expense category. Please clarify the category name."
            return {
                'messages': [AIMessage(content=reply)],
                'query_tool_call_ids': [],
                'last_finance_query_result': None,
                'insights': None,
            }

        facts_list = [payload.get('facts') for payload in payloads]
        facts = self._combine_query_facts(facts_list)
        reply = self._deterministic_combined_query_reply(facts)
        insights = self._normalize_insights_payload(payloads[0].get('insights')) if len(payloads) == 1 else None
        if isinstance(facts, dict) and self._llm_query_reply_chain is not None:
            try:
                generated_reply = await self._llm_query_reply_chain.ainvoke(
                    {
                        'question': self._latest_user_message(state.get('messages', [])),
                        'facts_json': json.dumps(facts, ensure_ascii=False),
                    }
                )
                candidate_reply = str(generated_reply.reply).strip()
                if candidate_reply and self._query_reply_preserves_facts(candidate_reply, facts):
                    reply = candidate_reply
                    insights = None
                elif candidate_reply:
                    logger.warning(
                        'Generated finance-query reply omitted required computed facts; using deterministic answer.'
                    )
            except Exception:
                logger.exception('Finance query response generation failed; using deterministic answer.')
        return {
            'messages': [AIMessage(content=reply)],
            'query_tool_call_ids': [],
            'last_finance_query_plan': state.get('query_plan'),
            'last_finance_query_result': facts if isinstance(facts, dict) else None,
            'insights': insights,
        }

    @staticmethod
    def _combine_query_facts(raw_facts: list[Any]) -> dict[str, Any] | None:
        facts_list = [facts for facts in raw_facts if isinstance(facts, dict)]
        if not facts_list or len(facts_list) != len(raw_facts):
            return None
        query_kind = facts_list[0].get('query_kind')
        if any(facts.get('query_kind') != query_kind for facts in facts_list):
            return None
        if len(facts_list) == 1:
            return facts_list[0]

        if query_kind == 'spending_summary':
            total_spent_paise = sum(int(facts.get('total_spent_paise') or 0) for facts in facts_list)
            transaction_count = sum(int(facts.get('transaction_count') or 0) for facts in facts_list)
            categories = [
                {
                    'name': str(facts.get('category') or 'Uncategorized'),
                    'total_spent_paise': int(facts.get('total_spent_paise') or 0),
                    'total_spent_display': str(facts.get('total_spent_display') or 'INR 0.00'),
                    'transaction_count': int(facts.get('transaction_count') or 0),
                }
                for facts in facts_list
            ]
            return {
                'query_kind': query_kind,
                'category': None,
                'categories': categories,
                'date_from': facts_list[0].get('date_from'),
                'date_to': facts_list[0].get('date_to'),
                'total_spent_paise': total_spent_paise,
                'total_spent_display': f'INR {total_spent_paise / 100:,.2f}',
                'transaction_count': transaction_count,
            }

        if query_kind == 'transaction_list':
            transactions_by_id: dict[str, dict[str, Any]] = {}
            for facts in facts_list:
                for transaction in facts.get('transactions', []):
                    if isinstance(transaction, dict):
                        transaction_id = str(
                            transaction.get('id')
                            or '|'.join(
                                str(transaction.get(key) or '')
                                for key in ('occurred_at', 'date', 'amount', 'merchant', 'category')
                            )
                        )
                        transactions_by_id[transaction_id] = transaction
            transactions = sorted(
                transactions_by_id.values(),
                key=lambda transaction: str(transaction.get('occurred_at') or transaction.get('date') or ''),
                reverse=True,
            )[:10]
            return {
                'query_kind': query_kind,
                'category': None,
                'date_from': facts_list[0].get('date_from'),
                'date_to': facts_list[0].get('date_to'),
                'transaction_count': sum(int(facts.get('transaction_count') or 0) for facts in facts_list),
                'transactions': transactions,
            }

        return None

    @staticmethod
    def _deterministic_combined_query_reply(facts: dict[str, Any] | None) -> str:
        if not facts:
            return 'I could not verify the requested finance-query results. Please try a more specific query.'
        if facts.get('query_kind') == 'spending_summary':
            categories = facts.get('categories')
            if isinstance(categories, list):
                category_totals = '; '.join(
                    f"{item['name']}: {item['total_spent_display']} ({item['transaction_count']} transactions)"
                    for item in categories
                )
                return (
                    f"From {facts.get('date_from')} to {facts.get('date_to')}, the selected categories "
                    f"total {facts.get('total_spent_display')} across {facts.get('transaction_count')} transactions. "
                    f'{category_totals}.'
                )
            return (
                f"From {facts.get('date_from')} to {facts.get('date_to')}, spending was "
                f"{facts.get('total_spent_display')} across {facts.get('transaction_count')} transactions."
            )
        if facts.get('query_kind') == 'transaction_list':
            transactions = facts.get('transactions')
            if isinstance(transactions, list) and transactions:
                transaction_lines = [
                    f"{item.get('date')}: {item.get('merchant')} — {item.get('amount')} "
                    f"({item.get('category')})"
                    for item in transactions
                ]
                return (
                    f"I found {facts.get('transaction_count')} matching transactions:\n"
                    + '\n'.join(f'• {line}' for line in transaction_lines)
                )
            return 'No matching transactions found for that time range.'
        return 'I could not verify the requested finance-query results. Please try a more specific query.'

    @staticmethod
    def _query_reply_preserves_facts(reply: str, facts: dict[str, Any]) -> bool:
        normalized_reply = ' '.join(reply.lower().split())
        query_kind = facts.get('query_kind')
        category = str(facts.get('category') or '').strip()
        if category and category.lower() not in normalized_reply:
            return False

        if query_kind == 'spending_summary':
            total = str(facts.get('total_spent_display') or '').strip()
            transaction_count = int(facts.get('transaction_count') or 0)
            if not (
                total
                and total.lower() in normalized_reply
                and re.search(rf'(?<!\d){transaction_count}(?!\d)', normalized_reply)
                and re.search(r'\btransactions?\b', normalized_reply)
            ):
                return False
            categories = facts.get('categories')
            if not isinstance(categories, list):
                return True
            return all(
                str(category.get('name') or '').lower() in normalized_reply
                and str(category.get('total_spent_display') or '').lower() in normalized_reply
                for category in categories
            )

        if query_kind == 'transaction_list':
            transaction_count = int(facts.get('transaction_count') or 0)
            if not re.search(rf'(?<!\d){transaction_count}(?!\d)', normalized_reply) or not re.search(
                r'\btransactions?\b', normalized_reply
            ):
                return False
            transactions = facts.get('transactions')
            if not isinstance(transactions, list) or not transactions:
                return True
            latest = transactions[0]
            if not isinstance(latest, dict):
                return False
            latest_amount = str(latest.get('amount') or '').strip()
            latest_date = str(latest.get('date') or '').strip()
            latest_merchant = str(latest.get('merchant') or '').strip()
            required_fields = (latest_amount, latest_date, latest_merchant)
            if not all(value and value.lower() in normalized_reply for value in required_fields):
                return False
            return all(
                isinstance(transaction, dict)
                and all(
                    str(transaction.get(field) or '').strip().lower() in normalized_reply
                    for field in ('date', 'amount', 'merchant')
                )
                for transaction in transactions
            )

        return False

    @staticmethod
    def _normalize_insights_payload(raw_insights: Any) -> list[dict[str, str]] | None:
        if not isinstance(raw_insights, list):
            return None

        insights: list[dict[str, str]] = []
        for raw_item in raw_insights:
            if not isinstance(raw_item, dict):
                continue
            title = str(raw_item.get('title') or '').strip()
            detail = str(raw_item.get('detail') or '').strip()
            if not title or not detail:
                continue
            insights.append({'title': title, 'detail': detail})

        return insights or None

    @staticmethod
    def _latest_tool_message(
        messages: list[BaseMessage],
        *,
        tool_call_id: str | None = None,
    ) -> ToolMessage | None:
        for message in reversed(messages):
            if not isinstance(message, ToolMessage):
                continue
            if tool_call_id is None or str(message.tool_call_id) == tool_call_id:
                return message
        return None

    @staticmethod
    def _parse_tool_payload(raw_content: Any) -> dict[str, Any]:
        if isinstance(raw_content, dict):
            return raw_content

        if isinstance(raw_content, str):
            try:
                parsed = json.loads(raw_content)
            except json.JSONDecodeError:
                return {'reply': raw_content}
            return parsed if isinstance(parsed, dict) else {'reply': raw_content}

        return {}

    async def _assistant_default(self, state: ChatGraphState) -> dict[str, list[AIMessage]]:
        supervisor_response = str(state.get('supervisor_response') or '').strip()
        if supervisor_response:
            return {'messages': [AIMessage(content=supervisor_response)]}

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

    async def _build_proposal(
        self,
        *,
        user_id: uuid.UUID,
        candidate: dict[str, Any],
        user_accounts: list[dict[str, Any]] | None = None,
        user_categories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | str:
        if candidate['type'] == TransactionType.TRANSFER.value:
            return 'Transfer extraction is detected, but transfer proposal flow is not enabled yet.'

        accounts = self._normalize_state_accounts(user_accounts)
        if not accounts:
            accounts = await self._list_user_accounts_for_state(user_id)
        if not accounts:
            return 'I can log this transaction, but please create an account first.'

        resolved_account_id = str(candidate.get('resolved_account_id') or '').strip()
        account = next(
            (
                item
                for item in accounts
                if item['id'] == resolved_account_id and item['is_active']
            ),
            None,
        ) if resolved_account_id else None
        if account is None:
            account = next((item for item in accounts if item['is_active'] and item['is_default']), None)
        if account is None:
            active_accounts = [item for item in accounts if item['is_active']]
            if len(active_accounts) == 1:
                account = active_accounts[0]
            elif active_accounts:
                return 'Please choose a default account or specify which account to use.'
        if account is None:
            return 'I can log this transaction, but please create an active account first.'

        category_type = (
            CategoryType.EXPENSE if candidate['type'] == TransactionType.EXPENSE.value else CategoryType.INCOME
        )
        categories = self._normalize_state_categories(user_categories)
        if not categories:
            categories = await self._list_user_categories_for_state(user_id)

        category = None
        resolved_category_id = str(candidate.get('resolved_category_id') or '').strip()
        if resolved_category_id:
            category = next(
                (
                    item
                    for item in categories
                    if item['id'] == resolved_category_id and item['type'] == category_type.value
                ),
                None,
            )

        if category is None:
            category = self._select_category_by_hint(
            categories,
            category_type=category_type,
                hint_values=[candidate.get('resolved_category_name'), candidate.get('category'), candidate.get('note')],
                allow_default=False,
            )

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
            'account_id': account['id'],
            'account_name': account['name'],
            'category_id': category['id'],
            'category_name': category['name'],
        }

    async def _build_manual_prefill_proposal(
        self,
        *,
        user_id: uuid.UUID,
        candidate: dict[str, Any] | None,
        context_message: str | None,
        user_accounts: list[dict[str, Any]] | None = None,
        user_categories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        normalized_candidate = candidate or {}

        accounts = self._normalize_state_accounts(user_accounts)
        if not accounts:
            accounts = await self._list_user_accounts_for_state(user_id)
        account_id = str(normalized_candidate.get('resolved_account_id') or '').strip()
        account = next(
            (item for item in accounts if item['id'] == account_id and item['is_active']),
            None,
        ) if account_id else None
        if account is None:
            account = next((item for item in accounts if item['is_active'] and item['is_default']), None)
        if account is None:
            active_accounts = [item for item in accounts if item['is_active']]
            account = active_accounts[0] if len(active_accounts) == 1 else None

        raw_type = str(normalized_candidate.get('type') or '').strip().lower()
        parsed_type = self._map_transaction_type(raw_type)
        transaction_type = parsed_type or TransactionType.EXPENSE

        categories = self._normalize_state_categories(user_categories)
        if not categories:
            categories = await self._list_user_categories_for_state(user_id)
        if transaction_type == TransactionType.EXPENSE:
            desired_category_type = CategoryType.EXPENSE
        elif transaction_type in {TransactionType.INCOME, TransactionType.REFUND}:
            desired_category_type = CategoryType.INCOME
        else:
            desired_category_type = None

        category = self._select_category_by_hint(
            categories,
            category_type=desired_category_type,
            hint_values=[
                normalized_candidate.get('resolved_category_name'),
                normalized_candidate.get('category'),
                normalized_candidate.get('note'),
                context_message,
            ],
            allow_default=False,
        )

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
            'account_id': account['id'] if account else '',
            'account_name': account['name'] if account else 'Select account',
            'category_id': category['id'] if category else '',
            'category_name': category['name'] if category else 'Select category',
            'confidence_score': max(0, min(100, confidence_score)),
        }

    async def _extract_candidate(
        self,
        message: str,
        *,
        accounts: list[dict[str, Any]] | None = None,
        categories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        llm_candidate = await self._extract_candidate_with_llm(message, accounts=accounts, categories=categories)
        if llm_candidate is not None:
            return llm_candidate
        return self._extract_candidate_rule_based(message)

    async def _extract_candidate_with_llm(
        self,
        message: str,
        *,
        accounts: list[dict[str, Any]] | None = None,
        categories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        if self._llm_extraction_chain is None:
            return None

        try:
            extracted = await self._llm_extraction_chain.ainvoke(
                {
                    'message': message,
                    'today_utc': datetime.now(UTC).isoformat(),
                    'accounts_catalog': self._build_accounts_catalog_for_prompt(accounts or []),
                    'categories_catalog': self._build_categories_catalog_for_prompt(categories or []),
                }
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
            'selected_account': self._sanitize_category(extracted.selected_account),
            'account_hint': self._sanitize_category(extracted.account_hint),
            'selected_category': self._sanitize_category(extracted.selected_category),
            'category': self._sanitize_category(extracted.category),
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
        relative_days_match = re.search(r'\b(\d{1,3})\s+days?\s+ago\b', normalized)
        relative_weeks_match = re.search(r'\b(\d{1,3})\s+weeks?\s+ago\b', normalized)
        relative_months_match = re.search(r'\b(\d{1,3})\s+months?\s+ago\b', normalized)

        if relative_days_match:
            occurred_at -= timedelta(days=int(relative_days_match.group(1)))
            has_date_hint = True
        elif relative_weeks_match:
            occurred_at -= timedelta(weeks=int(relative_weeks_match.group(1)))
            has_date_hint = True
        elif relative_months_match:
            # Approximate month offsets with 30-day windows in fallback parsing.
            occurred_at -= timedelta(days=30 * int(relative_months_match.group(1)))
            has_date_hint = True
        elif 'yesterday' in normalized:
            occurred_at -= timedelta(days=1)
            has_date_hint = True
        elif 'today' in normalized:
            has_date_hint = True
        elif 'last week' in normalized:
            occurred_at -= timedelta(weeks=1)
            has_date_hint = True
        elif 'last month' in normalized:
            occurred_at -= timedelta(days=30)
            has_date_hint = True

        category = self._extract_category_hint(message)
        merchant = self._extract_merchant(message)

        return {
            'type': transaction_type.value,
            'amount_paise': amount_paise,
            'occurred_at': occurred_at.isoformat(),
            'selected_account': None,
            'account_hint': None,
            'category': category,
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
    def _sanitize_category(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = ' '.join(value.strip().split()).strip(' .,!?;:')
        if not cleaned:
            return None
        return cleaned[:100]

    @staticmethod
    def _extract_category_hint(message: str) -> str | None:
        category_match = re.search(r"\b(?:category|under)\s+([A-Za-z][A-Za-z0-9 &'\-.]{1,80})", message, re.IGNORECASE)
        if not category_match:
            return None
        return LangGraphChatOrchestrator._sanitize_category(category_match.group(1))

    @staticmethod
    def _normalize_lookup_text(value: str) -> str:
        return ' '.join(re.sub(r'[^a-z0-9]+', ' ', value.lower()).split())

    @classmethod
    def _select_category_by_hint(
        cls,
        categories: list[dict[str, Any]],
        *,
        category_type: CategoryType | None,
        hint_values: list[str | None],
        allow_default: bool,
    ) -> dict[str, Any] | None:
        if category_type is None:
            scoped_categories = list(categories)
        else:
            scoped_categories = [item for item in categories if item.get('type') == category_type.value]

        if not scoped_categories:
            return None

        for raw_hint in hint_values:
            sanitized_hint = cls._sanitize_category(raw_hint)
            if sanitized_hint is None:
                continue

            normalized_hint = cls._normalize_lookup_text(sanitized_hint)
            if not normalized_hint:
                continue

            padded_hint = f' {normalized_hint} '
            for category in scoped_categories:
                normalized_name = cls._normalize_lookup_text(str(category.get('name') or ''))
                if not normalized_name:
                    continue
                if normalized_hint == normalized_name:
                    return category
                if f' {normalized_name} ' in padded_hint:
                    return category

        return scoped_categories[0] if allow_default else None

    @staticmethod
    def _normalize_state_accounts(raw_accounts: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_accounts, list):
            return []

        normalized_accounts: list[dict[str, Any]] = []
        for raw_account in raw_accounts:
            if not isinstance(raw_account, dict):
                continue

            account_id = str(raw_account.get('id') or '').strip()
            account_name = str(raw_account.get('name') or '').strip()
            if not account_id or not account_name:
                continue

            normalized_accounts.append(
                {
                    'id': account_id,
                    'name': account_name,
                    'type': str(raw_account.get('type') or '').strip().lower(),
                    'is_active': bool(raw_account.get('is_active', False)),
                    'is_default': bool(raw_account.get('is_default', False)),
                }
            )

        return normalized_accounts

    @staticmethod
    def _normalize_state_categories(raw_categories: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_categories, list):
            return []

        normalized_categories: list[dict[str, Any]] = []
        for raw_category in raw_categories:
            if not isinstance(raw_category, dict):
                continue

            category_id = str(raw_category.get('id') or '').strip()
            category_name = str(raw_category.get('name') or '').strip()
            category_type = str(raw_category.get('type') or '').strip().lower()
            if not category_id or not category_name:
                continue
            if category_type not in {CategoryType.EXPENSE.value, CategoryType.INCOME.value}:
                continue

            normalized_categories.append(
                {
                    'id': category_id,
                    'name': category_name,
                    'type': category_type,
                }
            )

        return normalized_categories

    async def _list_user_accounts_for_state(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        accounts = await self._account_repository.list_for_user(user_id)
        return [
            {
                'id': str(account.id),
                'name': account.name,
                'type': account.type.value,
                'is_active': bool(account.is_active),
                'is_default': bool(account.is_default),
            }
            for account in accounts
        ]

    async def _list_user_categories_for_state(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        categories = await self._category_repository.list_for_user(user_id)
        return [
            {
                'id': str(category.id),
                'name': category.name,
                'type': category.type.value,
            }
            for category in categories
        ]

    @classmethod
    def _build_accounts_catalog_for_prompt(cls, accounts: list[dict[str, Any]]) -> str:
        catalog = [
            {
                'name': str(account.get('name') or '').strip(),
                'type': str(account.get('type') or '').strip().lower(),
                'is_active': bool(account.get('is_active', False)),
                'is_default': bool(account.get('is_default', False)),
            }
            for account in cls._normalize_state_accounts(accounts)
            if bool(account.get('is_active', False))
        ]
        return json.dumps(catalog, ensure_ascii=False)

    @classmethod
    def _resolve_candidate_account(
        cls,
        *,
        candidate: dict[str, Any],
        accounts: list[dict[str, Any]],
        latest_user_message: str,
        hitl_active: bool,
    ) -> tuple[dict[str, Any] | None, bool]:
        active_accounts = [account for account in accounts if account.get('is_active')]
        selected_name = cls._sanitize_category(candidate.get('selected_account'))
        hint = cls._sanitize_category(candidate.get('account_hint'))

        if hitl_active and selected_name and not cls._account_name_mentioned(selected_name, latest_user_message):
            selected_name = None
        if hitl_active and hint and not cls._account_name_mentioned(hint, latest_user_message):
            hint = None

        requested_name = hint or selected_name
        if requested_name:
            normalized_request = cls._normalize_lookup_text(requested_name)
            exact_matches = [
                account
                for account in active_accounts
                if cls._normalize_lookup_text(str(account.get('name') or '')) == normalized_request
            ]
            if len(exact_matches) == 1:
                return exact_matches[0], False
            if len(exact_matches) > 1:
                return None, True

            partial_matches = [
                account
                for account in active_accounts
                if normalized_request
                and normalized_request in cls._normalize_lookup_text(str(account.get('name') or ''))
            ]
            if len(partial_matches) == 1:
                return partial_matches[0], False
            return None, True

        default_accounts = [account for account in active_accounts if account.get('is_default')]
        if len(default_accounts) == 1:
            return default_accounts[0], False
        if len(active_accounts) == 1:
            return active_accounts[0], False
        return None, bool(active_accounts)

    @classmethod
    def _account_name_mentioned(cls, account_name: str, message: str) -> bool:
        normalized_name = cls._normalize_lookup_text(account_name)
        normalized_message = cls._normalize_lookup_text(message)
        return bool(normalized_name and f' {normalized_name} ' in f' {normalized_message} ')

    @classmethod
    def _build_categories_catalog_for_prompt(cls, categories: list[dict[str, Any]]) -> str:
        if not categories:
            return '[]'

        catalog: list[dict[str, Any]] = []
        for category in categories:
            category_name = str(category.get('name') or '').strip()
            category_type = str(category.get('type') or '').strip().lower()
            if not category_name:
                continue

            normalized_name = cls._normalize_lookup_text(category_name)
            alias_tokens = [token for token in normalized_name.split(' ') if token]
            aliases = [normalized_name, *alias_tokens]
            unique_aliases = list(dict.fromkeys(alias for alias in aliases if alias))

            usage_hint = (
                f"Use this for {category_name} related {category_type} transactions."
                if category_type
                else f'Use this for {category_name} related transactions.'
            )

            catalog.append(
                {
                    'name': category_name,
                    'type': category_type,
                    'when_to_use': usage_hint,
                    'aliases': unique_aliases,
                }
            )

        return json.dumps(catalog, ensure_ascii=False)

    @staticmethod
    def _category_type_for_transaction_type(transaction_type: TransactionType | None) -> CategoryType | None:
        if transaction_type == TransactionType.EXPENSE:
            return CategoryType.EXPENSE
        if transaction_type in {TransactionType.INCOME, TransactionType.REFUND}:
            return CategoryType.INCOME
        return None

    @classmethod
    def _requires_category(cls, transaction_type: TransactionType | None) -> bool:
        return cls._category_type_for_transaction_type(transaction_type) is not None

    @classmethod
    def _category_options_for_hitl(
        cls,
        categories: list[dict[str, Any]],
        candidate: dict[str, Any] | None,
    ) -> list[str]:
        normalized_categories = cls._normalize_state_categories(categories)
        transaction_type = cls._map_transaction_type(str((candidate or {}).get('type') or ''))
        desired_category_type = cls._category_type_for_transaction_type(transaction_type)
        scoped_categories = (
            [item for item in normalized_categories if item['type'] == desired_category_type.value]
            if desired_category_type is not None
            else normalized_categories
        )
        return [item['name'] for item in scoped_categories]

    async def _resolve_candidate_category(
        self,
        *,
        user_id: uuid.UUID,
        latest_user_message: str,
        candidate: dict[str, Any],
        categories: list[dict[str, Any]],
        hitl_active: bool = False,
        existing_suggested_category_name: str | None = None,
    ) -> tuple[dict[str, Any] | None, str | None, list[dict[str, Any]]]:
        normalized_categories = self._normalize_state_categories(categories)
        candidate_transaction_type = self._map_transaction_type(str(candidate.get('type') or ''))
        category_type = self._category_type_for_transaction_type(candidate_transaction_type)
        if category_type is None:
            return None, None, normalized_categories

        selected_category_hint = self._sanitize_category(candidate.get('selected_category'))
        selected_category_was_answered_now = (
            not hitl_active
            or (
                selected_category_hint is not None
                and self._category_name_mentioned_in_message(selected_category_hint, latest_user_message)
            )
        )
        if selected_category_hint is not None and selected_category_was_answered_now:
            selected_category = next(
                (
                    item
                    for item in normalized_categories
                    if item.get('type') == category_type.value
                    and self._normalize_lookup_text(str(item.get('name') or ''))
                    == self._normalize_lookup_text(selected_category_hint)
                ),
                None,
            )
            if selected_category is not None:
                return selected_category, selected_category_hint, normalized_categories

        category_hint = self._sanitize_category(candidate.get('category'))
        if (
            hitl_active
            and category_hint is not None
            and not self._category_name_mentioned_in_message(category_hint, latest_user_message)
        ):
            category_hint = None
        if category_hint is None:
            category_hint = self._sanitize_category(existing_suggested_category_name)

        matched_category = self._select_category_by_hint(
            normalized_categories,
            category_type=category_type,
            hint_values=[
                candidate.get('resolved_category_name'),
                category_hint,
                candidate.get('note'),
                latest_user_message,
            ],
            allow_default=False,
        )

        scoped_categories = [item for item in normalized_categories if item.get('type') == category_type.value]
        if (
            matched_category is not None
            and len(scoped_categories) == 1
            and self._extract_category_hint(latest_user_message) is None
            and not self._category_name_mentioned_in_message(
                str(matched_category.get('name') or ''),
                latest_user_message,
            )
        ):
            return None, None, normalized_categories

        if matched_category is not None:
            return matched_category, category_hint, normalized_categories

        create_category_name = self._extract_requested_new_category_name(latest_user_message)
        if create_category_name is not None:
            created_category = await self._create_category_with_tool(
                user_id=user_id,
                category_name=create_category_name,
                category_type=category_type,
                existing_categories=normalized_categories,
            )
            if created_category is not None:
                normalized_categories = [*normalized_categories, created_category]
                return created_category, create_category_name, normalized_categories
            return None, create_category_name, normalized_categories

        if hitl_active:
            llm_selected_name, llm_create_name = await self._resolve_hitl_category_reply_with_llm(
                latest_user_message=latest_user_message,
                category_options=scoped_categories,
                suggested_category_name=category_hint,
            )

            selected_name = llm_selected_name
            create_name = llm_create_name
            if selected_name is None and create_name is None:
                selected_name, create_name = self._resolve_hitl_category_reply_rule_based(
                    latest_user_message=latest_user_message,
                    category_options=scoped_categories,
                    suggested_category_name=category_hint,
                )

            if selected_name is not None:
                selected_category = self._select_category_by_hint(
                    scoped_categories,
                    category_type=None,
                    hint_values=[selected_name],
                    allow_default=False,
                )
                if selected_category is not None:
                    return selected_category, selected_name, normalized_categories

            if create_name is not None:
                created_category = await self._create_category_with_tool(
                    user_id=user_id,
                    category_name=create_name,
                    category_type=category_type,
                    existing_categories=normalized_categories,
                )
                if created_category is not None:
                    normalized_categories = [*normalized_categories, created_category]
                    return created_category, create_name, normalized_categories
                return None, create_name, normalized_categories

        return None, category_hint, normalized_categories

    async def _category_tool_agent(self, state: CategoryToolGraphState) -> dict[str, Any]:
        category_name = str(state.get('requested_category_name') or '').strip()
        category_type = str(state.get('requested_category_type') or '').strip().lower()
        if not category_name or category_type not in {CategoryType.EXPENSE.value, CategoryType.INCOME.value}:
            return {'category_tool_call_id': None}

        tool_call_id = f'category-tool-{uuid.uuid4().hex}'
        return {
            'messages': [
                AIMessage(
                    content='',
                    tool_calls=[
                        {
                            'name': 'create_category',
                            'args': {'category_name': category_name, 'category_type': category_type},
                            'id': tool_call_id,
                            'type': 'tool_call',
                        }
                    ],
                )
            ],
            'category_tool_call_id': tool_call_id,
        }

    async def _category_tool_finalize(self, state: CategoryToolGraphState) -> dict[str, Any]:
        tool_message = self._latest_tool_message(
            state.get('messages', []),
            tool_call_id=state.get('category_tool_call_id'),
        )
        if tool_message is None:
            return {'created_category': None, 'category_tool_call_id': None}

        parsed_payload = self._parse_tool_payload(tool_message.content)
        category = parsed_payload.get('category')
        return {
            'created_category': category if isinstance(category, dict) else None,
            'category_tool_call_id': None,
        }

    async def _create_category_with_tool(
        self,
        *,
        user_id: uuid.UUID,
        category_name: str,
        category_type: CategoryType,
        existing_categories: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        tool_state: CategoryToolGraphState = {
            'runtime_user_id': str(user_id),
            'user_categories': existing_categories,
            'requested_category_name': category_name,
            'requested_category_type': category_type.value,
        }

        tool_result = await self._category_tool_graph.ainvoke(tool_state)
        category = tool_result.get('created_category')
        return category if isinstance(category, dict) else None

    async def _resolve_hitl_category_reply_with_llm(
        self,
        *,
        latest_user_message: str,
        category_options: list[dict[str, Any]],
        suggested_category_name: str | None,
    ) -> tuple[str | None, str | None]:
        if self._llm_hitl_category_resolution_chain is None:
            return None, None

        option_names = [str(item.get('name') or '') for item in category_options if str(item.get('name') or '').strip()]
        try:
            result = await self._llm_hitl_category_resolution_chain.ainvoke(
                {
                    'user_reply': latest_user_message,
                    'category_options_json': json.dumps(option_names, ensure_ascii=False),
                    'suggested_category_name': suggested_category_name or '',
                }
            )
        except Exception:
            return None, None

        selected_category = self._sanitize_category(result.selected_category)
        create_category = self._sanitize_category(result.create_category)
        return selected_category, create_category

    @classmethod
    def _resolve_hitl_category_reply_rule_based(
        cls,
        *,
        latest_user_message: str,
        category_options: list[dict[str, Any]],
        suggested_category_name: str | None,
    ) -> tuple[str | None, str | None]:
        matched_category = cls._select_category_by_hint(
            category_options,
            category_type=None,
            hint_values=[latest_user_message],
            allow_default=False,
        )
        if matched_category is not None:
            return str(matched_category.get('name') or ''), None

        affirmative_create_match = re.search(
            r'^(?:yes|yeah|yep|yup|ok|okay|sure|proceed|go ahead)\s+(.+)$',
            latest_user_message,
            re.IGNORECASE,
        )
        if affirmative_create_match:
            requested_name = cls._sanitize_category(affirmative_create_match.group(1))
            if requested_name is not None:
                suggested_name_for_case = cls._sanitize_category(suggested_category_name)
                if suggested_name_for_case is not None:
                    if cls._normalize_lookup_text(requested_name) == cls._normalize_lookup_text(
                        suggested_name_for_case
                    ):
                        requested_name = suggested_name_for_case

                requested_existing = cls._select_category_by_hint(
                    category_options,
                    category_type=None,
                    hint_values=[requested_name],
                    allow_default=False,
                )
                if requested_existing is not None:
                    return str(requested_existing.get('name') or ''), None
                return None, requested_name

        normalized_message = cls._normalize_lookup_text(latest_user_message)
        suggested_name = cls._sanitize_category(suggested_category_name)
        if suggested_name is None:
            return None, None

        normalized_suggested_name = cls._normalize_lookup_text(suggested_name)
        if not normalized_message or not normalized_suggested_name:
            return None, None

        if normalized_message == normalized_suggested_name:
            return None, suggested_name

        if normalized_suggested_name in normalized_message and re.search(
            r'\b(?:yes|yeah|yep|yup|ok|okay|sure|proceed|go ahead)\b',
            normalized_message,
        ):
            return None, suggested_name

        return None, None

    @classmethod
    def _extract_requested_new_category_name(cls, message: str) -> str | None:
        match = re.search(
            r"\b(?:create|add|new)\s+(?:a\s+)?(?:category\s*)?(?:called\s*)?([A-Za-z][A-Za-z0-9 &'\-.]{1,80})",
            message,
            re.IGNORECASE,
        )
        if not match:
            return None
        return cls._sanitize_category(match.group(1))

    @classmethod
    def _category_name_mentioned_in_message(cls, category_name: str, message: str) -> bool:
        normalized_message = cls._normalize_lookup_text(message)
        normalized_category = cls._normalize_lookup_text(category_name)
        if not normalized_message or not normalized_category:
            return False
        return f' {normalized_category} ' in f' {normalized_message} '

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
    def _is_deterministic_transaction_candidate(message: str) -> bool:
        normalized_message = ' '.join(message.lower().split())
        if LangGraphChatOrchestrator._is_non_transaction_query(normalized_message):
            return False

        has_amount = LangGraphChatOrchestrator._extract_amount_paise(normalized_message) is not None
        has_action_keyword = any(keyword in normalized_message for keyword in _STRONG_TRANSACTION_ACTION_KEYWORDS)
        return has_amount and has_action_keyword

    @staticmethod
    def _is_non_transaction_query(message: str) -> bool:
        normalized_message = ' '.join(message.lower().split())
        has_query_cue = any(cue in normalized_message for cue in _NON_TRANSACTION_QUERY_CUES)
        return has_query_cue or normalized_message.endswith('?')

    @staticmethod
    def _should_route_to_transaction_flow(*, latest_user_message: str, detected_intent: DetectedIntent) -> bool:
        del latest_user_message
        return detected_intent == DetectedIntent.LOG_TRANSACTION

    @staticmethod
    def _should_route_to_query_transactions(*, latest_user_message: str, detected_intent: DetectedIntent) -> bool:
        if detected_intent in {
            DetectedIntent.QUERY_SPENDING,
            DetectedIntent.ACCOUNT_QUERY,
            DetectedIntent.MEMORY_RELATED,
        }:
            return True

        normalized_message = ' '.join(latest_user_message.lower().split())
        if not LangGraphChatOrchestrator._is_non_transaction_query(normalized_message):
            return False

        return any(hint in normalized_message for hint in _FINANCE_QUERY_HINTS)

    @staticmethod
    def _has_date_hint(message: str) -> bool:
        if 'today' in message or 'yesterday' in message:
            return True
        if 'last week' in message or 'last month' in message:
            return True
        if re.search(r'\b\d{1,3}\s+days?\s+ago\b', message):
            return True
        if re.search(r'\b\d{1,3}\s+weeks?\s+ago\b', message):
            return True
        if re.search(r'\b\d{1,3}\s+months?\s+ago\b', message):
            return True
        return bool(re.search(r'\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b', message))

    @staticmethod
    def _has_candidate_date(candidate: dict[str, Any] | None) -> bool:
        if not isinstance(candidate, dict):
            return False

        occurred_at = candidate.get('occurred_at')
        if not isinstance(occurred_at, str):
            return False

        cleaned = occurred_at.strip()
        if not cleaned:
            return False

        try:
            datetime.fromisoformat(cleaned)
        except ValueError:
            return False
        return True

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
    def _validated_timezone_name(timezone_name: str | None) -> str:
        if not timezone_name:
            return 'UTC'
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning('Invalid client timezone `%s`; using UTC.', timezone_name)
            return 'UTC'
        return timezone_name

    @staticmethod
    def _as_guardrail_assessment(value: GuardrailAssessment | GuardrailDecision | str) -> GuardrailAssessment:
        if isinstance(value, GuardrailAssessment):
            return value
        if isinstance(value, GuardrailDecision):
            return GuardrailAssessment(decision=value, confidence=0.5, layer='semantic')
        normalized_value = str(value).strip().lower()
        for decision in GuardrailDecision:
            if decision.value == normalized_value:
                return GuardrailAssessment(decision=decision, confidence=0.5, layer='semantic')
        return GuardrailAssessment(decision=GuardrailDecision.BLOCK, confidence=0.5, layer='semantic')

    @staticmethod
    def _as_detected_intent(value: DetectedIntent | str) -> DetectedIntent:
        if isinstance(value, DetectedIntent):
            return value
        normalized_value = str(value).strip().lower()
        for intent in DetectedIntent:
            if intent.value == normalized_value:
                return intent
        return DetectedIntent.OFF_TOPIC
