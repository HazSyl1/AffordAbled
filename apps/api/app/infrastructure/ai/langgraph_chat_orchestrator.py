from __future__ import annotations

import asyncio
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
from pydantic import BaseModel, Field, model_validator

from app.application.dto import (
    CreateAccountInput,
    CreateTransactionInput,
    UpdateAccountInput,
    UpdateCategoryInput,
    UpdateTransactionInput,
)
from app.application.services.account_service import AccountService
from app.application.services.category_service import CategoryService
from app.application.services.transaction_service import TransactionService
from app.domain.entities import AccountType, CategoryType, TransactionType
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
    "Want me to log a transaction, check spending, or split a bill?"
)
_MAX_SUPERVISOR_HANDOFFS = 3
_SUPERVISOR_DECISION_TIMEOUT_SECONDS = 30
_REGISTERED_SUPERVISOR_WORKFLOWS = frozenset(
    {
        "transaction",
        "analytics",
        "account_management",
        "category_management",
        "transaction_management",
        "format_previous",
    }
)

_CURRENCY_PREFIX_PATTERN = re.compile(
    r"(?:\u20B9|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
_CURRENCY_SUFFIX_PATTERN = re.compile(
    r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:\u20B9|rs\.?|inr|rupees?)",
    re.IGNORECASE,
)
_ANY_NUMBER_PATTERN = re.compile(r"\b([0-9][0-9,]*(?:\.[0-9]{1,2})?)\b")
_MERCHANT_PATTERN = re.compile(
    r"\b(?:at|for|from)\s+([A-Za-z][A-Za-z0-9 &'\-.]{1,80})",
    re.IGNORECASE,
)

_EXPENSE_KEYWORDS = ("spend", "spent", "paid", "pay", "bought", "purchase", "purchased", "debited")
_INCOME_KEYWORDS = ("received", "credited", "salary", "earned", "income", "got paid")
_REFUND_KEYWORDS = ("refund", "refunded", "reimbursed", "reimbursement", "cashback")

_TRANSACTION_ACTION_KEYWORDS = (
    "spend",
    "spent",
    "pay",
    "paid",
    "bought",
    "purchase",
    "purchased",
    "debit",
    "debited",
    "credit",
    "credited",
    "received",
    "salary",
    "income",
    "refund",
    "transfer",
    "transaction",
    "log",
)

_STRONG_TRANSACTION_ACTION_KEYWORDS = (
    "spend",
    "spent",
    "pay",
    "paid",
    "bought",
    "purchase",
    "purchased",
    "debit",
    "debited",
    "credit",
    "credited",
    "received",
    "salary",
    "income",
    "refund",
    "transfer",
)

_NON_TRANSACTION_QUERY_CUES = (
    "what did i",
    "how much",
    "show",
    "summary",
    "this week",
    "this month",
    "weekly",
    "monthly",
    "trend",
    "total",
    "budget",
    "report",
)

_FINANCE_QUERY_HINTS = (
    "spend",
    "spent",
    "spending",
    "transaction",
    "transactions",
    "account",
    "balance",
    "budget",
    "history",
)


class TransactionExtractionOutput(BaseModel):
    is_transaction: bool = Field(
        default=False,
        description=(
            "True only when the user is reporting or asking to record an actual financial transaction. "
            "Questions about spending history or hypothetical examples are not transactions."
        ),
    )
    transaction_type: str | None = Field(
        default=None,
        description=(
            "Transaction direction/type: expense, income, refund, or transfer. "
            "Use the meaning of the user message; return null if it cannot be determined."
        ),
    )
    amount: float | None = Field(
        default=None,
        description=(
            "Positive amount in major currency units (INR rupees, not paise). "
            "Convert spoken or formatted amounts to a number; return null if no amount is stated or inferable."
        ),
    )
    selected_account: str | None = Field(
        default=None,
        description=(
            "Exact name of one account from the supplied account catalog when the user explicitly names or "
            "clearly selects it. Never invent an account or silently substitute another account. Return null "
            "when no account preference is stated or the match is ambiguous."
        ),
    )
    account_hint: str | None = Field(
        default=None,
        description=(
            "The account or institution name/description the user explicitly mentions as the payment source, "
            'even if it does not exactly match one catalog account (for example, "SBI"). Return null when the '
            "user gives no account preference."
        ),
    )
    selected_category: str | None = Field(
        default=None,
        description=(
            "Exact name of an existing user category from the supplied category catalog, only when it is an "
            "appropriate match explicitly stated or strongly supported by the transaction context. "
            "Never choose a merely closest or default category; otherwise return null."
        ),
    )
    category: str | None = Field(
        default=None,
        description=(
            "The category concept expressed or strongly implied by the user, including a useful category name "
            "that could be offered for creation when no existing category matches (for example, Hotel or "
            "Electronics). Do not copy a merchant or location as a category. Return null when no category "
            "concept is supported by the message."
        ),
    )
    merchant: str | None = Field(
        default=None,
        description=(
            "Name of the store, business, person, or other identifiable payee/merchant if stated or reliably "
            "implied (for example, Amazon). Do not invent a business name from a generic venue type or location; "
            'put useful context such as "hotel in Delhi" in note instead. Merchant is optional; return null '
            "rather than asking the user when it cannot be identified."
        ),
    )
    note: str | None = Field(
        default=None,
        description=(
            "Brief transaction context not represented by type, amount, date, merchant, or category, such as "
            '"hotel stay in Delhi" or "new phone". Preserve useful purpose/location details without inventing facts.'
        ),
    )
    occurred_at: datetime | None = Field(
        default=None,
        description=(
            "Date and time when the transaction occurred, as an ISO-8601-compatible datetime. Resolve relative "
            "dates such as today, yesterday, or 2 days ago using the supplied current datetime as the reference. "
            "If the user gives no date, return null; the application will default it to the current datetime."
        ),
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Overall confidence from 0.0 to 1.0 that the transaction is real and the extracted type, amount, "
            "date, merchant, and category are supported by the message. Missing optional merchant/category "
            "information alone should not make an otherwise clear transaction invalid."
        ),
    )


class TransactionBatchExtractionOutput(BaseModel):
    transactions: list[TransactionExtractionOutput] = Field(default_factory=list, min_length=2, max_length=10)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class HitlCategoryResolutionOutput(BaseModel):
    selected_category: str | None = Field(default=None)
    create_category: str | None = Field(default=None)


class FinanceQueryPlan(BaseModel):
    action: Literal["query", "drill_down", "format_previous", "compare_periods"] = Field(
        default="query",
        description=(
            "Choose query for a new database question, drill_down to fetch records behind a prior summary, "
            "or format_previous to sort/reformat stored prior results without querying again."
        ),
    )
    query_kind: Literal["summary", "transaction_list", "account_balance", "spending_by_account"] = Field(
        description=(
            "summary when the user asks how much, totals, or category spend; transaction_list when asking "
            "what transactions/items occurred in a time period."
        )
    )
    date_period: Literal[
        "today",
        "yesterday",
        "this_week",
        "last_week",
        "this_month",
        "last_month",
        "last_n_days",
        "last_n_weeks",
        "recent_default",
    ] = Field(description="The calendar period requested by the user.")
    period_count: int | None = Field(
        default=None,
        ge=1,
        le=180,
        description="Number of days or weeks when date_period is last_n_days or last_n_weeks.",
    )
    category_names: list[str] = Field(
        default_factory=list,
        max_length=5,
        description=(
            "Every expense category explicitly or clearly requested, such as Food and Transport. "
            "Return an empty list when no category is requested."
        ),
    )
    category_scope: Literal["all", "selected", "unspecified"] = Field(
        default="all",
        description=(
            "Use all when no category filter is requested, selected when one or more category names are supplied, "
            "and unspecified when the user requests particular categories but does not identify them."
        ),
    )
    transaction_type: Literal["expense", "income", "all"] = Field(
        default="all",
        description="Filter transaction-list results by direction; use expense when drilling down into spending.",
    )
    comparison_period: Literal["last_week", "last_month"] | None = None
    account_names: list[str] = Field(default_factory=list, max_length=10)
    result_format: Literal["table", "list"] = Field(
        default="list",
        description="Requested presentation for prior transaction rows when action is format_previous.",
    )
    sort_order: Literal["newest_first", "oldest_first"] = Field(
        default="newest_first",
        description="Chronological order for transaction rows; newest_first is the default unless user asks ascending.",
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_comparison(self) -> FinanceQueryPlan:
        if self.action != "compare_periods":
            return self
        supported_pair = (self.date_period == "this_month" and self.comparison_period == "last_month") or (
            self.date_period == "this_week" and self.comparison_period == "last_week"
        )
        if not supported_pair:
            raise ValueError("Only this month vs last month and this week vs last week are supported")
        if self.query_kind != "summary":
            raise ValueError("Period comparisons require a summary query")
        return self


class FinanceQueryReply(BaseModel):
    reply: str = Field(
        description=(
            "A concise, natural answer to the user using only the supplied computed facts. Preserve amounts, "
            "periods, category names, and counts exactly; do not add calculations or unsupported claims."
        )
    )


class SupervisorAction(BaseModel):
    action: Literal["run_workflow", "ask_user", "finish", "refuse"] = Field(
        description="Exactly one next action: run one registered workflow, ask the user, finish, or refuse."
    )
    workflow_id: (
        Literal[
            "transaction",
            "analytics",
            "account_management",
            "category_management",
            "transaction_management",
            "format_previous",
        ]
        | None
    ) = Field(
        default=None,
        description="Required only for run_workflow; must be a currently registered workflow ID.",
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Must be empty: registered workflows currently consume the authenticated turn state directly.",
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=240)
    response: str | None = Field(
        default=None,
        max_length=600,
        description="Short user-facing clarification or final response; never include unverified facts.",
    )

    @model_validator(mode="after")
    def validate_workflow_target(self) -> SupervisorAction:
        if self.action == "run_workflow" and self.workflow_id is None:
            raise ValueError("run_workflow requires a registered workflow_id")
        if self.action != "run_workflow" and self.workflow_id is not None:
            raise ValueError("workflow_id is only valid for run_workflow")
        return self


class WorkflowResult(BaseModel):
    workflow_id: Literal[
        "transaction",
        "analytics",
        "account_management",
        "category_management",
        "transaction_management",
        "format_previous",
    ]
    status: Literal["success", "needs_input", "failed"]
    summary: str = Field(max_length=600)
    result_ref: Literal["finance_result", "management_request", "transaction_proposal", "mutation_proposal", "none"] = (
        "none"
    )
    side_effect: Literal["none", "proposed", "committed"] = "none"


class AccountManagementRequest(BaseModel):
    operation: Literal["create", "rename", "set_default", "activate", "deactivate", "clarify"]
    account_name: str | None = Field(default=None, max_length=120)
    new_name: str | None = Field(default=None, max_length=120)
    account_type: Literal["cash", "bank", "card", "wallet"] | None = None
    opening_balance: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CategoryManagementRequest(BaseModel):
    operation: Literal["create", "rename", "delete", "clarify"]
    category_name: str | None = Field(default=None, max_length=120)
    new_name: str | None = Field(default=None, max_length=120)
    category_type: Literal["expense", "income"] | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class TransactionManagementRequest(BaseModel):
    operation: Literal["edit", "delete", "restore", "clarify"]
    selected_transaction_id: str | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    account_name: str | None = Field(default=None, max_length=120)
    category_name: str | None = Field(default=None, max_length=120)
    transaction_type: Literal["expense", "income", "refund"] | None = None
    occurred_at: datetime | None = None
    merchant: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=500)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ChatGraphState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    workflow_action: str
    pending_proposal: dict[str, Any] | None
    extracted_candidate: dict[str, Any] | None
    extracted_candidates: list[dict[str, Any]] | None
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
    pending_supervisor_question: str | None
    supervisor_action: str | None
    supervisor_workflow_id: str | None
    supervisor_arguments: dict[str, Any]
    supervisor_handoff_count: int
    supervisor_executed_workflows: list[str]
    workflow_result: dict[str, Any] | None
    active_workflow_id: str | None
    active_workflow_start_query_generation: int
    finance_query_generation: int
    pending_category_request: dict[str, Any] | None
    pending_account_request: dict[str, Any] | None
    pending_transaction_management_request: dict[str, Any] | None
    pending_mutation: dict[str, Any] | None
    pending_proposals_queue: list[dict[str, Any]] | None
    mutation_committed: bool
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
        self._account_service = AccountService(account_repository=account_repository)
        self._category_service = CategoryService(category_repository=category_repository)
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
            messages_key="messages",
        )
        self._query_tool_node = ToolNode(
            self._langgraph_finance_tools.build_query_tools(),
            messages_key="messages",
        )
        self._proposal_confidence_threshold = max(0, min(int(proposal_confidence_threshold), 100))
        self._hitl_max_turns = max(1, int(hitl_max_turns))
        self._deterministic_transaction_first = bool(deterministic_transaction_first)

        self._guardrail_chain = (
            ChatPromptTemplate.from_messages(
                [
                    ("system", "Classify whether this user message is in finance scope."),
                    ("human", "{message}"),
                ]
            )
            | RunnableLambda(self._extract_message_from_prompt)
            | RunnableLambda(self._semantic_guardrail.assess)
        )

        self._intent_chain = (
            ChatPromptTemplate.from_messages(
                [
                    ("system", "Classify the finance intent for this user message."),
                    ("human", "{message}"),
                ]
            )
            | RunnableLambda(self._extract_message_from_prompt)
            | RunnableLambda(self._intent_classifier.classify)
        )

        self._llm_extraction_chain = None
        self._llm_batch_extraction_chain = None
        self._llm_hitl_category_resolution_chain = None
        self._llm_category_management_chain = None
        self._llm_account_management_chain = None
        self._llm_transaction_management_chain = None
        self._supervisor_workflow_chain = None
        self._llm_query_plan_chain = None
        self._llm_query_reply_chain = None
        if extraction_llm is not None:
            extraction_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        (
                            "Extract transaction details from the user message. "
                            "Mark is_transaction=true only when the user is asking to log a real transaction. "
                            "transaction_type must be one of: expense, income, refund, transfer. "
                            "amount must be positive in major currency units (for example 250.75). "
                            "Choose selected_account only from the supplied accounts catalog. Capture an explicit "
                            "but unresolved account/institution name in account_hint; do not replace it with the "
                            "default account. If the user gives no account preference, leave both fields null. "
                            "Resolve occurred_at from relative date language using the supplied current datetime; "
                            "return null only when the user gives no date. "
                            "For selected_category, choose only an appropriate exact existing category from the "
                            "catalog; never choose a merely closest or default category. "
                            "For category, extract the user-supported category concept even if it is not in the "
                            "catalog, so the application can offer to create it; return null if no category concept "
                            "is supported. "
                            "Extract a merchant only when an identifiable merchant is stated or reliably implied; "
                            "do not invent a business from a venue type or location. Preserve details such as "
                            '"hotel in Delhi" or "new phone" in note. Merchant is optional. '
                            "Set confidence between 0 and 1 for extraction certainty."
                        ),
                    ),
                    (
                        "human",
                        "Today is {today_utc}. User message: {message}. "
                        "Available accounts (JSON): {accounts_catalog}. "
                        "Available categories (JSON): {categories_catalog}",
                    ),
                ]
            )
            self._llm_extraction_chain = extraction_prompt | extraction_llm.with_structured_output(
                TransactionExtractionOutput
            )

            batch_extraction_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        (
                            "Extract every dated transaction row in source order. Return between 2 and 10 rows. "
                            "Each row must keep its own amount, date, account, category, merchant, and note. Choose "
                            "account and category names only from the supplied authenticated catalogs. Leave "
                            "transaction_type null when direction is not explicit; the application may infer it "
                            "from an exact category match. Never merge rows or create missing rows."
                        ),
                    ),
                    (
                        "human",
                        "Today is {today_utc}. Rows: {message}. Accounts: {accounts_catalog}. "
                        "Categories: {categories_catalog}",
                    ),
                ]
            )
            self._llm_batch_extraction_chain = batch_extraction_prompt | extraction_llm.with_structured_output(
                TransactionBatchExtractionOutput, method="function_calling"
            )

            hitl_category_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        (
                            "You resolve user replies during a category clarification step. "
                            "Return selected_category when user picks an existing category from options. "
                            "Return create_category when user clearly asks or confirms creating a new category. "
                            "Treat semantic matches and short replies (for example yes transport, first one) as valid. "
                            "If uncertain, keep both fields null. "
                            "Never hallucinate categories outside the user reply/options."
                        ),
                    ),
                    (
                        "human",
                        "User reply: {user_reply}. "
                        "Available category options (JSON): {category_options_json}. "
                        "Suggested new category name: {suggested_category_name}.",
                    ),
                ]
            )
            self._llm_hitl_category_resolution_chain = hitl_category_prompt | extraction_llm.with_structured_output(
                HitlCategoryResolutionOutput
            )

            category_management_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        (
                            "Interpret a category-management request. Supported operations are create, rename, and "
                            "delete. For rename, category_name is the current name and new_name is the replacement. "
                            "Extract whether it is an expense or income category when stated. Use "
                            "category context only when the user clearly indicates it (for example “expense category” "
                            "or a reply “expense” to a prior clarification). Do not assume every category is expense. "
                            "If the user is answering a pending category-type question, preserve the pending name and "
                            "interpret their short reply as the type. If name or type is unclear, return null for it. "
                            "Never mutate a category or invent a name in this parser."
                        ),
                    ),
                    (
                        "human",
                        "Current user message: {message}\nPending category request: {pending_request}",
                    ),
                ]
            )
            self._llm_category_management_chain = category_management_prompt | extraction_llm.with_structured_output(
                CategoryManagementRequest
            )

            account_management_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        (
                            "Interpret an account-management request. Supported operations are create, rename, "
                            "set_default, activate, and deactivate. Extract an account name only when stated. For "
                            "rename, account_name is the current name and new_name is the requested replacement. "
                            "For create, extract account_type, opening_balance in major currency units, and the "
                            "three-letter currency. Do not invent missing values. Use pending request fields only "
                            "when the current message clearly answers the pending question."
                        ),
                    ),
                    (
                        "human",
                        "Current user message: {message}\nPending account request: {pending_request}\n"
                        "Owned accounts (JSON): {accounts_catalog}",
                    ),
                ]
            )
            self._llm_account_management_chain = account_management_prompt | extraction_llm.with_structured_output(
                AccountManagementRequest
            )

            transaction_management_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        (
                            "Interpret a request to edit, delete, or restore an existing transaction. Choose a "
                            "selected_transaction_id only from the supplied authenticated transaction catalog. If "
                            "more than one row could match, leave it null. For edits, return only fields explicitly "
                            "requested by the user. Amount is in major currency units. Never invent an account, "
                            "category, merchant, note, date, or transaction ID."
                        ),
                    ),
                    (
                        "human",
                        "Current user message: {message}\nPending request: {pending_request}\n"
                        "Transactions (JSON): {transactions_catalog}\nAccounts (JSON): {accounts_catalog}\n"
                        "Categories (JSON): {categories_catalog}",
                    ),
                ]
            )
            self._llm_transaction_management_chain = (
                transaction_management_prompt | extraction_llm.with_structured_output(TransactionManagementRequest)
            )

            supervisor_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        (
                            "You are a bounded workflow supervisor for a personal finance assistant. Return exactly "
                            "one action: run_workflow with one registered workflow_id; ask_user with a focused "
                            "clarification; finish when the current request is complete; or refuse when clearly "
                            "off-topic. Registered workflow IDs are transaction (new transaction proposal), "
                            "analytics, account_management, category_management, transaction_management, and "
                            "format_previous. arguments must always be an empty object; "
                            "workflows interpret the authenticated current turn and trusted graph state themselves. "
                            "Do not invent unregistered capabilities such as split, memory, or account-balance "
                            "specialists, or file export. The first action should address the current user request. "
                            "After a workflow "
                            "result, use its bounded status/summary to decide whether another distinct registered "
                            "workflow is necessary to complete the request; otherwise finish. Never repeat a workflow "
                            "that already ran this turn. Stop when a workflow needs user input, fails, or proposes a "
                            "transaction. Mutation workflows may produce a confirmation proposal; stop when one is "
                            "waiting. Do not chain unrelated work after a mutation. Keep the per-turn limit in mind. "
                            "A hard-block guardrail cannot be overridden. You do not execute tools, calculate money, "
                            "commit transactions, or change authenticated user scope. Use only verified workflow "
                            "results for final wording; do not invent financial facts."
                        ),
                    ),
                    (
                        "human",
                        "Current message: {message}\nRecent conversation: {conversation_context}\n"
                        "Classified intent hint: {intent}\nGuardrail: {guardrail_decision}\n"
                        "Prior query plan: {previous_plan}\n"
                        "Last workflow result (bounded summary only): {workflow_result}\n"
                        "Clarification question awaiting this reply: {pending_question}\n"
                        "Handoffs used: {handoff_count}. Previously executed workflow keys: {executed_workflows}",
                    ),
                ]
            )
            self._supervisor_workflow_chain = supervisor_prompt | extraction_llm.with_structured_output(
                SupervisorAction, method="function_calling"
            )

            query_plan_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        (
                            "Interpret a personal-finance query into a structured plan. Choose summary when the "
                            "user asks how much they spent, totals, or spending by category. Choose transaction_list "
                            "when they ask what transactions happened or simply name a period such as yesterday. "
                            "Choose account_balance for current balances or available funds, and put only explicitly "
                            "requested account names in account_names. Choose spending_by_account when the user asks "
                            "to group spending across accounts. Choose compare_periods only for this month versus "
                            "last month or this week versus last week; store the earlier period in comparison_period. "
                            "Extract every category the user asks about, including multiple categories joined by "
                            "and, or, commas. Set category_scope=all when no category filter is requested, "
                            "selected when category names are supplied, and unspecified when the user asks about "
                            "some categories but does not identify them; never treat unspecified as all spending. "
                            "Resolve short follow-up messages such as “where?” using recent conversation and the "
                            "previous query plan. When the user asks where a prior spending total went, return "
                            "action=drill_down, set query_kind=transaction_list, preserve that plan’s date/category "
                            "scope, and set transaction_type=expense. When the user asks to sort, format, or show "
                            "previously returned records as a table/list, choose action=format_previous, preserve "
                            "the prior result and do not request a new query. Choose sort_order=oldest_first for "
                            "ascending/oldest first and newest_first otherwise. "
                            "Resolve phrases like today, "
                            "yesterday, this week, last week, this month, last month, and the last N days/weeks "
                            "relative to the supplied local date and timezone. Do not calculate money or invent "
                            "transactions; the database tools do that."
                        ),
                    ),
                    (
                        "human",
                        "Recent conversation: {conversation_context}\n"
                        "Previous finance query plan: {previous_query_plan}\n"
                        "Previous structured result: {previous_query_result}\n"
                        "Local now: {local_now}. Timezone: {timezone}. Current user query: {message}",
                    ),
                ]
            )
            self._llm_query_plan_chain = query_plan_prompt | extraction_llm.with_structured_output(FinanceQueryPlan)

            query_reply_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        (
                            "Write one concise, natural answer to the finance query using only the supplied facts. "
                            "The facts were computed by database tools and are authoritative. Do not recalculate, "
                            "round, infer, or invent any amount, count, date, category, merchant, or comparison. "
                            "Mention the requested category and period when provided. Avoid canned insight labels "
                            "and do not claim a trend unless trend data is present. When the user asks for details, "
                            "a breakdown, or multiple records, prefer a compact Markdown table when the facts share "
                            "consistent fields and a table is readable (for example date, merchant, amount, category). "
                            "Otherwise use concise labeled sections or bullets. Honor explicit format or sort order. "
                            "For a single fact, use a short sentence rather than forcing a table. Do not output raw "
                            "JSON "
                            "or add fields absent from the computed facts."
                        ),
                    ),
                    ("human", "User query: {question}\nComputed facts (JSON): {facts_json}"),
                ]
            )
            self._llm_query_reply_chain = query_reply_prompt | extraction_llm.with_structured_output(FinanceQueryReply)

        builder = StateGraph(ChatGraphState)
        builder.add_node("analyze_turn", self._analyze_turn)
        builder.add_node("supervisor", self._supervisor_node)
        builder.add_node("workflow_dispatch", self._workflow_dispatch_node)
        builder.add_node("workflow_observer", self._workflow_observer_node)
        builder.add_node("supervisor_ask_user", self._supervisor_ask_user_node)
        builder.add_node("supervisor_finish", self._supervisor_finish_node)
        builder.add_node("account_management", self._account_management_node)
        builder.add_node("category_management", self._category_management_node)
        builder.add_node("transaction_management", self._transaction_management_node)
        builder.add_node("mutation_confirmation", self._mutation_confirmation_node)
        builder.add_node("populate_user_context", self._populate_user_context)
        builder.add_node("extract_transaction_candidate", self._extract_transaction_candidate_node)
        builder.add_node("evaluate_transaction_candidate", self._evaluate_transaction_candidate)
        builder.add_node("hitl_clarification", self._hitl_clarification_node)
        builder.add_node("transaction_flow", self._transaction_flow)
        builder.add_node("query_planner", self._query_planner_node)
        builder.add_node("format_previous_result", self._format_previous_result_node)
        builder.add_node("query_orchestrator", self._query_orchestrator_node)
        builder.add_node("query_tool_executor", self._query_tool_node)
        builder.add_node("query_tool_finalize", self._query_tool_finalize)
        builder.add_node("assistant_default", self._assistant_default)
        builder.add_node("assistant_refusal", self._assistant_refusal)

        builder.add_edge(START, "analyze_turn")
        builder.add_conditional_edges(
            "analyze_turn",
            self._route_after_analysis,
            {
                "populate_user_context": "populate_user_context",
                "transaction_flow": "transaction_flow",
                "mutation_confirmation": "mutation_confirmation",
                "query_tool_agent": "query_planner",
                "account_management": "account_management",
                "category_management": "category_management",
                "transaction_management": "transaction_management",
                "supervisor": "supervisor",
                "assistant_default": "assistant_default",
                "assistant_refusal": "assistant_refusal",
            },
        )
        builder.add_conditional_edges(
            "supervisor",
            self._route_after_supervisor_action,
            {
                "workflow_dispatch": "workflow_dispatch",
                "supervisor_ask_user": "supervisor_ask_user",
                "supervisor_finish": "supervisor_finish",
                "assistant_refusal": "assistant_refusal",
            },
        )
        builder.add_conditional_edges(
            "workflow_dispatch",
            self._route_after_workflow_dispatch,
            {
                "populate_user_context": "populate_user_context",
                "query_tool_agent": "query_planner",
                "account_management": "account_management",
                "category_management": "category_management",
                "transaction_management": "transaction_management",
                "format_previous_result": "format_previous_result",
                "assistant_default": "assistant_default",
                "assistant_refusal": "assistant_refusal",
                "supervisor_finish": "supervisor_finish",
            },
        )
        builder.add_edge("supervisor_ask_user", "supervisor")
        builder.add_edge("supervisor_finish", END)
        specialist_nodes = (
            "account_management",
            "category_management",
            "transaction_management",
            "mutation_confirmation",
            "transaction_flow",
            "format_previous_result",
            "query_tool_finalize",
        )
        for specialist_node in specialist_nodes:
            builder.add_conditional_edges(
                specialist_node,
                self._route_after_specialist,
                {"workflow_observer": "workflow_observer", END: END},
            )
        builder.add_conditional_edges(
            "workflow_observer",
            self._route_after_workflow_observation,
            {"supervisor": "supervisor", "supervisor_finish": "supervisor_finish"},
        )
        builder.add_edge("populate_user_context", "extract_transaction_candidate")
        builder.add_edge("extract_transaction_candidate", "evaluate_transaction_candidate")
        builder.add_conditional_edges(
            "evaluate_transaction_candidate",
            self._route_after_candidate_evaluation,
            {
                "hitl_clarification": "hitl_clarification",
                "transaction_flow": "transaction_flow",
                "assistant_default": "assistant_default",
            },
        )
        builder.add_conditional_edges(
            "hitl_clarification",
            self._route_after_hitl_clarification,
            {
                "extract_transaction_candidate": "extract_transaction_candidate",
                "transaction_flow": "transaction_flow",
            },
        )
        builder.add_conditional_edges(
            "query_planner",
            self._route_after_query_plan,
            {
                "query_orchestrator": "query_orchestrator",
                "format_previous_result": "format_previous_result",
                "assistant_default": "assistant_default",
            },
        )
        builder.add_conditional_edges(
            "query_orchestrator",
            tools_condition,
            {
                "tools": "query_tool_executor",
                "__end__": "query_tool_finalize",
            },
        )
        builder.add_edge("query_tool_executor", "query_tool_finalize")
        builder.add_conditional_edges(
            "assistant_default",
            self._route_after_assistant_default,
            {"workflow_observer": "workflow_observer", END: END},
        )
        builder.add_edge("assistant_refusal", END)

        self._graph = builder.compile(checkpointer=checkpointer)

        category_tool_builder = StateGraph(CategoryToolGraphState)
        category_tool_builder.add_node("category_tool_agent", self._category_tool_agent)
        category_tool_builder.add_node("category_tool_executor", self._category_tool_node)
        category_tool_builder.add_node("category_tool_finalize", self._category_tool_finalize)
        category_tool_builder.add_edge(START, "category_tool_agent")
        category_tool_builder.add_conditional_edges(
            "category_tool_agent",
            tools_condition,
            {
                "tools": "category_tool_executor",
                "__end__": "category_tool_finalize",
            },
        )
        category_tool_builder.add_edge("category_tool_executor", "category_tool_finalize")
        category_tool_builder.add_edge("category_tool_finalize", END)
        self._category_tool_graph = category_tool_builder.compile()

    def graph_mermaid(self) -> str:
        return self._graph.get_graph().draw_mermaid()

    def graph_png(self, output_file_path: str | None = None) -> bytes:
        return self._graph.get_graph().draw_mermaid_png(output_file_path=output_file_path)

    def save_graph_assets(self, output_dir: str | Path) -> tuple[Path, Path | None]:
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        mermaid_path = target_dir / "chat_langgraph.mmd"
        mermaid_path.write_text(self.graph_mermaid(), encoding="utf-8")

        png_path = target_dir / "chat_langgraph.png"
        try:
            self.graph_png(str(png_path))
            rendered_png_path: Path | None = png_path
        except Exception:
            rendered_png_path = None

        return mermaid_path, rendered_png_path

    @traceable(name="langgraph_chat_turn", run_type="chain")
    async def run_turn(
        self,
        *,
        user_id: uuid.UUID,
        thread_id: str,
        message: str,
        timezone: str | None = None,
    ) -> ChatTurnResult:
        checkpoint_thread_id = f"{user_id}:{thread_id}"
        timezone_name = self._validated_timezone_name(timezone)
        config = {
            "configurable": {
                "thread_id": checkpoint_thread_id,
            }
        }

        state_snapshot = await self._graph.aget_state(config=config)
        if state_snapshot.interrupts:
            graph_input: dict[str, Any] | Command = Command(
                resume=message,
                update={
                    "messages": [HumanMessage(content=message)],
                    "transaction_logged": False,
                    "manual_transaction_input_required": False,
                    "mutation_committed": False,
                    "pending_proposals_queue": None,
                    "insights": None,
                    "agent_correction": None,
                    "runtime_timezone": timezone_name,
                },
            )
        else:
            graph_input = {
                "messages": [HumanMessage(content=message)],
                "runtime_user_id": str(user_id),
                "transaction_logged": False,
                "manual_transaction_input_required": False,
                "mutation_committed": False,
                "pending_proposals_queue": None,
                "insights": None,
                "agent_correction": None,
                "runtime_timezone": timezone_name,
                "supervisor_action": None,
                "supervisor_workflow_id": None,
                "supervisor_arguments": {},
                "supervisor_handoff_count": 0,
                "supervisor_executed_workflows": [],
                "workflow_result": None,
                "active_workflow_id": None,
            }

        result = await self._graph.ainvoke(graph_input, config=config)

        assistant_message = _REFUSAL_MESSAGE
        graph_interrupts = result.get("__interrupt__", [])
        if graph_interrupts:
            first_interrupt = graph_interrupts[0]
            interrupt_payload = getattr(first_interrupt, "value", None)
            if isinstance(interrupt_payload, dict):
                assistant_message = str(interrupt_payload.get("question") or _REFUSAL_MESSAGE)
            else:
                assistant_message = _REFUSAL_MESSAGE
        else:
            for item in reversed(result.get("messages", [])):
                if isinstance(item, AIMessage):
                    assistant_message = str(item.content)
                    break

        pending_proposals_raw = result.get("pending_proposals_queue") or []
        pending_proposal_raw = result.get("pending_proposal")
        if pending_proposal_raw is None and pending_proposals_raw:
            pending_proposal_raw = pending_proposals_raw[0]
        if pending_proposal_raw is None and bool(result.get("manual_transaction_input_required", False)):
            pending_proposal_raw = result.get("manual_prefill_proposal")
        pending_proposal: PendingTransactionProposal | None = None
        if pending_proposal_raw is not None:
            pending_proposal = PendingTransactionProposal(
                type=str(pending_proposal_raw["type"]),
                amount_paise=int(pending_proposal_raw["amount_paise"]),
                occurred_at=str(pending_proposal_raw["occurred_at"]),
                merchant=pending_proposal_raw.get("merchant"),
                note=pending_proposal_raw.get("note"),
                account_id=str(pending_proposal_raw["account_id"]),
                account_name=str(pending_proposal_raw["account_name"]),
                category_id=str(pending_proposal_raw["category_id"]),
                category_name=str(pending_proposal_raw["category_name"]),
                confidence_score=int(pending_proposal_raw.get("confidence_score", 0)),
            )

        pending_proposals = [
            PendingTransactionProposal(
                type=str(item["type"]),
                amount_paise=int(item["amount_paise"]),
                occurred_at=str(item["occurred_at"]),
                merchant=item.get("merchant"),
                note=item.get("note"),
                account_id=str(item["account_id"]),
                account_name=str(item["account_name"]),
                category_id=str(item["category_id"]),
                category_name=str(item["category_name"]),
                confidence_score=int(item.get("confidence_score", 0)),
            )
            for item in pending_proposals_raw
        ]

        return ChatTurnResult(
            message=assistant_message,
            pending_transaction_proposal=pending_proposal,
            pending_transaction_proposals=pending_proposals or None,
            transaction_logged=bool(result.get("transaction_logged", False)),
            manual_transaction_input_required=bool(result.get("manual_transaction_input_required", False)),
            intent=result.get("intent"),
            guardrail_decision=str(result.get("guardrail_decision", GuardrailDecision.ALLOW.value)),
            guardrail_confidence=float(result.get("guardrail_confidence", 1.0)),
            guardrail_layer=str(result.get("guardrail_layer", "semantic")),
            insights=result.get("insights"),
            agent_correction=result.get("agent_correction"),
        )

    async def _analyze_turn(self, state: ChatGraphState) -> dict[str, Any]:
        latest_user_message = self._latest_user_message(state.get("messages", []))
        if not latest_user_message:
            return {
                "workflow_action": "default",
                "intent": state.get("intent"),
                "guardrail_decision": state.get("guardrail_decision", GuardrailDecision.ALLOW.value),
                "guardrail_confidence": float(state.get("guardrail_confidence", 1.0)),
                "guardrail_layer": state.get("guardrail_layer", "semantic"),
            }

        pending_proposal = state.get("pending_proposal")
        if pending_proposal is not None:
            proposal_action = self._proposal_action(latest_user_message)
            if proposal_action is not None:
                return {
                    "workflow_action": proposal_action,
                    "intent": state.get("intent"),
                    "guardrail_decision": state.get("guardrail_decision", GuardrailDecision.ALLOW.value),
                    "guardrail_confidence": float(state.get("guardrail_confidence", 1.0)),
                    "guardrail_layer": state.get("guardrail_layer", "semantic"),
                }
            return {
                "workflow_action": "proposal_wait",
                "intent": state.get("intent"),
                "guardrail_decision": state.get("guardrail_decision", GuardrailDecision.ALLOW.value),
                "guardrail_confidence": float(state.get("guardrail_confidence", 1.0)),
                "guardrail_layer": state.get("guardrail_layer", "semantic"),
            }

        if state.get("pending_mutation") is not None:
            return {
                "workflow_action": self._mutation_confirmation_action(latest_user_message),
                "intent": state.get("intent"),
                "guardrail_decision": state.get("guardrail_decision", GuardrailDecision.ALLOW.value),
                "guardrail_confidence": float(state.get("guardrail_confidence", 1.0)),
                "guardrail_layer": state.get("guardrail_layer", "semantic"),
            }

        if state.get("hitl_active"):
            proposal_action = self._proposal_action(latest_user_message)
            if proposal_action == "cancel_proposal":
                return {
                    "workflow_action": "cancel_hitl",
                    "intent": state.get("intent"),
                    "guardrail_decision": state.get("guardrail_decision", GuardrailDecision.ALLOW.value),
                    "guardrail_confidence": float(state.get("guardrail_confidence", 1.0)),
                    "guardrail_layer": state.get("guardrail_layer", "semantic"),
                }
            return {
                "workflow_action": "build_proposal",
                "intent": state.get("intent"),
                "guardrail_decision": state.get("guardrail_decision", GuardrailDecision.ALLOW.value),
                "guardrail_confidence": float(state.get("guardrail_confidence", 1.0)),
                "guardrail_layer": state.get("guardrail_layer", "semantic"),
            }

        if self._looks_like_multiple_transaction_rows(latest_user_message):
            return {
                "workflow_action": "build_proposal",
                "intent": DetectedIntent.LOG_TRANSACTION.value,
                "guardrail_decision": GuardrailDecision.ALLOW.value,
                "guardrail_confidence": 1.0,
                "guardrail_layer": "batch_detector",
            }

        if self._deterministic_transaction_first and self._is_deterministic_transaction_candidate(latest_user_message):
            return {
                "workflow_action": "build_proposal",
                "intent": DetectedIntent.LOG_TRANSACTION.value,
                "guardrail_decision": GuardrailDecision.ALLOW.value,
                "guardrail_confidence": 1.0,
                "guardrail_layer": "classifier",
            }

        routing_message = self._conversation_aware_message(state.get("messages", []))
        guardrail_assessment = self._as_guardrail_assessment(
            await self._guardrail_chain.ainvoke({"message": routing_message})
        )
        detected_intent = self._as_detected_intent(await self._intent_chain.ainvoke({"message": routing_message}))
        metadata = {
            "intent": detected_intent.value,
            "guardrail_decision": guardrail_assessment.decision.value,
            "guardrail_confidence": guardrail_assessment.confidence,
            "guardrail_layer": guardrail_assessment.layer,
        }

        if guardrail_assessment.decision == GuardrailDecision.BLOCK:
            if detected_intent == DetectedIntent.LOG_TRANSACTION and self._is_deterministic_transaction_candidate(
                latest_user_message
            ):
                return {"workflow_action": "build_proposal", **metadata}
            return {"workflow_action": "refusal", **metadata}

        if guardrail_assessment.decision == GuardrailDecision.NEEDS_CLASSIFICATION:
            if detected_intent == DetectedIntent.OFF_TOPIC and not state.get("last_finance_query_result"):
                return {"workflow_action": "refusal", **metadata}

        if state.get("pending_account_request"):
            return {"workflow_action": "account_management", **metadata}
        if state.get("pending_category_request"):
            return {"workflow_action": "category_management", **metadata}
        if state.get("pending_transaction_management_request"):
            return {"workflow_action": "transaction_management", **metadata}

        return {"workflow_action": "supervisor", **metadata}

    @staticmethod
    def _route_after_analysis(state: ChatGraphState) -> str:
        action = state.get("workflow_action")
        if action == "build_proposal":
            return "populate_user_context"
        if action in {
            "confirm_proposal",
            "cancel_proposal",
            "edit_proposal",
            "proposal_wait",
            "cancel_hitl",
        }:
            return "transaction_flow"
        if action in {"confirm_mutation", "cancel_mutation", "mutation_wait"}:
            return "mutation_confirmation"
        if action == "query_transactions":
            return "query_tool_agent"
        if action == "account_management":
            return "account_management"
        if action == "category_management":
            return "category_management"
        if action == "transaction_management":
            return "transaction_management"
        if action == "supervisor":
            return "supervisor"
        if action == "refusal":
            return "assistant_refusal"
        return "assistant_default"

    async def _supervisor_node(self, state: ChatGraphState) -> dict[str, Any]:
        latest_user_message = self._latest_user_message(state.get("messages", []))
        if not latest_user_message:
            return {"supervisor_action": "finish", "supervisor_response": "What would you like help with?"}

        detected_intent = self._as_detected_intent(state.get("intent"))
        is_explicit_category_create = bool(
            re.match(r"^\s*(?:please\s+)?(?:create|add|new)\b", latest_user_message, re.IGNORECASE)
            and re.search(r"\bcategor(?:y|ies)\b", latest_user_message, re.IGNORECASE)
            and self._extract_requested_new_category_name(latest_user_message)
        )
        if is_explicit_category_create:
            return self._supervisor_fallback_update(
                latest_user_message,
                DetectedIntent.CATEGORY_MANAGEMENT,
                state,
            )
        if detected_intent == DetectedIntent.CATEGORY_MANAGEMENT:
            return self._supervisor_fallback_update(latest_user_message, detected_intent, state)
        if detected_intent in {DetectedIntent.ACCOUNT_MANAGEMENT, DetectedIntent.TRANSACTION_MANAGEMENT}:
            return self._supervisor_fallback_update(latest_user_message, detected_intent, state)

        if getattr(self, "_supervisor_workflow_chain", None) is not None:
            try:
                decision = await asyncio.wait_for(
                    self._supervisor_workflow_chain.ainvoke(
                        {
                            "message": latest_user_message,
                            "conversation_context": self._supervisor_conversation_context(state.get("messages", []))
                            or "No earlier conversation.",
                            "intent": detected_intent.value,
                            "guardrail_decision": state.get("guardrail_decision", GuardrailDecision.ALLOW.value),
                            "previous_plan": json.dumps(
                                state.get("last_finance_query_plan") or state.get("query_plan"),
                                ensure_ascii=False,
                            ),
                            "workflow_result": json.dumps(state.get("workflow_result"), ensure_ascii=False),
                            "pending_question": state.get("pending_supervisor_question") or "None",
                            "handoff_count": state.get("supervisor_handoff_count", 0),
                            "executed_workflows": json.dumps(state.get("supervisor_executed_workflows", [])),
                        }
                    ),
                    timeout=_SUPERVISOR_DECISION_TIMEOUT_SECONDS,
                )
                if decision.confidence >= 0.55:
                    return self._supervisor_decision_update(decision, state)
            except Exception:
                logger.exception("Workflow supervisor failed; falling back to safe registered intent routing.")

        return self._supervisor_fallback_update(latest_user_message, detected_intent, state)

    def _supervisor_decision_update(self, decision: SupervisorAction, state: ChatGraphState) -> dict[str, Any]:
        if state.get("guardrail_decision") == GuardrailDecision.BLOCK.value:
            return {"supervisor_action": "refuse", "supervisor_response": None}

        has_previous_result = bool(state.get("last_finance_query_result"))
        latest_user_message = self._latest_user_message(state.get("messages", []))
        detected_intent = self._as_detected_intent(state.get("intent"))
        if (
            state.get("workflow_result") is None
            and decision.action in {"finish", "refuse"}
            and self._has_explicit_finance_query_cue(latest_user_message)
            and self._should_route_to_query_transactions(
                latest_user_message=latest_user_message,
                detected_intent=detected_intent,
            )
        ):
            decision = decision.model_copy(update={"action": "run_workflow", "workflow_id": "analytics"})
        if decision.action != "run_workflow":
            return {
                "supervisor_action": decision.action,
                "supervisor_workflow_id": None,
                "supervisor_arguments": {},
                "supervisor_response": decision.response,
                "pending_supervisor_question": decision.response if decision.action == "ask_user" else None,
                "supervisor_confidence": decision.confidence,
                "supervisor_rationale": decision.rationale,
            }

        workflow_id = decision.workflow_id
        is_explicit_category_create = bool(
            re.match(r"^\s*(?:please\s+)?(?:create|add|new)\b", latest_user_message, re.IGNORECASE)
            and re.search(r"\bcategor(?:y|ies)\b", latest_user_message, re.IGNORECASE)
            and self._extract_requested_new_category_name(latest_user_message)
        )
        if is_explicit_category_create or detected_intent == DetectedIntent.CATEGORY_MANAGEMENT:
            workflow_id = "category_management"
        elif detected_intent == DetectedIntent.ACCOUNT_MANAGEMENT:
            workflow_id = "account_management"
        elif detected_intent == DetectedIntent.TRANSACTION_MANAGEMENT:
            workflow_id = "transaction_management"
        elif self._should_route_to_query_transactions(
            latest_user_message=latest_user_message,
            detected_intent=detected_intent,
        ):
            workflow_id = "analytics"
        elif workflow_id in {"finish", "format_previous"} and not has_previous_result:
            workflow_id = (
                "analytics"
                if self._should_route_to_query_transactions(
                    latest_user_message=latest_user_message,
                    detected_intent=detected_intent,
                )
                else None
            )
        if workflow_id is None:
            return {
                "supervisor_action": "ask_user",
                "supervisor_workflow_id": None,
                "supervisor_arguments": {},
                "supervisor_response": decision.response
                or "I do not have a previous result to format. What finance question should I answer?",
                "pending_supervisor_question": decision.response
                or "I do not have a previous result to format. What finance question should I answer?",
                "supervisor_confidence": decision.confidence,
                "supervisor_rationale": decision.rationale,
            }
        if workflow_id not in _REGISTERED_SUPERVISOR_WORKFLOWS:
            return {
                "supervisor_action": "finish",
                "supervisor_workflow_id": None,
                "supervisor_arguments": {},
                "supervisor_response": "That workflow is not available.",
            }
        if decision.arguments:
            return {
                "supervisor_action": "finish",
                "supervisor_workflow_id": None,
                "supervisor_arguments": {},
                "supervisor_response": "I could not safely route that request. Please restate it in plain language.",
            }
        if workflow_id == "transaction" and state.get("guardrail_decision") == GuardrailDecision.BLOCK.value:
            return {"supervisor_action": "refuse", "supervisor_workflow_id": None}
        return {
            "supervisor_action": "run_workflow",
            "supervisor_workflow_id": workflow_id,
            "supervisor_arguments": {},
            "supervisor_workflow": workflow_id,
            "supervisor_response": None,
            "pending_supervisor_question": None,
            "supervisor_confidence": decision.confidence,
            "supervisor_rationale": decision.rationale,
        }

    def _supervisor_fallback_update(
        self,
        latest_user_message: str,
        detected_intent: DetectedIntent,
        state: ChatGraphState,
    ) -> dict[str, Any]:
        if state.get("workflow_result") is not None:
            return {"supervisor_action": "finish", "supervisor_response": None}

        latest_is_transaction = self._is_deterministic_transaction_candidate(latest_user_message)
        if detected_intent == DetectedIntent.OFF_TOPIC:
            workflow = "refuse"
        elif detected_intent == DetectedIntent.CATEGORY_MANAGEMENT:
            workflow = "category_management"
        elif detected_intent == DetectedIntent.ACCOUNT_MANAGEMENT:
            workflow = "account_management"
        elif detected_intent == DetectedIntent.TRANSACTION_MANAGEMENT:
            workflow = "transaction_management"
        elif (
            state.get("last_finance_query_result")
            and not latest_is_transaction
            and self._is_result_format_followup(" ".join(latest_user_message.lower().split()))
        ):
            workflow = "format_previous"
        elif (
            state.get("last_finance_query_result")
            and not latest_is_transaction
            and self._is_transaction_drilldown_followup(" ".join(latest_user_message.lower().split()))
        ):
            workflow = "analytics"
        elif self._should_route_to_query_transactions(
            latest_user_message=latest_user_message,
            detected_intent=detected_intent,
        ):
            workflow = "analytics"
        elif detected_intent == DetectedIntent.LOG_TRANSACTION:
            workflow = "transaction"
        else:
            workflow = "respond"

        unsupported_responses = {
            DetectedIntent.SPLIT_REQUEST: "Split workflows are not available in chat yet.",
            DetectedIntent.GENERATE_REPORT: "Report generation is not available in chat yet.",
            DetectedIntent.MEMORY_RELATED: "Long-term memory workflows are not available in chat yet.",
        }
        response = unsupported_responses.get(detected_intent)
        if workflow == "refuse":
            action = "refuse"
        elif workflow == "respond":
            action = "finish"
        else:
            action = "run_workflow"
        workflow_id = workflow if workflow in _REGISTERED_SUPERVISOR_WORKFLOWS else None
        return {
            "supervisor_action": action,
            "supervisor_workflow_id": workflow_id,
            "supervisor_arguments": {},
            "supervisor_workflow": workflow,
            "supervisor_confidence": 0.0,
            "supervisor_rationale": "Registered intent fallback",
            "supervisor_response": response,
            "pending_supervisor_question": None,
        }

    @staticmethod
    def _route_after_supervisor_action(state: ChatGraphState) -> str:
        return {
            "run_workflow": "workflow_dispatch",
            "ask_user": "supervisor_ask_user",
            "finish": "supervisor_finish",
            "refuse": "assistant_refusal",
        }.get(str(state.get("supervisor_action") or ""), "supervisor_finish")

    async def _workflow_dispatch_node(self, state: ChatGraphState) -> dict[str, Any]:
        if state.get("guardrail_decision") == GuardrailDecision.BLOCK.value:
            return {
                "supervisor_action": "refuse",
                "supervisor_response": None,
                "workflow_action": "refusal",
            }
        workflow_id = state.get("supervisor_workflow_id")
        arguments = state.get("supervisor_arguments") or {}
        if workflow_id not in _REGISTERED_SUPERVISOR_WORKFLOWS:
            return {
                "supervisor_action": "finish",
                "supervisor_response": "I could not route that to a registered workflow.",
                "workflow_action": "default",
            }
        if arguments:
            return {
                "supervisor_action": "finish",
                "supervisor_response": "That workflow received unsupported arguments and was not run.",
                "workflow_action": "default",
            }

        workflow_key = json.dumps([workflow_id, arguments], sort_keys=True, separators=(",", ":"))
        executed_workflows = list(state.get("supervisor_executed_workflows") or [])
        handoff_count = int(state.get("supervisor_handoff_count") or 0)
        if handoff_count >= _MAX_SUPERVISOR_HANDOFFS:
            return {
                "supervisor_action": "finish",
                "supervisor_response": (
                    "I reached the safe workflow limit for this turn. Please tell me what to do next."
                ),
                "workflow_action": "default",
            }
        if workflow_key in executed_workflows:
            return {
                "supervisor_action": "finish",
                "supervisor_response": "I stopped to avoid repeating the same workflow without progress.",
                "workflow_action": "default",
            }

        workflow_action = {
            "transaction": "build_proposal",
            "analytics": "query_transactions",
            "account_management": "account_management",
            "category_management": "category_management",
            "transaction_management": "transaction_management",
            "format_previous": "query_transactions",
        }[workflow_id]
        return {
            "active_workflow_id": workflow_id,
            "active_workflow_start_query_generation": int(state.get("finance_query_generation") or 0),
            "workflow_action": workflow_action,
            "supervisor_handoff_count": handoff_count + 1,
            "supervisor_executed_workflows": [*executed_workflows, workflow_key],
            "workflow_result": None,
            "supervisor_response": None,
        }

    @staticmethod
    def _route_after_workflow_dispatch(state: ChatGraphState) -> str:
        if state.get("supervisor_action") == "refuse":
            return "assistant_refusal"
        if state.get("supervisor_action") == "finish":
            return "supervisor_finish"
        action = state.get("workflow_action")
        if action == "build_proposal":
            return "populate_user_context"
        if action == "account_management":
            return "account_management"
        if action == "category_management":
            return "category_management"
        if action == "transaction_management":
            return "transaction_management"
        if action == "query_transactions":
            return "query_tool_agent"
        if action == "refusal":
            return "assistant_refusal"
        return "assistant_default"

    @staticmethod
    def _route_after_specialist(state: ChatGraphState) -> str:
        if state.get("active_workflow_id") and int(state.get("supervisor_handoff_count") or 0) > 0:
            return "workflow_observer"
        return END

    @staticmethod
    def _route_after_assistant_default(state: ChatGraphState) -> str:
        if state.get("active_workflow_id") and int(state.get("supervisor_handoff_count") or 0) > 0:
            return "workflow_observer"
        return END

    async def _workflow_observer_node(self, state: ChatGraphState) -> dict[str, Any]:
        workflow_id = state.get("active_workflow_id")
        if workflow_id not in _REGISTERED_SUPERVISOR_WORKFLOWS:
            return {"workflow_result": None}

        messages = state.get("messages", [])
        latest_user_index = max(
            (index for index, message in enumerate(messages) if isinstance(message, HumanMessage)),
            default=-1,
        )
        latest_ai_message = next(
            (
                str(message.content)
                for message in reversed(messages[latest_user_index + 1 :])
                if isinstance(message, AIMessage) and isinstance(message.content, str) and message.content.strip()
            ),
            "",
        )
        status: Literal["success", "needs_input", "failed"] = "failed"
        result_ref: Literal[
            "finance_result",
            "management_request",
            "transaction_proposal",
            "mutation_proposal",
            "none",
        ] = "none"
        side_effect: Literal["none", "proposed", "committed"] = "none"

        if workflow_id == "analytics":
            query_completed = int(state.get("finance_query_generation") or 0) > int(
                state.get("active_workflow_start_query_generation") or 0
            )
            status = "success" if query_completed else "needs_input" if latest_ai_message else "failed"
            result_ref = "finance_result" if query_completed else "none"
        elif workflow_id == "format_previous":
            has_transactions = bool((state.get("last_finance_query_result") or {}).get("transactions"))
            status = "success" if has_transactions else "needs_input"
            result_ref = "finance_result" if has_transactions else "none"
        elif workflow_id in {"account_management", "category_management", "transaction_management"}:
            pending_by_workflow = {
                "account_management": state.get("pending_account_request"),
                "category_management": state.get("pending_category_request"),
                "transaction_management": state.get("pending_transaction_management_request"),
            }
            pending = pending_by_workflow[workflow_id]
            status = "needs_input" if pending else "success" if latest_ai_message else "failed"
            result_ref = "management_request" if pending else "none"
            if state.get("pending_mutation"):
                status = "needs_input"
                result_ref = "mutation_proposal"
                side_effect = "proposed"
            elif state.get("mutation_committed"):
                side_effect = "committed"
        elif workflow_id == "transaction":
            if (
                state.get("pending_proposal")
                or state.get("hitl_active")
                or state.get("manual_transaction_input_required")
            ):
                status = "needs_input"
                result_ref = "transaction_proposal"
                side_effect = "proposed" if state.get("pending_proposal") else "none"
            elif state.get("transaction_logged"):
                status = "success"
                side_effect = "committed"

        summary = latest_ai_message[:600]
        if workflow_id == "analytics" and status == "success":
            facts = state.get("last_finance_query_result") or {}
            plan = state.get("last_finance_query_plan") or {}
            summary = (
                f"Analytics succeeded: {facts.get('query_kind', 'finance query')}; "
                f"{facts.get('transaction_count', 0)} matching transactions; "
                f"date range {facts.get('date_from') or plan.get('date_period') or 'unspecified'} to "
                f"{facts.get('date_to') or 'unspecified'}."
            )
        elif workflow_id == "format_previous" and status == "success":
            summary = "Formatted the saved transaction rows according to the current request."
        elif workflow_id == "transaction" and status == "needs_input":
            summary = "A transaction proposal is waiting for explicit user confirmation."
        result = WorkflowResult(
            workflow_id=workflow_id,
            status=status,
            summary=summary,
            result_ref=result_ref,
            side_effect=side_effect,
        )
        return {"workflow_result": result.model_dump()}

    @staticmethod
    def _route_after_workflow_observation(state: ChatGraphState) -> str:
        result = state.get("workflow_result") or {}
        active_workflow_id = state.get("active_workflow_id")
        handoff_count = int(state.get("supervisor_handoff_count") or 0)
        can_continue = (
            result.get("status") == "success"
            and active_workflow_id in {"analytics", "format_previous"}
            and handoff_count < _MAX_SUPERVISOR_HANDOFFS
        )
        return "supervisor" if can_continue else "supervisor_finish"

    async def _supervisor_ask_user_node(self, state: ChatGraphState) -> dict[str, Any]:
        question = str(state.get("supervisor_response") or "Could you clarify what you would like me to do?")
        interrupt({"question": question})
        return {"supervisor_response": None, "supervisor_action": None}

    async def _supervisor_finish_node(self, state: ChatGraphState) -> dict[str, Any]:
        response = str(state.get("supervisor_response") or "").strip()
        if response and state.get("workflow_result") is None:
            return {"messages": [AIMessage(content=response)]}
        messages = state.get("messages", [])
        latest_user_index = max(
            (index for index, message in enumerate(messages) if isinstance(message, HumanMessage)),
            default=-1,
        )
        has_current_reply = any(
            isinstance(message, AIMessage) and str(message.content or "").strip()
            for message in messages[latest_user_index + 1 :]
        )
        if state.get("workflow_result") is None and not has_current_reply:
            return await self._assistant_default(state)
        return {}

    @staticmethod
    def _supervisor_conversation_context(messages: list[BaseMessage]) -> str:
        selected: list[str] = []
        for message in messages:
            if not isinstance(message, (HumanMessage, AIMessage)) or not isinstance(message.content, str):
                continue
            text = " ".join(message.content.split())
            if not text:
                continue
            if isinstance(message, AIMessage) and ("| ---" in text or "|---" in text):
                text = "[Prior structured analytics result; see the bounded workflow result.]"
            selected.append(f"{'User' if isinstance(message, HumanMessage) else 'Assistant'}: {text[:240]}")
        return "\n".join(selected[-6:])

    async def _account_management_node(self, state: ChatGraphState) -> dict[str, Any]:
        message = self._latest_user_message(state.get("messages", []))
        if not message:
            return {"messages": [AIMessage(content="What account change would you like to make?")]}

        user_id = self._user_id_from_state(state)
        accounts = await self._list_user_accounts_for_state(user_id)
        pending = state.get("pending_account_request") or {}
        request: AccountManagementRequest | None = None
        chain = getattr(self, "_llm_account_management_chain", None)
        if chain is not None:
            try:
                request = await chain.ainvoke(
                    {
                        "message": message,
                        "pending_request": json.dumps(pending, ensure_ascii=False) if pending else "None",
                        "accounts_catalog": json.dumps(accounts, ensure_ascii=False),
                    }
                )
            except Exception:
                logger.exception("Account management parsing failed; using deterministic fallback.")
        if request is None or request.confidence < 0.55:
            request = self._fallback_account_management_request(message, pending)

        operation = str(pending.get("operation") or request.operation)
        account_name = self._sanitize_category(str(pending.get("account_name") or request.account_name or ""))
        new_name = self._sanitize_category(str(pending.get("new_name") or request.new_name or ""))
        account_type = str(pending.get("account_type") or request.account_type or "").lower() or None
        opening_balance = request.opening_balance
        if opening_balance is None and pending.get("opening_balance") is not None:
            opening_balance = Decimal(str(pending["opening_balance"]))
        currency = str(pending.get("currency") or request.currency or "INR").upper()

        if operation == "create":
            if not account_name:
                return {
                    "messages": [AIMessage(content="What should the new account be called?")],
                    "pending_account_request": {"operation": "create", "account_type": account_type},
                }
            if account_type not in {item.value for item in AccountType}:
                normalized_reply = self._normalize_lookup_text(message)
                account_type = next(
                    (item.value for item in AccountType if re.search(rf"\b{item.value}\b", normalized_reply)),
                    None,
                )
            if account_type is None:
                return {
                    "messages": [AIMessage(content=f"Is '{account_name}' a cash, bank, card, or wallet account?")],
                    "pending_account_request": {"operation": "create", "account_name": account_name},
                }
            if self._find_exact_named_item(accounts, account_name) is not None:
                return {
                    "messages": [AIMessage(content=f"An account named '{account_name}' already exists.")],
                    "pending_account_request": None,
                }
            balance_paise = self._to_paise(opening_balance or Decimal("0"))
            if balance_paise is None:
                return {
                    "messages": [AIMessage(content="What is the opening balance for this account?")],
                    "pending_account_request": {
                        "operation": "create",
                        "account_name": account_name,
                        "account_type": account_type,
                    },
                }
            proposal = self._build_mutation_proposal(
                entity="account",
                operation="create",
                target_id=None,
                payload={
                    "name": account_name,
                    "type": account_type,
                    "balance_paise": balance_paise,
                    "currency": currency,
                },
                summary=(
                    f"Create {account_type} account '{account_name}' with an opening balance of "
                    f"{currency} {balance_paise / 100:.2f}?"
                ),
            )
            return self._proposal_update(proposal, pending_field="pending_account_request")

        target = self._find_exact_named_item(accounts, account_name)
        if target is None:
            names = ", ".join(str(item["name"]) for item in accounts if item.get("is_active")) or "none"
            return {
                "messages": [AIMessage(content=f"Which account do you mean? Active accounts: {names}.")],
                "pending_account_request": {"operation": operation, "new_name": new_name},
            }

        if operation == "rename":
            if not new_name:
                return {
                    "messages": [AIMessage(content=f"What should I rename '{target['name']}' to?")],
                    "pending_account_request": {"operation": "rename", "account_name": target["name"]},
                }
            duplicate = self._find_exact_named_item(accounts, new_name)
            if duplicate is not None and duplicate["id"] != target["id"]:
                return {
                    "messages": [AIMessage(content=f"An account named '{new_name}' already exists.")],
                    "pending_account_request": None,
                }
            updated = await self._account_service.update_account(
                user_id, uuid.UUID(str(target["id"])), UpdateAccountInput(name=new_name)
            )
            return {
                "messages": [AIMessage(content=f"Renamed account '{target['name']}' to '{updated.name}'.")],
                "pending_account_request": None,
                "user_accounts": await self._list_user_accounts_for_state(user_id),
                "mutation_committed": True,
            }

        if operation == "set_default":
            updated = await self._account_service.set_default_account(user_id, uuid.UUID(str(target["id"])))
            return {
                "messages": [AIMessage(content=f"'{updated.name}' is now your default account.")],
                "pending_account_request": None,
                "user_accounts": await self._list_user_accounts_for_state(user_id),
                "mutation_committed": True,
            }

        if operation == "activate":
            updated = await self._account_service.update_account(
                user_id, uuid.UUID(str(target["id"])), UpdateAccountInput(is_active=True)
            )
            return {
                "messages": [AIMessage(content=f"Activated account '{updated.name}'.")],
                "pending_account_request": None,
                "user_accounts": await self._list_user_accounts_for_state(user_id),
                "mutation_committed": True,
            }

        if operation == "deactivate":
            proposal = self._build_mutation_proposal(
                entity="account",
                operation="deactivate",
                target_id=str(target["id"]),
                payload={},
                summary=f"Deactivate account '{target['name']}'? Existing transactions will remain available.",
            )
            return self._proposal_update(proposal, pending_field="pending_account_request")

        return {
            "messages": [AIMessage(content="I can create, rename, activate, deactivate, or set a default account.")],
            "pending_account_request": None,
        }

    @classmethod
    def _fallback_account_management_request(cls, message: str, pending: dict[str, Any]) -> AccountManagementRequest:
        text = " ".join(message.strip().split())
        normalized = text.lower()
        operation = str(pending.get("operation") or "clarify")
        if re.search(r"\b(?:create|add|new)\b", normalized):
            operation = "create"
        elif re.search(r"\brename\b", normalized):
            operation = "rename"
        elif re.search(r"\b(?:set|make).+\bdefault\b", normalized):
            operation = "set_default"
        elif re.search(r"\b(?:reactivate|activate)\b", normalized):
            operation = "activate"
        elif re.search(r"\b(?:deactivate|disable|close)\b", normalized):
            operation = "deactivate"

        account_type = next((item.value for item in AccountType if re.search(rf"\b{item.value}\b", normalized)), None)
        account_name = None
        new_name = None
        rename_match = re.search(r"\brename\s+(?:account\s+)?['\"]?(.+?)['\"]?\s+to\s+['\"]?(.+?)['\"]?$", text, re.I)
        if rename_match:
            account_name, new_name = rename_match.group(1), rename_match.group(2)
        else:
            create_match = re.search(
                r"\b(?:create|add)\s+(?:an?\s+|new\s+)?(?:(?:cash|bank|card|wallet)\s+)?account"
                r"(?:\s+(?:called|named))?\s+['\"]?(.+?)['\"]?(?:\s+with\s+(?:an?\s+)?(?:opening\s+)?balance\b|$)",
                text,
                re.I,
            )
            target_match = re.search(
                r"\b(?:deactivate|disable|close|activate|reactivate)\s+(?:account\s+)?['\"]?(.+?)['\"]?$",
                text,
                re.I,
            )
            default_match = re.search(
                r"\b(?:set|make)\s+['\"]?(.+?)['\"]?\s+(?:as\s+)?(?:my\s+)?default(?:\s+account)?$",
                text,
                re.I,
            )
            match = create_match or target_match or default_match
            if match:
                account_name = match.group(1)

        amount_paise = cls._extract_amount_paise(text)
        opening_balance = Decimal(amount_paise) / Decimal(100) if amount_paise is not None else None
        return AccountManagementRequest(
            operation=operation,
            account_name=cls._sanitize_category(account_name),
            new_name=cls._sanitize_category(new_name),
            account_type=account_type,
            opening_balance=opening_balance,
            currency="INR",
            confidence=0.75 if operation != "clarify" else 0.0,
        )

    @staticmethod
    def _build_mutation_proposal(
        *, entity: str, operation: str, target_id: str | None, payload: dict[str, Any], summary: str
    ) -> dict[str, Any]:
        return {
            "id": uuid.uuid4().hex,
            "entity": entity,
            "operation": operation,
            "target_id": target_id,
            "payload": payload,
            "summary": summary,
            "created_at": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _proposal_update(proposal: dict[str, Any], *, pending_field: str) -> dict[str, Any]:
        return {
            "messages": [AIMessage(content=f"{proposal['summary']} Reply 'confirm' to proceed or 'cancel' to stop.")],
            "pending_mutation": proposal,
            pending_field: None,
        }

    @staticmethod
    def _find_exact_named_item(items: list[dict[str, Any]], name: str | None) -> dict[str, Any] | None:
        if not name:
            return None
        normalized = LangGraphChatOrchestrator._normalize_lookup_text(name)
        matches = [
            item
            for item in items
            if LangGraphChatOrchestrator._normalize_lookup_text(str(item.get("name") or "")) == normalized
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _mutation_confirmation_action(message: str) -> str:
        normalized = LangGraphChatOrchestrator._normalize_lookup_text(message)
        if normalized in {"confirm", "confirmed", "yes", "yes proceed", "proceed", "do it"}:
            return "confirm_mutation"
        if normalized in {"cancel", "no", "stop", "never mind", "nevermind"}:
            return "cancel_mutation"
        return "mutation_wait"

    async def _mutation_confirmation_node(self, state: ChatGraphState) -> dict[str, Any]:
        proposal = state.get("pending_mutation")
        if proposal is None:
            return {"messages": [AIMessage(content="There is no pending change to confirm.")]}
        action = state.get("workflow_action")
        if action == "cancel_mutation":
            return {
                "messages": [AIMessage(content="Okay, I cancelled that change.")],
                "pending_mutation": None,
            }
        if action != "confirm_mutation":
            return {
                "messages": [
                    AIMessage(content=f"{proposal['summary']} Reply 'confirm' to proceed or 'cancel' to stop.")
                ]
            }

        user_id = self._user_id_from_state(state)
        entity = str(proposal.get("entity"))
        operation = str(proposal.get("operation"))
        target_id = uuid.UUID(str(proposal["target_id"])) if proposal.get("target_id") else None
        payload = dict(proposal.get("payload") or {})
        try:
            message = await self._execute_mutation(
                user_id=user_id,
                entity=entity,
                operation=operation,
                target_id=target_id,
                payload=payload,
            )
        except Exception:
            logger.exception("Confirmed chat mutation failed.")
            return {
                "messages": [AIMessage(content="I could not apply that change safely. Nothing else was attempted.")],
                "pending_mutation": None,
                "mutation_committed": False,
            }
        return {
            "messages": [AIMessage(content=message)],
            "pending_mutation": None,
            "mutation_committed": True,
            "user_accounts": await self._list_user_accounts_for_state(user_id),
            "user_categories": await self._list_user_categories_for_state(user_id),
        }

    async def _execute_mutation(
        self,
        *,
        user_id: uuid.UUID,
        entity: str,
        operation: str,
        target_id: uuid.UUID | None,
        payload: dict[str, Any],
    ) -> str:
        if entity == "account" and operation == "create":
            existing = await self._account_service.list_accounts(user_id)
            requested_name = str(payload["name"])
            if any(
                self._normalize_lookup_text(account.name) == self._normalize_lookup_text(requested_name)
                for account in existing
            ):
                return f"An account named '{requested_name}' already exists; I did not create another one."
            account = await self._account_service.create_account(
                CreateAccountInput(
                    user_id=user_id,
                    name=requested_name,
                    type=AccountType(str(payload["type"])),
                    balance_paise=int(payload["balance_paise"]),
                    currency=str(payload["currency"]),
                )
            )
            return f"Created {account.type.value} account '{account.name}'."
        if entity == "account" and operation == "deactivate" and target_id is not None:
            account = await self._account_service.update_account(
                user_id, target_id, UpdateAccountInput(is_active=False)
            )
            return f"Deactivated account '{account.name}'."
        if entity == "category" and operation == "delete" and target_id is not None:
            category = await self._category_repository.get_for_user(target_id, user_id)
            if category is None:
                return "That category no longer exists."
            await self._category_service.delete_category(user_id, target_id)
            return f"Deleted category '{category.name}'. Existing transactions keep their amounts and history."
        if entity == "transaction" and target_id is not None:
            if operation == "delete":
                transaction = await self._transaction_service.get_transaction(user_id, target_id)
                await self._transaction_service.soft_delete_transaction(user_id, target_id)
                return f"Deleted the transaction for INR {transaction.amount_paise / 100:.2f}."
            if operation == "restore":
                await self._transaction_service.restore_transaction(user_id, target_id)
                return "Restored the transaction and reapplied its balance effect."
            if operation == "edit":
                transaction = await self._transaction_service.update_transaction(
                    user_id,
                    target_id,
                    UpdateTransactionInput(
                        account_id=uuid.UUID(payload["account_id"]) if payload.get("account_id") else None,
                        type=TransactionType(payload["type"]) if payload.get("type") else None,
                        amount_paise=int(payload["amount_paise"]) if payload.get("amount_paise") is not None else None,
                        occurred_at=datetime.fromisoformat(payload["occurred_at"])
                        if payload.get("occurred_at")
                        else None,
                        category_id=uuid.UUID(payload["category_id"]) if payload.get("category_id") else None,
                        merchant=payload.get("merchant"),
                        note=payload.get("note"),
                    ),
                )
                return f"Updated the transaction. Its amount is now INR {transaction.amount_paise / 100:.2f}."
        raise ValueError(f"Unsupported mutation: {entity}.{operation}")

    async def _category_management_node(self, state: ChatGraphState) -> dict[str, Any]:
        latest_user_message = self._latest_user_message(state.get("messages", []))
        if not latest_user_message:
            return {"messages": [AIMessage(content="What category would you like to create?")]}

        pending_request = state.get("pending_category_request")
        explicit_new_category_name = self._extract_requested_new_category_name(latest_user_message)
        if explicit_new_category_name is not None:
            pending_request = None
        request: CategoryManagementRequest | None = None
        category_chain = getattr(self, "_llm_category_management_chain", None)
        if category_chain is not None:
            try:
                request = await category_chain.ainvoke(
                    {
                        "message": latest_user_message,
                        "pending_request": json.dumps(pending_request, ensure_ascii=False)
                        if pending_request
                        else "None",
                    }
                )
            except Exception:
                logger.exception("Category request parsing failed; using explicit category wording fallback.")

        operation = str(pending_request.get("operation") if pending_request else "") or (
            request.operation if request is not None else "clarify"
        )
        if re.search(r"\brename\b", latest_user_message, re.IGNORECASE):
            operation = "rename"
        elif re.search(r"\b(?:delete|remove)\b", latest_user_message, re.IGNORECASE):
            operation = "delete"
        elif explicit_new_category_name is not None:
            operation = "create"

        pending_name = self._sanitize_category(str(pending_request.get("name") or "")) if pending_request else None
        requested_name = pending_name or self._sanitize_category(
            getattr(request, "category_name", None) if request is not None else None
        )
        if requested_name is None:
            requested_name = explicit_new_category_name
        if requested_name is None and pending_request and not pending_request.get("name"):
            requested_name = self._sanitize_category(latest_user_message)
        if requested_name is not None:
            requested_name = requested_name.strip().strip("'\"`“”‘’")
            requested_name = self._sanitize_category(requested_name)

        new_name = self._sanitize_category(
            str((pending_request or {}).get("new_name") or getattr(request, "new_name", None) or "")
        )
        if operation == "rename" and (requested_name is None or new_name is None):
            rename_match = re.search(
                r"\brename\s+(?:the\s+)?(?:category\s+)?['\"]?(.+?)['\"]?\s+to\s+['\"]?(.+?)['\"]?$",
                latest_user_message,
                re.IGNORECASE,
            )
            if rename_match:
                requested_name = self._sanitize_category(rename_match.group(1))
                new_name = self._sanitize_category(rename_match.group(2))
        if operation == "delete" and requested_name is None:
            delete_match = re.search(
                r"\b(?:delete|remove)\s+(?:the\s+)?(?:category\s+)?['\"]?(.+?)['\"]?$",
                latest_user_message,
                re.IGNORECASE,
            )
            if delete_match:
                requested_name = self._sanitize_category(delete_match.group(1))

        if operation in {"rename", "delete"}:
            user_id = self._user_id_from_state(state)
            categories = self._normalize_state_categories(state.get("user_categories"))
            if not categories:
                categories = await self._list_user_categories_for_state(user_id)
            target = self._find_exact_named_item(categories, requested_name)
            if target is None:
                names = ", ".join(str(item["name"]) for item in categories) or "none"
                return {
                    "messages": [AIMessage(content=f"Which category do you mean? Categories: {names}.")],
                    "pending_category_request": {"operation": operation, "new_name": new_name},
                }
            if operation == "rename":
                if not new_name:
                    return {
                        "messages": [AIMessage(content=f"What should I rename '{target['name']}' to?")],
                        "pending_category_request": {"operation": "rename", "name": target["name"]},
                    }
                duplicate = self._find_exact_named_item(categories, new_name)
                if duplicate is not None and duplicate["id"] != target["id"]:
                    return {
                        "messages": [AIMessage(content=f"A category named '{new_name}' already exists.")],
                        "pending_category_request": None,
                    }
                updated = await self._category_service.update_category(
                    user_id,
                    uuid.UUID(str(target["id"])),
                    UpdateCategoryInput(name=new_name),
                )
                return {
                    "messages": [AIMessage(content=f"Renamed category '{target['name']}' to '{updated.name}'.")],
                    "pending_category_request": None,
                    "user_categories": await self._list_user_categories_for_state(user_id),
                    "mutation_committed": True,
                }
            proposal = self._build_mutation_proposal(
                entity="category",
                operation="delete",
                target_id=str(target["id"]),
                payload={},
                summary=(
                    f"Delete category '{target['name']}'? Existing transactions will retain their history but "
                    "will no longer reference this category."
                ),
            )
            return self._proposal_update(proposal, pending_field="pending_category_request")

        if operation != "create":
            return {
                "messages": [AIMessage(content="Would you like to create, rename, or delete a category?")],
                "pending_category_request": {"operation": "clarify"},
            }

        category_type = getattr(request, "category_type", None) if request is not None else None
        if category_type is None:
            category_type = self._infer_category_type(latest_user_message, requested_name)
        if category_type is None and pending_request:
            type_reply = self._normalize_lookup_text(latest_user_message)
            if re.search(r"\b(?:expense|expenses|spending|cost)\b", type_reply):
                category_type = CategoryType.EXPENSE.value
            elif re.search(r"\b(?:income|earning|earnings|salary)\b", type_reply):
                category_type = CategoryType.INCOME.value

        if requested_name is None:
            return {
                "messages": [AIMessage(content="What should the new category be called?")],
                "pending_category_request": {"operation": "create"},
            }
        if category_type is None:
            return {
                "messages": [AIMessage(content=f"Should '{requested_name}' be an expense or income category?")],
                "pending_category_request": {"operation": "create", "name": requested_name},
            }

        user_id = self._user_id_from_state(state)
        categories = self._normalize_state_categories(state.get("user_categories"))
        if not categories:
            categories = await self._list_user_categories_for_state(user_id)
        normalized_name = self._normalize_lookup_text(requested_name)
        same_name_categories = [
            category
            for category in categories
            if self._normalize_lookup_text(str(category.get("name") or "")) == normalized_name
        ]
        existing_match = next(
            (category for category in same_name_categories if category.get("type") == category_type),
            None,
        )
        if existing_match is not None:
            return {
                "messages": [
                    AIMessage(content=f"The {category_type} category '{existing_match['name']}' already exists.")
                ],
                "pending_category_request": None,
            }
        if same_name_categories:
            existing_type = str(same_name_categories[0].get("type") or "unknown")
            return {
                "messages": [
                    AIMessage(
                        content=(
                            f"A category named '{requested_name}' already exists as {existing_type}. "
                            "Choose a different name or category type."
                        )
                    )
                ],
                "pending_category_request": None,
            }

        created_category = await self._create_category_with_tool(
            user_id=user_id,
            category_name=requested_name,
            category_type=CategoryType(category_type),
            existing_categories=categories,
        )
        if created_category is None:
            return {
                "messages": [
                    AIMessage(
                        content=(
                            f"I couldn't create the {category_type} category '{requested_name}'. Please try again."
                        )
                    )
                ],
                "pending_category_request": None,
            }

        return {
            "messages": [AIMessage(content=f"Created the {category_type} category '{created_category['name']}'.")],
            "pending_category_request": None,
            "user_categories": [*categories, created_category],
        }

    async def _transaction_management_node(self, state: ChatGraphState) -> dict[str, Any]:
        message = self._latest_user_message(state.get("messages", []))
        if not message:
            return {"messages": [AIMessage(content="Which transaction would you like to change?")]}

        user_id = self._user_id_from_state(state)
        pending = state.get("pending_transaction_management_request") or {}
        normalized = self._normalize_lookup_text(message)
        operation = str(pending.get("operation") or "")
        if re.search(r"\b(?:delete|remove)\b", normalized):
            operation = "delete"
        elif re.search(r"\brestore\b", normalized):
            operation = "restore"
        elif re.search(r"\b(?:edit|update|change|modify)\b", normalized):
            operation = "edit"

        include_deleted = operation == "restore"
        transactions = await self._transaction_service.transaction_repository.list_for_user(
            user_id, include_deleted=include_deleted
        )
        accounts = await self._list_user_accounts_for_state(user_id)
        categories = await self._list_user_categories_for_state(user_id)
        catalog = [
            {
                "id": str(transaction.id),
                "type": transaction.type.value,
                "amount_paise": transaction.amount_paise,
                "occurred_at": transaction.occurred_at.isoformat(),
                "merchant": transaction.merchant,
                "note": transaction.note,
                "account_id": str(transaction.account_id),
                "category_id": str(transaction.category_id) if transaction.category_id else None,
                "deleted": transaction.deleted_at is not None,
            }
            for transaction in transactions[:20]
            if (transaction.deleted_at is not None) == include_deleted
        ]

        request: TransactionManagementRequest | None = None
        chain = getattr(self, "_llm_transaction_management_chain", None)
        if chain is not None:
            try:
                request = await chain.ainvoke(
                    {
                        "message": message,
                        "pending_request": json.dumps(pending, ensure_ascii=False) if pending else "None",
                        "transactions_catalog": json.dumps(catalog, ensure_ascii=False),
                        "accounts_catalog": json.dumps(accounts, ensure_ascii=False),
                        "categories_catalog": json.dumps(categories, ensure_ascii=False),
                    }
                )
            except Exception:
                logger.exception("Transaction management parsing failed; using deterministic fallback.")

        if request is not None and request.operation != "clarify":
            operation = str(pending.get("operation") or request.operation)
        if operation not in {"edit", "delete", "restore"}:
            return {
                "messages": [AIMessage(content="Would you like to edit, delete, or restore a transaction?")],
                "pending_transaction_management_request": {"operation": "clarify"},
            }

        target_id = str(pending.get("selected_transaction_id") or "") or (
            str(request.selected_transaction_id or "") if request is not None else ""
        )
        owned_ids = {item["id"] for item in catalog}
        target = next((item for item in catalog if item["id"] == target_id), None)
        if target is None:
            uuid_match = re.search(
                r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
                message,
                re.IGNORECASE,
            )
            if uuid_match and uuid_match.group(0) in owned_ids:
                target = next(item for item in catalog if item["id"] == uuid_match.group(0))
            elif re.search(r"\b(?:latest|last|most recent)\s+transaction\b", normalized) and catalog:
                target = catalog[0]
            else:
                amount_paise = self._extract_amount_paise(message)
                amount_matches = [item for item in catalog if item["amount_paise"] == amount_paise]
                if len(amount_matches) == 1:
                    target = amount_matches[0]

        if target is None:
            options = "; ".join(self._format_transaction_catalog_item(item) for item in catalog[:5])
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "Which transaction do you mean? "
                            + (f"Recent matches: {options}." if options else "No matching transactions were found.")
                        )
                    )
                ],
                "pending_transaction_management_request": {"operation": operation},
            }

        if operation in {"delete", "restore"}:
            verb = "Restore" if operation == "restore" else "Delete"
            proposal = self._build_mutation_proposal(
                entity="transaction",
                operation=operation,
                target_id=target["id"],
                payload={},
                summary=f"{verb} {self._format_transaction_catalog_item(target)}?",
            )
            return self._proposal_update(proposal, pending_field="pending_transaction_management_request")

        if request is None:
            amount_paise = self._extract_amount_paise(message)
            request = TransactionManagementRequest(
                operation="edit",
                amount=Decimal(amount_paise) / Decimal(100) if amount_paise is not None else None,
                confidence=0.7 if amount_paise is not None else 0.0,
            )

        payload: dict[str, Any] = {}
        if request is not None:
            amount_paise = self._to_paise(request.amount) if request.amount is not None else None
            if amount_paise is not None:
                payload["amount_paise"] = amount_paise
            if request.transaction_type is not None:
                payload["type"] = request.transaction_type
            if request.occurred_at is not None:
                occurred_at = request.occurred_at
                if occurred_at.tzinfo is None:
                    occurred_at = occurred_at.replace(tzinfo=UTC)
                payload["occurred_at"] = occurred_at.isoformat()
            if request.merchant is not None:
                payload["merchant"] = self._sanitize_merchant(request.merchant)
            if request.note is not None:
                payload["note"] = self._sanitize_note(request.note)
            if request.account_name:
                account = self._find_exact_named_item(accounts, request.account_name)
                if account is None or not account.get("is_active"):
                    return {
                        "messages": [
                            AIMessage(content=f"I could not find one active account named '{request.account_name}'.")
                        ],
                        "pending_transaction_management_request": None,
                    }
                payload["account_id"] = account["id"]
            if request.category_name:
                category = self._find_exact_named_item(categories, request.category_name)
                if category is None:
                    return {
                        "messages": [
                            AIMessage(content=f"I could not find one category named '{request.category_name}'.")
                        ],
                        "pending_transaction_management_request": None,
                    }
                payload["category_id"] = category["id"]
                payload.setdefault("type", category["type"])

        if not payload:
            return {
                "messages": [AIMessage(content="What should I change about that transaction?")],
                "pending_transaction_management_request": {
                    "operation": "edit",
                    "selected_transaction_id": target["id"],
                },
            }
        changes = ", ".join(f"{key}={value}" for key, value in payload.items())
        proposal = self._build_mutation_proposal(
            entity="transaction",
            operation="edit",
            target_id=target["id"],
            payload=payload,
            summary=f"Update {self._format_transaction_catalog_item(target)} with {changes}?",
        )
        return self._proposal_update(proposal, pending_field="pending_transaction_management_request")

    @staticmethod
    def _format_transaction_catalog_item(item: dict[str, Any]) -> str:
        date_text = str(item.get("occurred_at") or "")[:10]
        merchant = str(item.get("merchant") or item.get("note") or item.get("type") or "transaction")
        amount = int(item.get("amount_paise") or 0) / 100
        return f"{date_text} {merchant} for INR {amount:.2f}"

    @classmethod
    def _infer_category_type(cls, message: str, category_name: str | None) -> str | None:
        normalized_message = cls._normalize_lookup_text(message)
        normalized_name = cls._normalize_lookup_text(category_name or "")
        if re.search(r"\b(?:income|earning|earnings|salary)\s+categor(?:y|ies)\b", normalized_message):
            return CategoryType.INCOME.value
        if re.search(r"\bexpense\s+categor(?:y|ies)\b", normalized_message):
            return CategoryType.EXPENSE.value
        if normalized_name.endswith(" income") or normalized_name == "income":
            return CategoryType.INCOME.value
        if normalized_name.endswith(" expense") or normalized_name == "expense":
            return CategoryType.EXPENSE.value
        return None

    async def _populate_user_context(self, state: ChatGraphState) -> dict[str, Any]:
        if state.get("workflow_action") != "build_proposal":
            return {}

        user_id = self._user_id_from_state(state)
        accounts = await self._list_user_accounts_for_state(user_id)
        categories = await self._list_user_categories_for_state(user_id)
        return {
            "user_accounts": accounts,
            "user_categories": categories,
        }

    async def _extract_transaction_candidate_node(self, state: ChatGraphState) -> dict[str, Any]:
        if state.get("workflow_action") != "build_proposal":
            return {"extracted_candidate": None}

        latest_user_message = self._latest_user_message(state.get("messages", []))
        if not latest_user_message:
            return {"extracted_candidate": None}

        accounts = self._normalize_state_accounts(state.get("user_accounts"))
        categories = self._normalize_state_categories(state.get("user_categories"))
        row_count = self._count_transaction_rows(latest_user_message)
        if row_count > 10:
            return {
                "extracted_candidate": None,
                "extracted_candidates": [],
                "batch_extraction_error": "I can review at most 10 transaction rows at a time. Nothing was created.",
            }
        if row_count >= 2:
            candidates, error = await self._extract_transaction_batch(
                latest_user_message,
                expected_count=row_count,
                accounts=accounts,
                categories=categories,
            )
            return {
                "extracted_candidate": None,
                "extracted_candidates": candidates,
                "batch_extraction_error": error,
            }

        context_message = state.get("hitl_context_message") if state.get("hitl_active") else None
        extraction_message = self._merge_hitl_context(context_message, latest_user_message)
        candidate = await self._extract_candidate(
            extraction_message,
            accounts=accounts,
            categories=categories,
        )

        return {
            "extracted_candidate": candidate,
            "hitl_context_message": extraction_message if state.get("hitl_active") else context_message,
        }

    async def _evaluate_transaction_candidate(self, state: ChatGraphState) -> dict[str, Any]:
        if state.get("workflow_action") != "build_proposal":
            return {"workflow_action": "default"}

        batch_error = state.get("batch_extraction_error")
        batch_candidates = state.get("extracted_candidates")
        if batch_error:
            return {
                "workflow_action": "batch_proposals_ready",
                "pending_proposals_queue": [],
                "batch_extraction_error": batch_error,
            }
        if batch_candidates:
            proposals, error = await self._build_transaction_batch_proposals(
                candidates=batch_candidates,
                latest_user_message=self._latest_user_message(state.get("messages", [])),
                user_accounts=self._normalize_state_accounts(state.get("user_accounts")),
                user_categories=self._normalize_state_categories(state.get("user_categories")),
                timezone_name=str(state.get("runtime_timezone") or "UTC"),
            )
            return {
                "workflow_action": "batch_proposals_ready",
                "pending_proposals_queue": proposals,
                "batch_extraction_error": error,
                "transaction_logged": False,
            }

        candidate = state.get("extracted_candidate")
        latest_user_message = self._latest_user_message(state.get("messages", []))
        hitl_attempt_count = int(state.get("hitl_attempt_count", 0))
        hitl_context_message = state.get("hitl_context_message")
        user_id = self._user_id_from_state(state)
        user_accounts = self._normalize_state_accounts(state.get("user_accounts"))
        if not user_accounts:
            user_accounts = await self._list_user_accounts_for_state(user_id)
        user_categories = self._normalize_state_categories(state.get("user_categories"))
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
            hitl_result["user_categories"] = user_categories
            hitl_result["user_accounts"] = user_accounts
            return hitl_result

        resolved_account, account_needs_clarification = self._resolve_candidate_account(
            candidate=candidate,
            accounts=user_accounts,
            latest_user_message=latest_user_message,
            hitl_active=bool(state.get("hitl_active", False)),
        )
        if resolved_account is not None:
            candidate["resolved_account_id"] = resolved_account["id"]
            candidate["resolved_account_name"] = resolved_account["name"]
        if account_needs_clarification:
            hitl_result = self._next_hitl_step(
                latest_user_message=latest_user_message,
                current_context=hitl_context_message,
                current_hitl_attempt_count=hitl_attempt_count,
                candidate=candidate,
                available_accounts=user_accounts,
                available_categories=user_categories,
                forced_missing_fields=["account"],
            )
            hitl_result["user_categories"] = user_categories
            hitl_result["user_accounts"] = user_accounts
            return hitl_result

        resolved_category, suggested_category_name, user_categories = await self._resolve_candidate_category(
            user_id=user_id,
            latest_user_message=latest_user_message,
            candidate=candidate,
            categories=user_categories,
            hitl_active=bool(state.get("hitl_active", False)),
            existing_suggested_category_name=state.get("hitl_suggested_category"),
        )
        if resolved_category is not None:
            candidate["resolved_category_id"] = resolved_category["id"]
            candidate["resolved_category_name"] = resolved_category["name"]
        if suggested_category_name is not None and not candidate.get("category"):
            candidate["category"] = suggested_category_name

        if not user_accounts:
            return {
                "workflow_action": "build_proposal_ready",
                "manual_transaction_input_required": False,
                "extracted_candidate": candidate,
                "user_accounts": user_accounts,
                "user_categories": user_categories,
            }

        candidate_transaction_type = self._map_transaction_type(str(candidate.get("type") or ""))
        if self._requires_category(candidate_transaction_type) and resolved_category is None:
            hitl_result = self._next_hitl_step(
                latest_user_message=latest_user_message,
                current_context=hitl_context_message,
                current_hitl_attempt_count=hitl_attempt_count,
                candidate=candidate,
                available_accounts=user_accounts,
                available_categories=user_categories,
                suggested_category_name=suggested_category_name,
                forced_missing_fields=["category"],
            )
            hitl_result["user_categories"] = user_categories
            hitl_result["user_accounts"] = user_accounts
            return hitl_result

        completeness_message = hitl_context_message or latest_user_message
        missing_fields = self._infer_missing_fields(
            completeness_message,
            candidate,
            available_categories=user_categories,
        )
        if missing_fields and missing_fields != ["context"]:
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
            hitl_result["user_categories"] = user_categories
            hitl_result["user_accounts"] = user_accounts
            return hitl_result

        candidate_confidence_score = int(candidate.get("confidence_score", 0))
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
            hitl_result["user_categories"] = user_categories
            hitl_result["user_accounts"] = user_accounts
            return hitl_result

        return {
            "workflow_action": "build_proposal_ready",
            "manual_transaction_input_required": False,
            "extracted_candidate": candidate,
            "user_accounts": user_accounts,
            "user_categories": user_categories,
        }

    @staticmethod
    def _route_after_candidate_evaluation(state: ChatGraphState) -> str:
        action = state.get("workflow_action")
        if action == "hitl_clarification":
            return "hitl_clarification"
        if action in {"build_proposal_ready", "manual_fallback", "batch_proposals_ready"}:
            return "transaction_flow"
        return "assistant_default"

    @staticmethod
    def _route_after_hitl_clarification(state: ChatGraphState) -> str:
        if state.get("workflow_action") == "cancel_hitl":
            return "transaction_flow"
        return "extract_transaction_candidate"

    async def _hitl_clarification_node(self, state: ChatGraphState) -> dict[str, Any]:
        missing_fields = state.get("hitl_missing_fields", [])
        attempt_number = max(1, int(state.get("hitl_attempt_count", 1)))
        question = self._build_hitl_question(
            missing_fields=missing_fields,
            attempt_number=attempt_number,
            category_options=state.get("hitl_category_options", []),
            account_options=state.get("hitl_account_options", []),
            suggested_category_name=state.get("hitl_suggested_category"),
        )

        human_response = interrupt(
            {
                "question": question,
                "attempt": attempt_number,
                "max_turns": self._hitl_max_turns,
                "missing_fields": missing_fields,
                "category_options": state.get("hitl_category_options", []),
                "account_options": state.get("hitl_account_options", []),
                "suggested_category_name": state.get("hitl_suggested_category"),
            }
        )

        if self._proposal_action(str(human_response)) == "cancel_proposal":
            return {
                "workflow_action": "cancel_hitl",
                "hitl_active": False,
                "hitl_attempt_count": 0,
                "hitl_context_message": None,
                "hitl_missing_fields": [],
                "hitl_category_options": [],
                "hitl_account_options": [],
                "hitl_suggested_category": None,
                "manual_transaction_input_required": False,
            }

        merged_context = self._merge_hitl_context(state.get("hitl_context_message"), str(human_response))
        return {
            "hitl_context_message": merged_context,
            "workflow_action": "build_proposal",
            "hitl_category_options": [],
            "hitl_account_options": [],
            "hitl_suggested_category": None,
            "manual_transaction_input_required": False,
        }

    async def _transaction_flow(self, state: ChatGraphState) -> dict[str, Any]:
        action = state.get("workflow_action")
        latest_user_message = self._latest_user_message(state.get("messages", []))
        pending_proposal = state.get("pending_proposal")

        if action == "batch_proposals_ready":
            proposals = list(state.get("pending_proposals_queue") or [])
            error = str(state.get("batch_extraction_error") or "")
            if error or not proposals:
                return {
                    "pending_proposals_queue": None,
                    "transaction_logged": False,
                    "manual_transaction_input_required": False,
                    "messages": [
                        AIMessage(content=error or "I could not validate every transaction row. Nothing was created.")
                    ],
                }
            return {
                "pending_proposal": None,
                "pending_proposals_queue": proposals,
                "extracted_candidates": None,
                "transaction_logged": False,
                "manual_transaction_input_required": False,
                "messages": [
                    AIMessage(
                        content=(
                            f"I found {len(proposals)} transactions. Please review and add each one in order; "
                            "nothing has been logged yet."
                        )
                    )
                ],
            }

        if action in {"build_proposal", "build_proposal_ready"}:
            candidate = state.get("extracted_candidate")
            if candidate is None:
                return {
                    "extracted_candidate": None,
                    "transaction_logged": False,
                    "manual_transaction_input_required": False,
                    "messages": [AIMessage(content="Unable to build a proposal from this message yet.")],
                }

            proposal = await self._build_proposal(
                user_id=self._user_id_from_state(state),
                candidate=candidate,
                user_accounts=self._normalize_state_accounts(state.get("user_accounts")),
                user_categories=self._normalize_state_categories(state.get("user_categories")),
            )
            if isinstance(proposal, str):
                return {
                    "extracted_candidate": None,
                    "hitl_active": False,
                    "hitl_attempt_count": 0,
                    "hitl_context_message": None,
                    "hitl_missing_fields": [],
                    "hitl_category_options": [],
                    "hitl_suggested_category": None,
                    "transaction_logged": False,
                    "manual_transaction_input_required": False,
                    "messages": [AIMessage(content=proposal)],
                }

            return {
                "pending_proposal": proposal,
                "extracted_candidate": None,
                "hitl_active": False,
                "hitl_attempt_count": 0,
                "hitl_context_message": None,
                "hitl_missing_fields": [],
                "hitl_category_options": [],
                "hitl_suggested_category": None,
                "transaction_logged": False,
                "manual_transaction_input_required": False,
                "messages": [AIMessage(content=self._format_proposal_message(proposal))],
            }

        if action == "manual_fallback":
            fallback_message = self._format_manual_fallback_message(state.get("hitl_missing_fields", []))
            manual_prefill_proposal = await self._build_manual_prefill_proposal(
                user_id=self._user_id_from_state(state),
                candidate=state.get("extracted_candidate"),
                context_message=state.get("hitl_context_message"),
                user_accounts=self._normalize_state_accounts(state.get("user_accounts")),
                user_categories=self._normalize_state_categories(state.get("user_categories")),
            )
            return {
                "pending_proposal": manual_prefill_proposal,
                "extracted_candidate": None,
                "hitl_active": False,
                "hitl_attempt_count": 0,
                "hitl_context_message": None,
                "hitl_missing_fields": [],
                "hitl_category_options": [],
                "hitl_suggested_category": None,
                "transaction_logged": False,
                "manual_transaction_input_required": True,
                "messages": [AIMessage(content=fallback_message)],
            }

        if action == "cancel_hitl":
            return {
                "pending_proposal": None,
                "extracted_candidate": None,
                "hitl_active": False,
                "hitl_attempt_count": 0,
                "hitl_context_message": None,
                "hitl_missing_fields": [],
                "hitl_category_options": [],
                "hitl_suggested_category": None,
                "transaction_logged": False,
                "manual_transaction_input_required": False,
                "messages": [AIMessage(content="Okay, I stopped this transaction draft. Nothing was logged.")],
            }

        if action == "confirm_proposal":
            if pending_proposal is None:
                return {
                    "extracted_candidate": None,
                    "transaction_logged": False,
                    "messages": [AIMessage(content="There is no pending proposal to confirm.")],
                }

            transaction = await self._transaction_service.create_transaction(
                CreateTransactionInput(
                    user_id=self._user_id_from_state(state),
                    account_id=uuid.UUID(pending_proposal["account_id"]),
                    type=TransactionType(pending_proposal["type"]),
                    amount_paise=int(pending_proposal["amount_paise"]),
                    occurred_at=datetime.fromisoformat(pending_proposal["occurred_at"]),
                    category_id=uuid.UUID(pending_proposal["category_id"]),
                    merchant=pending_proposal.get("merchant"),
                    note=pending_proposal.get("note") or "Logged via chat confirmation",
                )
            )

            amount_inr = f"{transaction.amount_paise / 100:.2f}"
            merchant = transaction.merchant or "merchant not provided"
            return {
                "pending_proposal": None,
                "extracted_candidate": None,
                "hitl_active": False,
                "hitl_attempt_count": 0,
                "hitl_context_message": None,
                "hitl_missing_fields": [],
                "hitl_category_options": [],
                "hitl_suggested_category": None,
                "transaction_logged": True,
                "manual_transaction_input_required": False,
                "messages": [
                    AIMessage(
                        content=(
                            f"Logged transaction: {transaction.type.value} INR {amount_inr} (merchant: {merchant})."
                        )
                    )
                ],
            }

        if action == "cancel_proposal":
            return {
                "pending_proposal": None,
                "extracted_candidate": None,
                "hitl_active": False,
                "hitl_attempt_count": 0,
                "hitl_context_message": None,
                "hitl_missing_fields": [],
                "hitl_category_options": [],
                "hitl_suggested_category": None,
                "transaction_logged": False,
                "manual_transaction_input_required": False,
                "messages": [AIMessage(content="Proposal discarded. Nothing was logged.")],
            }

        if action == "edit_proposal":
            if pending_proposal is None:
                return {
                    "extracted_candidate": None,
                    "transaction_logged": False,
                    "messages": [AIMessage(content="There is no pending proposal to edit.")],
                }

            updated = dict(pending_proposal)
            updated_amount = self._extract_amount_paise(latest_user_message)
            if updated_amount is not None:
                updated["amount_paise"] = updated_amount

            updated_merchant = self._extract_merchant(latest_user_message)
            if updated_merchant is not None:
                updated["merchant"] = updated_merchant

            correction_payload: dict[str, Any] | None = None
            if updated != pending_proposal:
                correction_payload = {
                    "original_proposal": dict(pending_proposal),
                    "corrected_proposal": dict(updated),
                    "user_message": latest_user_message,
                }

            return {
                "pending_proposal": updated,
                "extracted_candidate": None,
                "hitl_active": False,
                "hitl_attempt_count": 0,
                "hitl_context_message": None,
                "hitl_missing_fields": [],
                "agent_correction": correction_payload,
                "transaction_logged": False,
                "manual_transaction_input_required": False,
                "messages": [AIMessage(content=f"Updated proposal. {self._format_proposal_message(updated)}")],
            }

        if pending_proposal is not None:
            return {
                "extracted_candidate": None,
                "hitl_active": False,
                "transaction_logged": False,
                "manual_transaction_input_required": False,
                "messages": [
                    AIMessage(
                        content=(
                            f"{self._format_proposal_summary(pending_proposal)} "
                            "Reply 'confirm' to log, 'cancel' to discard, or send an edit "
                            "like 'make it INR 250'."
                        )
                    )
                ],
            }

        return {
            "extracted_candidate": None,
            "hitl_active": False,
            "transaction_logged": False,
            "manual_transaction_input_required": False,
            "messages": [AIMessage(content="No pending transaction proposal right now.")],
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
            if "category" in missing_fields
            else []
        )
        account_options = (
            [
                str(account.get("name") or "")
                for account in self._normalize_state_accounts(available_accounts or [])
                if account.get("is_active")
            ]
            if "account" in missing_fields
            else []
        )
        next_attempt_count = current_hitl_attempt_count + 1

        if next_attempt_count > self._hitl_max_turns:
            return {
                "workflow_action": "manual_fallback",
                "hitl_active": False,
                "hitl_attempt_count": 0,
                "hitl_context_message": updated_context,
                "extracted_candidate": candidate,
                "hitl_missing_fields": missing_fields,
                "hitl_category_options": category_options,
                "hitl_account_options": account_options,
                "hitl_suggested_category": resolved_suggested_category,
                "manual_transaction_input_required": True,
            }

        return {
            "workflow_action": "hitl_clarification",
            "hitl_active": True,
            "hitl_attempt_count": next_attempt_count,
            "hitl_context_message": updated_context,
            "hitl_missing_fields": missing_fields,
            "hitl_category_options": category_options,
            "hitl_account_options": account_options,
            "hitl_suggested_category": resolved_suggested_category,
            "manual_transaction_input_required": False,
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
        transaction_type = (candidate or {}).get("type") or (detected_type.value if detected_type is not None else None)
        amount_paise = (candidate or {}).get("amount_paise") or self._extract_amount_paise(message)

        has_date_hint = self._has_date_hint(normalized_message)
        has_candidate_date = self._has_candidate_date(candidate)

        missing_fields: list[str] = []
        if transaction_type is None:
            missing_fields.append("type")
        if amount_paise is None:
            missing_fields.append("amount")
        if not has_candidate_date and not has_date_hint:
            missing_fields.append("date")

        parsed_transaction_type = self._map_transaction_type(str(transaction_type)) if transaction_type else None
        if self._requires_category(parsed_transaction_type):
            matched_category = self._select_category_by_hint(
                available_categories or [],
                category_type=self._category_type_for_transaction_type(parsed_transaction_type),
                hint_values=[
                    (candidate or {}).get("resolved_category_name"),
                    (candidate or {}).get("category"),
                    (candidate or {}).get("note"),
                    message,
                ],
                allow_default=False,
            )
            if matched_category is None:
                missing_fields.append("category")

        if not missing_fields:
            missing_fields.append("context")

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
        attempts_label = f"({attempt_number}/{self._hitl_max_turns})"

        if primary_missing == "type":
            return f"To log this correctly {attempts_label}, is this an expense, income, refund, or transfer?"
        if primary_missing == "amount":
            return f"I need the exact amount {attempts_label}. How much was it in INR?"
        if primary_missing == "account":
            options = ", ".join(account_options or [])
            if options:
                return f"Which account should I use {attempts_label}? Choose one of: {options}."
            return f"Which account should I use {attempts_label}? Please provide the account name."
        if primary_missing == "merchant":
            return f"I can continue once I know the merchant {attempts_label}. Which store/person was this with?"
        if primary_missing == "date":
            return f"Please confirm when this happened {attempts_label} (today, yesterday, or a date)."
        if primary_missing == "category":
            options = ", ".join(category_options or [])
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
                "Please provide an existing category name, or reply `create <name>`. "
            )

        return (
            f"I still need one more detail {attempts_label} to be confident. "
            "Please share a complete sentence with amount, type, merchant, and date."
        )

    def _format_manual_fallback_message(self, missing_fields: list[str]) -> str:
        unresolved_labels = ", ".join(missing_fields)
        return (
            f"I still can't reach {self._proposal_confidence_threshold}% confidence after "
            f"{self._hitl_max_turns} clarification turns. "
            f"Please add this manually using the Add Transaction form (unclear: {unresolved_labels})."
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

        return f"{normalized_context}\n{normalized_latest_message}"

    async def _query_planner_node(self, state: ChatGraphState) -> dict[str, Any]:
        latest_user_message = self._latest_user_message(state.get("messages", []))
        if not latest_user_message:
            return {
                "messages": [AIMessage(content="Please tell me what transaction history you want to see.")],
                "query_tool_call_ids": [],
            }

        timezone_name = self._validated_timezone_name(state.get("runtime_timezone"))
        try:
            local_now = datetime.now(ZoneInfo(timezone_name)).isoformat()
        except (ZoneInfoNotFoundError, ValueError):
            timezone_name = "UTC"
            local_now = datetime.now(UTC).isoformat()

        plan = await self._create_query_plan(
            latest_user_message,
            timezone_name=timezone_name,
            local_now=local_now,
            conversation_context=self._conversation_context(state.get("messages", [])),
            previous_plan=state.get("last_finance_query_plan") or state.get("query_plan"),
            previous_result=state.get("last_finance_query_result"),
        )
        normalized_message = " ".join(latest_user_message.lower().split())
        if self._is_account_balance_query(normalized_message):
            requested_accounts = await self._resolve_query_account_names(
                user_id=self._user_id_from_state(state),
                message=latest_user_message,
                proposed_names=plan.account_names,
            )
            plan = plan.model_copy(
                update={
                    "action": "query",
                    "query_kind": "account_balance",
                    "date_period": "recent_default",
                    "account_names": requested_accounts,
                    "category_names": [],
                    "category_scope": "all",
                }
            )
        elif self._is_spending_by_account_query(normalized_message):
            plan = plan.model_copy(update={"action": "query", "query_kind": "spending_by_account"})
        if state.get("active_workflow_id") == "format_previous" and state.get("last_finance_query_result"):
            previous_plan = state.get("last_finance_query_plan") or state.get("query_plan") or {}
            try:
                prior_plan = FinanceQueryPlan.model_validate(previous_plan)
            except (TypeError, ValueError):
                prior_plan = FinanceQueryPlan()
            normalized_message = " ".join(latest_user_message.lower().split())
            plan = prior_plan.model_copy(
                update={
                    "action": "format_previous",
                    "result_format": "table" if "table" in normalized_message else "list",
                    "sort_order": "oldest_first"
                    if any(term in normalized_message for term in ("oldest first", "ascending", "oldest to newest"))
                    else "newest_first",
                }
            )
        return {
            "query_plan": plan.model_dump(),
            "runtime_timezone": timezone_name,
        }

    @staticmethod
    def _is_account_balance_query(message: str) -> bool:
        return bool(re.search(r"\b(?:account\s+balance|balance\s+of|available\s+funds|balances?)\b", message))

    @staticmethod
    def _is_spending_by_account_query(message: str) -> bool:
        return bool(re.search(r"\b(?:by|per|across)\s+accounts?\b", message)) and bool(
            re.search(r"\b(?:spend|spent|spending|expense|expenses)\b", message)
        )

    async def _resolve_query_account_names(
        self,
        *,
        user_id: uuid.UUID,
        message: str,
        proposed_names: list[str],
    ) -> list[str]:
        accounts = await self._account_repository.list_for_user(user_id)
        active_names = [str(account.name) for account in accounts if bool(account.is_active)]
        normalized_message = self._normalize_lookup_text(message)
        resolved = [name for name in active_names if self._normalize_lookup_text(name) in normalized_message]
        if resolved:
            return resolved
        explicit_match = re.search(
            r"\bbalance\s+(?:of|for)\s+(?:the\s+)?(.+?)(?:\s+account)?[?!.]*$",
            message,
            re.IGNORECASE,
        )
        if explicit_match:
            requested = self._sanitize_category(explicit_match.group(1))
            if requested:
                requested = re.sub(r"\s+account$", "", requested, flags=re.IGNORECASE).strip()
                return [requested]
        return [
            owned
            for proposed in proposed_names
            for owned in active_names
            if self._normalize_lookup_text(proposed) == self._normalize_lookup_text(owned)
        ]

    async def _query_orchestrator_node(self, state: ChatGraphState) -> dict[str, Any]:
        latest_user_message = self._latest_user_message(state.get("messages", []))
        plan_data = state.get("query_plan")
        if not latest_user_message or not isinstance(plan_data, dict):
            return {"query_tool_call_ids": []}

        if plan_data.get("action") == "compare_periods" and self._looks_like_unsupported_comparison(
            latest_user_message
        ):
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "I can compare this month with matching dates last month, or this week with matching "
                            "days last week. I cannot compare other period pairs yet."
                        )
                    )
                ],
                "query_tool_call_ids": [],
            }
        plan = FinanceQueryPlan.model_validate(plan_data)
        if plan.action == "compare_periods":
            category_names = list(dict.fromkeys(name.strip() for name in plan.category_names if name.strip()))
            if len(category_names) > 1:
                return {
                    "messages": [AIMessage(content="Please compare one category at a time.")],
                    "query_tool_call_ids": [],
                }
            tool_call_id = f"query-tool-{uuid.uuid4().hex}"
            return {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "query_spending_comparison",
                                "args": {
                                    "message": latest_user_message,
                                    "date_period": plan.date_period,
                                    "comparison_period": plan.comparison_period,
                                    "timezone_name": self._validated_timezone_name(state.get("runtime_timezone")),
                                    "category_hint": category_names[0] if category_names else None,
                                },
                                "id": tool_call_id,
                                "type": "tool_call",
                            }
                        ],
                    )
                ],
                "query_tool_call_ids": [tool_call_id],
            }
        if self._looks_like_unsupported_comparison(latest_user_message):
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "I can compare this month with matching dates last month, or this week with matching "
                            "days last week. I cannot compare other period pairs yet."
                        )
                    )
                ],
                "query_tool_call_ids": [],
            }
        if plan.category_scope == "unspecified" and not plan.category_names:
            return {
                "messages": [
                    AIMessage(content="Which expense categories should I include? Please name the categories.")
                ],
                "query_tool_call_ids": [],
            }
        if plan.query_kind == "account_balance":
            tool_call_id = f"query-tool-{uuid.uuid4().hex}"
            return {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "query_account_balances",
                                "args": {"account_names": plan.account_names},
                                "id": tool_call_id,
                                "type": "tool_call",
                            }
                        ],
                    )
                ],
                "query_tool_call_ids": [tool_call_id],
            }
        use_summary_tool = plan.query_kind == "summary"
        tool_name = (
            "query_spending_by_account"
            if plan.query_kind == "spending_by_account"
            else "query_spending_summary"
            if use_summary_tool
            else "query_transactions"
        )
        timezone_name = self._validated_timezone_name(state.get("runtime_timezone"))
        category_names = list(dict.fromkeys(name.strip() for name in plan.category_names if name.strip()))
        categories: list[str | None] = category_names or [None]
        tool_calls = []
        tool_call_ids: list[str] = []
        for category_name in categories:
            tool_call_id = f"query-tool-{uuid.uuid4().hex}"
            tool_call_ids.append(tool_call_id)
            tool_args: dict[str, Any] = {
                "message": latest_user_message,
                "date_period": plan.date_period,
                "period_count": plan.period_count,
                "timezone_name": timezone_name,
                "category_hint": category_name,
            }
            if plan.query_kind == "transaction_list":
                tool_args["limit"] = 10
                tool_args["transaction_type"] = plan.transaction_type
            tool_calls.append({"name": tool_name, "args": tool_args, "id": tool_call_id, "type": "tool_call"})

        return {
            "messages": [AIMessage(content="", tool_calls=tool_calls)],
            "query_tool_call_ids": tool_call_ids,
        }

    @staticmethod
    def _looks_like_unsupported_comparison(message: str) -> bool:
        normalized = " ".join(message.lower().split())
        has_comparison_cue = bool(re.search(r"\b(?:compare|vs\.?|versus)\b", normalized))
        if not has_comparison_cue:
            return False
        return not (
            ("this month" in normalized and "last month" in normalized)
            or ("this week" in normalized and "last week" in normalized)
        )

    async def _create_query_plan(
        self,
        message: str,
        *,
        timezone_name: str,
        local_now: str,
        conversation_context: str = "",
        previous_plan: dict[str, Any] | None = None,
        previous_result: dict[str, Any] | None = None,
    ) -> FinanceQueryPlan:
        if self._llm_query_plan_chain is not None:
            try:
                plan = await self._llm_query_plan_chain.ainvoke(
                    {
                        "message": message,
                        "timezone": timezone_name,
                        "local_now": local_now,
                        "conversation_context": conversation_context or "No earlier conversation.",
                        "previous_query_plan": json.dumps(previous_plan, ensure_ascii=False)
                        if previous_plan
                        else "None",
                        "previous_query_result": json.dumps(previous_result, ensure_ascii=False)
                        if previous_result
                        else "None",
                    }
                )
                if plan.confidence >= 0.55:
                    if plan.action == "format_previous" and not previous_result:
                        plan = plan.model_copy(update={"action": "query"})
                    if plan.action == "drill_down" and previous_plan:
                        return self._inherit_previous_query_scope(plan, previous_plan)
                    return plan
            except Exception:
                logger.exception("Finance query planning failed; falling back to basic query interpretation.")
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
        normalized = " ".join(message.lower().split())
        if LangGraphChatOrchestrator._is_transaction_drilldown_followup(normalized) and previous_plan:
            try:
                previous = FinanceQueryPlan.model_validate(previous_plan)
                return LangGraphChatOrchestrator._inherit_previous_query_scope(
                    previous.model_copy(update={"confidence": 0.5}), previous_plan
                )
            except (TypeError, ValueError):
                logger.warning("Previous finance query plan was invalid; falling back to standalone interpretation.")

        if previous_result and LangGraphChatOrchestrator._is_result_format_followup(normalized):
            previous = previous_plan or {}
            return FinanceQueryPlan(
                action="format_previous",
                query_kind="transaction_list",
                date_period=previous.get("date_period", "recent_default"),
                period_count=previous.get("period_count"),
                category_names=previous.get("category_names", []),
                category_scope=previous.get("category_scope", "all"),
                transaction_type=previous.get("transaction_type", "all"),
                result_format="table" if "table" in normalized else "list",
                sort_order="oldest_first"
                if any(term in normalized for term in ("oldest first", "oldest to newest", "ascending"))
                else "newest_first",
                confidence=0.5,
            )

        summary_cues = ("how much", "total", "spent", "spend", "spending", "summary")
        if LangGraphChatOrchestrator._is_account_balance_query(normalized):
            query_kind = "account_balance"
        elif LangGraphChatOrchestrator._is_spending_by_account_query(normalized):
            query_kind = "spending_by_account"
        else:
            query_kind = "summary" if any(cue in normalized for cue in summary_cues) else "transaction_list"

        period_count: int | None = None
        if "yesterday" in normalized:
            date_period = "yesterday"
        elif "today" in normalized:
            date_period = "today"
        elif "last week" in normalized:
            date_period = "last_week"
        elif "this week" in normalized or "this weeks" in normalized:
            date_period = "this_week"
        elif "last month" in normalized:
            date_period = "last_month"
        elif "this month" in normalized or "this months" in normalized:
            date_period = "this_month"
        else:
            weeks_match = re.search(r"\b(\d{1,2})\s+weeks?\b", normalized)
            days_match = re.search(r"\b(\d{1,3})\s+days?\b", normalized)
            if weeks_match:
                date_period = "last_n_weeks"
                period_count = int(weeks_match.group(1))
            elif days_match:
                date_period = "last_n_days"
                period_count = int(days_match.group(1))
            else:
                date_period = "recent_default"
        category_match = (
            re.search(
                r"\b(?:on|in|for|under|of)\s+([a-z][a-z0-9 &,\-]{1,80}?)"
                r"(?=\s+(?:this|last|today|yesterday|over|during)\b|[?!.]|$)",
                normalized,
            )
            if query_kind not in {"account_balance", "spending_by_account"}
            else None
        )
        category_names = (
            [part.strip() for part in re.split(r"\s*(?:,|&|\band\b)\s*", category_match.group(1)) if part.strip()]
            if category_match
            else []
        )
        action = "query"
        comparison_period = None
        if re.search(r"\b(?:vs\.?|versus|compare)\b", normalized):
            if "this month" in normalized and "last month" in normalized:
                action = "compare_periods"
                date_period = "this_month"
                comparison_period = "last_month"
                query_kind = "summary"
            elif "this week" in normalized and "last week" in normalized:
                action = "compare_periods"
                date_period = "this_week"
                comparison_period = "last_week"
                query_kind = "summary"
        return FinanceQueryPlan(
            action=action,
            query_kind=query_kind,
            date_period=date_period,
            period_count=period_count,
            category_names=category_names[:5],
            category_scope=(
                "selected"
                if category_names
                else "unspecified"
                if re.search(r"\b(?:category|categories)\b", normalized)
                else "all"
            ),
            comparison_period=comparison_period,
            confidence=0.5,
        )

    @staticmethod
    def _route_after_query_plan(state: ChatGraphState) -> str:
        plan = state.get("query_plan")
        if not isinstance(plan, dict):
            return "assistant_default"
        if plan.get("action") == "format_previous":
            return "format_previous_result"
        if plan.get("action") in {"query", "drill_down", "compare_periods"}:
            return "query_orchestrator"
        return "assistant_default"

    async def _format_previous_result_node(self, state: ChatGraphState) -> dict[str, Any]:
        plan_data = state.get("query_plan") or {}
        result = state.get("last_finance_query_result") or {}
        transactions = result.get("transactions")
        if not isinstance(transactions, list) or not transactions:
            return {
                "messages": [AIMessage(content="There are no transaction rows in the previous result to format.")],
            }

        sorted_transactions = sorted(
            (item for item in transactions if isinstance(item, dict)),
            key=lambda item: str(item.get("occurred_at") or item.get("date") or ""),
            reverse=plan_data.get("sort_order", "newest_first") != "oldest_first",
        )
        if plan_data.get("result_format", "list") == "table":
            lines = [
                "| Date | Merchant | Amount | Category |",
                "| --- | --- | ---: | --- |",
            ]
            for item in sorted_transactions:
                cells = (item.get("date"), item.get("merchant"), item.get("amount"), item.get("category"))
                lines.append("| " + " | ".join(self._markdown_table_cell(value) for value in cells) + " |")
            content = "\n".join(lines)
        else:
            content = "\n".join(
                f"{item.get('date')}: {item.get('merchant')} — {item.get('amount')} ({item.get('category')})"
                for item in sorted_transactions
            )

        return {"messages": [AIMessage(content=content)]}

    @staticmethod
    def _markdown_table_cell(value: Any) -> str:
        normalized = str(value if value is not None else "—").strip()
        return normalized.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")

    @staticmethod
    def _is_result_format_followup(message: str) -> bool:
        return any(
            term in message
            for term in (
                "table",
                "sort these",
                "sort them",
                "sort by date",
                "format these",
                "format them",
                "show these",
                "show them",
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
                "action": "drill_down",
                "query_kind": "transaction_list",
                "date_period": previous.date_period,
                "period_count": previous.period_count,
                "category_names": previous.category_names,
                "category_scope": previous.category_scope,
                "transaction_type": "expense" if previous.query_kind == "summary" else plan.transaction_type,
            }
        )

    @staticmethod
    def _is_transaction_drilldown_followup(message: str) -> bool:
        normalized = " ".join(message.lower().split()).strip("?.!, ")
        return normalized in {"where", "where exactly", "show me where"} or bool(
            re.search(r"\b(where did i spend|where was (?:it|that|this)|show me where i spent)\b", normalized)
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
            return ""
        prior_messages = relevant_messages[-(limit + 1) : -1]
        return "\n".join(
            f"{'User' if isinstance(message, HumanMessage) else 'Assistant'}: {message.content.strip()}"
            for message in prior_messages
        )

    @classmethod
    def _conversation_aware_message(cls, messages: list[BaseMessage]) -> str:
        latest_user_message = cls._latest_user_message(messages)
        context = cls._conversation_context(messages)
        if not context:
            return latest_user_message
        return f"Recent conversation (context only):\n{context}\nCurrent user message: {latest_user_message}"

    async def _query_tool_finalize(self, state: ChatGraphState) -> dict[str, Any]:
        tool_call_ids = state.get("query_tool_call_ids", [])
        if not tool_call_ids:
            return {"query_tool_call_ids": []}

        tool_messages = {
            str(message.tool_call_id): message
            for message in state.get("messages", [])
            if isinstance(message, ToolMessage) and str(message.tool_call_id) in tool_call_ids
        }
        if len(tool_messages) != len(tool_call_ids):
            return {"query_tool_call_ids": []}

        payloads = [self._parse_tool_payload(tool_messages[call_id].content) for call_id in tool_call_ids]
        failed_payload = next((payload for payload in payloads if payload.get("error")), None)
        if failed_payload is not None and failed_payload.get("error") not in {
            "category_ambiguous",
            "category_not_found",
        }:
            return {
                "messages": [
                    AIMessage(
                        content=str(
                            failed_payload.get("reply")
                            or "I could not complete that finance query safely. Please clarify and try again."
                        )
                    )
                ],
                "query_tool_call_ids": [],
                "last_finance_query_result": None,
                "insights": None,
            }
        failed_categories = [
            str(payload.get("category_hint") or "")
            for payload in payloads
            if payload.get("error") in {"category_ambiguous", "category_not_found"}
        ]
        if failed_categories:
            failed_label = ", ".join(name for name in failed_categories if name) or "the requested category"
            reply = f"I couldn't resolve {failed_label} to a unique expense category. Please clarify the category name."
            return {
                "messages": [AIMessage(content=reply)],
                "query_tool_call_ids": [],
                "last_finance_query_result": None,
                "insights": None,
            }

        facts_list = [payload.get("facts") for payload in payloads]
        facts = self._combine_query_facts(facts_list)
        reply = self._deterministic_combined_query_reply(facts)
        insights = self._normalize_insights_payload(payloads[0].get("insights")) if len(payloads) == 1 else None
        if isinstance(facts, dict) and self._llm_query_reply_chain is not None:
            try:
                generated_reply = await self._llm_query_reply_chain.ainvoke(
                    {
                        "question": self._latest_user_message(state.get("messages", [])),
                        "facts_json": json.dumps(facts, ensure_ascii=False),
                    }
                )
                candidate_reply = str(generated_reply.reply).strip()
                if candidate_reply and self._query_reply_preserves_facts(candidate_reply, facts):
                    reply = candidate_reply
                    insights = None
                elif candidate_reply:
                    logger.warning(
                        "Generated finance-query reply omitted required computed facts; using deterministic answer."
                    )
            except Exception:
                logger.exception("Finance query response generation failed; using deterministic answer.")
        return {
            "messages": [AIMessage(content=reply)],
            "query_tool_call_ids": [],
            "last_finance_query_plan": state.get("query_plan"),
            "last_finance_query_result": facts if isinstance(facts, dict) else None,
            "insights": insights,
            "finance_query_generation": int(state.get("finance_query_generation") or 0) + 1,
        }

    @staticmethod
    def _combine_query_facts(raw_facts: list[Any]) -> dict[str, Any] | None:
        facts_list = [facts for facts in raw_facts if isinstance(facts, dict)]
        if not facts_list or len(facts_list) != len(raw_facts):
            return None
        query_kind = facts_list[0].get("query_kind")
        if any(facts.get("query_kind") != query_kind for facts in facts_list):
            return None
        if len(facts_list) == 1:
            return facts_list[0]

        if query_kind == "spending_summary":
            total_spent_paise = sum(int(facts.get("total_spent_paise") or 0) for facts in facts_list)
            transaction_count = sum(int(facts.get("transaction_count") or 0) for facts in facts_list)
            categories = [
                {
                    "name": str(facts.get("category") or "Uncategorized"),
                    "total_spent_paise": int(facts.get("total_spent_paise") or 0),
                    "total_spent_display": str(facts.get("total_spent_display") or "INR 0.00"),
                    "transaction_count": int(facts.get("transaction_count") or 0),
                }
                for facts in facts_list
            ]
            return {
                "query_kind": query_kind,
                "category": None,
                "categories": categories,
                "date_from": facts_list[0].get("date_from"),
                "date_to": facts_list[0].get("date_to"),
                "total_spent_paise": total_spent_paise,
                "total_spent_display": f"INR {total_spent_paise / 100:,.2f}",
                "transaction_count": transaction_count,
            }

        if query_kind == "transaction_list":
            transactions_by_id: dict[str, dict[str, Any]] = {}
            for facts in facts_list:
                for transaction in facts.get("transactions", []):
                    if isinstance(transaction, dict):
                        transaction_id = str(
                            transaction.get("id")
                            or "|".join(
                                str(transaction.get(key) or "")
                                for key in ("occurred_at", "date", "amount", "merchant", "category")
                            )
                        )
                        transactions_by_id[transaction_id] = transaction
            transactions = sorted(
                transactions_by_id.values(),
                key=lambda transaction: str(transaction.get("occurred_at") or transaction.get("date") or ""),
                reverse=True,
            )[:10]
            return {
                "query_kind": query_kind,
                "category": None,
                "date_from": facts_list[0].get("date_from"),
                "date_to": facts_list[0].get("date_to"),
                "transaction_count": len(transactions),
                "has_more": any(bool(facts.get("has_more")) for facts in facts_list)
                or len(transactions_by_id) > len(transactions),
                "transactions": transactions,
            }

        return None

    @staticmethod
    def _deterministic_combined_query_reply(facts: dict[str, Any] | None) -> str:
        if not facts:
            return "I could not verify the requested finance-query results. Please try a more specific query."
        query_kind = facts.get("query_kind")
        if query_kind == "spending_summary":
            categories = facts.get("categories")
            if isinstance(categories, list):
                category_totals = "; ".join(
                    f"{item['name']}: {item['total_spent_display']} ({item['transaction_count']} transactions)"
                    for item in categories
                )
                return (
                    f"From {facts.get('date_from')} to {facts.get('date_to')}, the selected categories "
                    f"total {facts.get('total_spent_display')} across {facts.get('transaction_count')} transactions. "
                    f"{category_totals}."
                )
            category_scope = f" for {facts.get('category')}" if facts.get("category") else ""
            reply = (
                f"From {facts.get('date_from')} to {facts.get('date_to')}, you spent "
                f"{facts.get('total_spent_display')}{category_scope} across "
                f"{facts.get('transaction_count')} transactions."
            )
            top_categories = facts.get("top_categories")
            if isinstance(top_categories, list) and top_categories:
                totals = "; ".join(f"{item.get('name')}: {item.get('total_spent_display')}" for item in top_categories)
                reply += f" Top categories: {totals}."
            return reply
        if query_kind == "transaction_list":
            transactions = facts.get("transactions")
            if isinstance(transactions, list) and transactions:
                transaction_lines = [
                    f"{item.get('date')}: {item.get('merchant')} — {item.get('amount')} ({item.get('category')})"
                    for item in transactions
                ]
                reply = f"I found {facts.get('transaction_count')} matching transactions:\n" + "\n".join(
                    f"• {line}" for line in transaction_lines
                )
                if facts.get("has_more"):
                    reply += "\nmore matching transactions exist; showing the newest 10."
                return reply
            category_scope = f" for {facts.get('category')}" if facts.get("category") else ""
            return (
                f"No matching transactions{category_scope} from {facts.get('date_from')} to "
                f"{facts.get('date_to')}; 0 transactions found."
            )
        if query_kind == "account_balance":
            accounts = facts.get("accounts") or []
            if not accounts:
                return "There are no active accounts."
            reply = (
                "Account balances: "
                + "; ".join(f"{item.get('name')}: {item.get('balance_display')}" for item in accounts)
                + "."
            )
            omitted = int(facts.get("truncated_account_count") or 0)
            return reply + (f" {omitted} more omitted." if omitted else "")
        if query_kind == "spending_by_account":
            category_scope = f" {facts.get('category')}" if facts.get("category") else ""
            lines = "; ".join(
                f"{item.get('account_name')}: {item.get('total_spent_display')} across "
                f"{item.get('transaction_count')} transactions"
                for item in facts.get("accounts") or []
            )
            reply = (
                f"From {facts.get('date_from')} to {facts.get('date_to')},{category_scope} spending was "
                f"{facts.get('total_spent_display')} across {facts.get('transaction_count')} transactions. {lines}."
            )
            omitted = int(facts.get("truncated_account_count") or 0)
            return reply + (f" {omitted} more omitted." if omitted else "")
        if query_kind == "spending_comparison":
            current = facts.get("current_period") or {}
            previous = facts.get("comparison_period") or {}
            category_scope = f" for {facts.get('category')}" if facts.get("category") else ""
            direction = str(facts.get("direction") or "same")
            if direction == "same":
                change = f"spending was unchanged ({facts.get('delta_display')})"
            else:
                change = f"{facts.get('delta_display')} {direction}"
                percent_change = facts.get("percent_change")
                change += (
                    f", a {percent_change}% {'increase' if direction == 'higher' else 'decrease'}"
                    if percent_change is not None
                    else "; percentage change is unavailable because the earlier total was zero"
                )
            return (
                f"{current.get('name')} {current.get('total_spent_display')} across "
                f"{current.get('transaction_count')} transactions versus {previous.get('name')} "
                f"{previous.get('total_spent_display')} across {previous.get('transaction_count')} transactions"
                f"{category_scope}; {change}."
            )
        return "I could not verify the requested finance-query results. Please try a more specific query."

    @staticmethod
    def _query_reply_preserves_facts(reply: str, facts: dict[str, Any]) -> bool:
        normalized_reply = " ".join(reply.lower().split())
        query_kind = facts.get("query_kind")
        category = str(facts.get("category") or "").strip()
        if category and category.lower() not in normalized_reply:
            return False

        if query_kind == "spending_summary":
            total = str(facts.get("total_spent_display") or "").strip()
            transaction_count = int(facts.get("transaction_count") or 0)
            if not (
                total
                and total.lower() in normalized_reply
                and re.search(rf"(?<!\d){transaction_count}(?!\d)", normalized_reply)
                and re.search(r"\btransactions?\b", normalized_reply)
            ):
                return False
            categories = facts.get("categories")
            scoped_categories = categories if isinstance(categories, list) else facts.get("top_categories")
            if not isinstance(scoped_categories, list):
                return True
            return all(
                str(item.get("name") or "").lower() in normalized_reply
                and str(item.get("total_spent_display") or "").lower() in normalized_reply
                for item in scoped_categories
            )

        if query_kind == "transaction_list":
            transaction_count = int(facts.get("transaction_count") or 0)
            if not re.search(rf"(?<!\d){transaction_count}(?!\d)", normalized_reply) or not re.search(
                r"\btransactions?\b", normalized_reply
            ):
                return False
            transactions = facts.get("transactions")
            if not isinstance(transactions, list) or not transactions:
                return True
            if facts.get("has_more") and "more matching transactions exist" not in normalized_reply:
                return False
            latest = transactions[0]
            if not isinstance(latest, dict):
                return False
            latest_amount = str(latest.get("amount") or "").strip()
            latest_date = str(latest.get("date") or "").strip()
            latest_merchant = str(latest.get("merchant") or "").strip()
            required_fields = (latest_amount, latest_date, latest_merchant)
            if not all(value and value.lower() in normalized_reply for value in required_fields):
                return False
            return all(
                isinstance(transaction, dict)
                and all(
                    str(transaction.get(field) or "").strip().lower() in normalized_reply
                    for field in ("date", "amount", "merchant")
                )
                for transaction in transactions
            )

        if query_kind == "account_balance":
            accounts = facts.get("accounts")
            return isinstance(accounts, list) and all(
                str(item.get("name") or "").lower() in normalized_reply
                and str(item.get("balance_display") or "").lower() in normalized_reply
                for item in accounts
            )

        if query_kind == "spending_by_account":
            total = str(facts.get("total_spent_display") or "").lower()
            count = int(facts.get("transaction_count") or 0)
            accounts = facts.get("accounts")
            if not total or total not in normalized_reply or not re.search(rf"(?<!\d){count}(?!\d)", normalized_reply):
                return False
            if not isinstance(accounts, list) or not all(
                str(item.get("account_name") or "").lower() in normalized_reply
                and str(item.get("total_spent_display") or "").lower() in normalized_reply
                for item in accounts
            ):
                return False
            omitted = int(facts.get("truncated_account_count") or 0)
            return not omitted or f"{omitted} more omitted" in normalized_reply

        if query_kind == "spending_comparison":
            current = facts.get("current_period") or {}
            previous = facts.get("comparison_period") or {}
            required = [
                current.get("total_spent_display"),
                str(current.get("transaction_count")),
                previous.get("total_spent_display"),
                str(previous.get("transaction_count")),
                facts.get("delta_display"),
            ]
            if not all(str(value or "").lower() in normalized_reply for value in required):
                return False
            percent_change = facts.get("percent_change")
            return percent_change is None or f"{percent_change}%" in normalized_reply

        return False

    @staticmethod
    def _normalize_insights_payload(raw_insights: Any) -> list[dict[str, str]] | None:
        if not isinstance(raw_insights, list):
            return None

        insights: list[dict[str, str]] = []
        for raw_item in raw_insights:
            if not isinstance(raw_item, dict):
                continue
            title = str(raw_item.get("title") or "").strip()
            detail = str(raw_item.get("detail") or "").strip()
            if not title or not detail:
                continue
            insights.append({"title": title, "detail": detail})

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
                return {"reply": raw_content}
            return parsed if isinstance(parsed, dict) else {"reply": raw_content}

        return {}

    async def _assistant_default(self, state: ChatGraphState) -> dict[str, list[AIMessage]]:
        supervisor_response = str(state.get("supervisor_response") or "").strip()
        if supervisor_response:
            return {"messages": [AIMessage(content=supervisor_response)]}

        latest_user_message = self._latest_user_message(state.get("messages", []))
        if not latest_user_message:
            return {"messages": [AIMessage(content=_REFUSAL_MESSAGE)]}

        previous_user_message = self._previous_user_message(state.get("messages", []))
        if previous_user_message:
            reply = f'Got it. You said: "{latest_user_message}". Earlier you mentioned: "{previous_user_message}".'
        else:
            reply = f'Got it. You said: "{latest_user_message}".'

        return {"messages": [AIMessage(content=reply)]}

    @staticmethod
    async def _assistant_refusal(_: ChatGraphState) -> dict[str, list[AIMessage]]:
        return {"messages": [AIMessage(content=_REFUSAL_MESSAGE)]}

    async def _build_proposal(
        self,
        *,
        user_id: uuid.UUID,
        candidate: dict[str, Any],
        user_accounts: list[dict[str, Any]] | None = None,
        user_categories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | str:
        if candidate["type"] == TransactionType.TRANSFER.value:
            return "Transfer extraction is detected, but transfer proposal flow is not enabled yet."

        accounts = self._normalize_state_accounts(user_accounts)
        if not accounts:
            accounts = await self._list_user_accounts_for_state(user_id)
        if not accounts:
            return "I can log this transaction, but please create an account first."

        resolved_account_id = str(candidate.get("resolved_account_id") or "").strip()
        account = (
            next(
                (item for item in accounts if item["id"] == resolved_account_id and item["is_active"]),
                None,
            )
            if resolved_account_id
            else None
        )
        if account is None:
            account = next((item for item in accounts if item["is_active"] and item["is_default"]), None)
        if account is None:
            active_accounts = [item for item in accounts if item["is_active"]]
            if len(active_accounts) == 1:
                account = active_accounts[0]
            elif active_accounts:
                return "Please choose a default account or specify which account to use."
        if account is None:
            return "I can log this transaction, but please create an active account first."

        category_type = (
            CategoryType.EXPENSE if candidate["type"] == TransactionType.EXPENSE.value else CategoryType.INCOME
        )
        categories = self._normalize_state_categories(user_categories)
        if not categories:
            categories = await self._list_user_categories_for_state(user_id)

        category = None
        resolved_category_id = str(candidate.get("resolved_category_id") or "").strip()
        if resolved_category_id:
            category = next(
                (
                    item
                    for item in categories
                    if item["id"] == resolved_category_id and item["type"] == category_type.value
                ),
                None,
            )

        if category is None:
            category = self._select_category_by_hint(
                categories,
                category_type=category_type,
                hint_values=[candidate.get("resolved_category_name"), candidate.get("category"), candidate.get("note")],
                allow_default=False,
            )

        if category is None:
            label = "expense" if category_type == CategoryType.EXPENSE else "income"
            return f"I can log this transaction, but please create an {label} category first."

        return {
            "type": candidate["type"],
            "amount_paise": candidate["amount_paise"],
            "occurred_at": candidate["occurred_at"],
            "merchant": candidate.get("merchant"),
            "note": candidate.get("note"),
            "confidence_score": int(candidate.get("confidence_score", 0)),
            "account_id": account["id"],
            "account_name": account["name"],
            "category_id": category["id"],
            "category_name": category["name"],
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
        account_id = str(normalized_candidate.get("resolved_account_id") or "").strip()
        account = (
            next(
                (item for item in accounts if item["id"] == account_id and item["is_active"]),
                None,
            )
            if account_id
            else None
        )
        if account is None:
            account = next((item for item in accounts if item["is_active"] and item["is_default"]), None)
        if account is None:
            active_accounts = [item for item in accounts if item["is_active"]]
            account = active_accounts[0] if len(active_accounts) == 1 else None

        raw_type = str(normalized_candidate.get("type") or "").strip().lower()
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
                normalized_candidate.get("resolved_category_name"),
                normalized_candidate.get("category"),
                normalized_candidate.get("note"),
                context_message,
            ],
            allow_default=False,
        )

        amount_paise = 0
        raw_amount = normalized_candidate.get("amount_paise")
        if isinstance(raw_amount, int) and raw_amount > 0:
            amount_paise = raw_amount

        occurred_at = str(normalized_candidate.get("occurred_at") or datetime.now(UTC).isoformat())
        merchant = self._sanitize_merchant(normalized_candidate.get("merchant"))
        note = self._sanitize_note(normalized_candidate.get("note")) or self._infer_note_from_message(
            context_message or ""
        )
        confidence_score = int(normalized_candidate.get("confidence_score", 0))

        return {
            "type": transaction_type.value,
            "amount_paise": amount_paise,
            "occurred_at": occurred_at,
            "merchant": merchant,
            "note": note,
            "account_id": account["id"] if account else "",
            "account_name": account["name"] if account else "Select account",
            "category_id": category["id"] if category else "",
            "category_name": category["name"] if category else "Select category",
            "confidence_score": max(0, min(100, confidence_score)),
        }

    @staticmethod
    def _count_transaction_rows(message: str) -> int:
        date_pattern = re.compile(
            r"\b(?:\d{4}-\d{1,2}-\d{1,2}|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
            r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
            r"\s+\d{1,2},?\s+\d{4})\b",
            re.IGNORECASE,
        )
        matches = list(date_pattern.finditer(message))
        count = 0
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(message)
            segment = message[match.end() : end]
            if _CURRENCY_PREFIX_PATTERN.search(segment) or _CURRENCY_SUFFIX_PATTERN.search(segment):
                count += 1
        return count

    @classmethod
    def _looks_like_multiple_transaction_rows(cls, message: str) -> bool:
        return cls._count_transaction_rows(message) >= 2

    async def _extract_transaction_batch(
        self,
        message: str,
        *,
        expected_count: int,
        accounts: list[dict[str, Any]],
        categories: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], str | None]:
        chain = getattr(self, "_llm_batch_extraction_chain", None)
        if chain is None:
            return [], "Batch extraction is unavailable right now. Nothing was created."
        try:
            extracted = await chain.ainvoke(
                {
                    "message": message,
                    "today_utc": datetime.now(UTC).isoformat(),
                    "accounts_catalog": self._build_accounts_catalog_for_prompt(accounts),
                    "categories_catalog": self._build_categories_catalog_for_prompt(categories),
                }
            )
        except Exception:
            logger.exception("Batch transaction extraction failed.")
            return [], "I could not safely extract every transaction row. Nothing was created."
        if extracted.confidence < 0.55 or len(extracted.transactions) != expected_count:
            return [], "I could not verify every transaction row. Nothing was created."
        candidates: list[dict[str, Any]] = []
        for row in extracted.transactions:
            candidate = self._candidate_from_extraction_output(row, message)
            if candidate is None:
                return [], "At least one transaction row was incomplete or uncertain. Nothing was created."
            candidates.append(candidate)
        return candidates, None

    @classmethod
    def _candidate_from_extraction_output(
        cls, extracted: TransactionExtractionOutput, source_message: str
    ) -> dict[str, Any] | None:
        if not extracted.is_transaction or extracted.confidence < 0.55 or extracted.amount is None:
            return None
        amount_paise = cls._to_paise(extracted.amount)
        if amount_paise is None or extracted.occurred_at is None:
            return None
        occurred_at = extracted.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        transaction_type = cls._map_transaction_type(extracted.transaction_type)
        return {
            "type": transaction_type.value if transaction_type else None,
            "amount_paise": amount_paise,
            "occurred_at": occurred_at.isoformat(),
            "selected_account": cls._sanitize_category(extracted.selected_account),
            "account_hint": cls._sanitize_category(extracted.account_hint),
            "selected_category": cls._sanitize_category(extracted.selected_category),
            "category": cls._sanitize_category(extracted.category),
            "merchant": cls._sanitize_merchant(extracted.merchant),
            "note": cls._sanitize_note(extracted.note) or cls._infer_note_from_message(source_message),
            "confidence_score": max(0, min(100, int(round(extracted.confidence * 100)))),
        }

    @classmethod
    async def _build_transaction_batch_proposals(
        cls,
        *,
        candidates: list[dict[str, Any]],
        latest_user_message: str,
        user_accounts: list[dict[str, Any]],
        user_categories: list[dict[str, Any]],
        timezone_name: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        del latest_user_message
        del timezone_name
        proposals: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates, start=1):
            account = cls._find_exact_named_item(user_accounts, candidate.get("selected_account"))
            if account is None or not account.get("is_active"):
                return [], f"I could not resolve the account in row {index}. Nothing was created."
            category = cls._find_exact_named_item(
                user_categories, candidate.get("selected_category") or candidate.get("category")
            )
            if category is None:
                return [], f"I could not resolve the category in row {index}. Nothing was created."
            transaction_type = cls._map_transaction_type(candidate.get("type"))
            if transaction_type is None:
                transaction_type = TransactionType(category["type"])
            if transaction_type == TransactionType.TRANSFER:
                return [], f"Transfers are not supported in batch row {index}. Nothing was created."
            expected_category_type = cls._category_type_for_transaction_type(transaction_type)
            if category.get("type") != expected_category_type.value:
                return [], f"The direction and category conflict in row {index}. Nothing was created."
            amount_paise = int(candidate.get("amount_paise") or 0)
            occurred_at = str(candidate.get("occurred_at") or "")
            if amount_paise <= 0 or not occurred_at or int(candidate.get("confidence_score") or 0) < 55:
                return [], f"Row {index} is incomplete or uncertain. Nothing was created."
            proposals.append(
                {
                    "type": transaction_type.value,
                    "amount_paise": amount_paise,
                    "occurred_at": occurred_at,
                    "merchant": cls._sanitize_merchant(candidate.get("merchant")),
                    "note": cls._sanitize_note(candidate.get("note")),
                    "account_id": account["id"],
                    "account_name": account["name"],
                    "category_id": category["id"],
                    "category_name": category["name"],
                    "confidence_score": int(candidate.get("confidence_score") or 0),
                }
            )
        return proposals, None

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
                    "message": message,
                    "today_utc": datetime.now(UTC).isoformat(),
                    "accounts_catalog": self._build_accounts_catalog_for_prompt(accounts or []),
                    "categories_catalog": self._build_categories_catalog_for_prompt(categories or []),
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
            "type": transaction_type.value,
            "amount_paise": amount_paise,
            "occurred_at": occurred_at.isoformat(),
            "selected_account": self._sanitize_category(extracted.selected_account),
            "account_hint": self._sanitize_category(extracted.account_hint),
            "selected_category": self._sanitize_category(extracted.selected_category),
            "category": self._sanitize_category(extracted.category),
            "merchant": self._sanitize_merchant(extracted.merchant),
            "note": inferred_note,
            "confidence_score": max(0, min(100, int(round(extracted.confidence * 100)))),
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
        relative_days_match = re.search(r"\b(\d{1,3})\s+days?\s+ago\b", normalized)
        relative_weeks_match = re.search(r"\b(\d{1,3})\s+weeks?\s+ago\b", normalized)
        relative_months_match = re.search(r"\b(\d{1,3})\s+months?\s+ago\b", normalized)

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
        elif "yesterday" in normalized:
            occurred_at -= timedelta(days=1)
            has_date_hint = True
        elif "today" in normalized:
            has_date_hint = True
        elif "last week" in normalized:
            occurred_at -= timedelta(weeks=1)
            has_date_hint = True
        elif "last month" in normalized:
            occurred_at -= timedelta(days=30)
            has_date_hint = True

        category = self._extract_category_hint(message)
        merchant = self._extract_merchant(message)

        return {
            "type": transaction_type.value,
            "amount_paise": amount_paise,
            "occurred_at": occurred_at.isoformat(),
            "selected_account": None,
            "account_hint": None,
            "category": category,
            "merchant": merchant,
            "note": self._infer_note_from_message(message),
            "confidence_score": self._confidence_score_from_rule_based(
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
        cleaned = value.strip(" .,!?;:")
        if not cleaned:
            return None
        return cleaned[:255]

    @staticmethod
    def _sanitize_note(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            return None
        return cleaned[:500]

    @staticmethod
    def _sanitize_category(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split()).strip(" .,!?;:")
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
        return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())

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
            scoped_categories = [item for item in categories if item.get("type") == category_type.value]

        if not scoped_categories:
            return None

        for raw_hint in hint_values:
            sanitized_hint = cls._sanitize_category(raw_hint)
            if sanitized_hint is None:
                continue

            normalized_hint = cls._normalize_lookup_text(sanitized_hint)
            if not normalized_hint:
                continue

            padded_hint = f" {normalized_hint} "
            for category in scoped_categories:
                normalized_name = cls._normalize_lookup_text(str(category.get("name") or ""))
                if not normalized_name:
                    continue
                if normalized_hint == normalized_name:
                    return category
                if f" {normalized_name} " in padded_hint:
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

            account_id = str(raw_account.get("id") or "").strip()
            account_name = str(raw_account.get("name") or "").strip()
            if not account_id or not account_name:
                continue

            normalized_accounts.append(
                {
                    "id": account_id,
                    "name": account_name,
                    "type": str(raw_account.get("type") or "").strip().lower(),
                    "is_active": bool(raw_account.get("is_active", False)),
                    "is_default": bool(raw_account.get("is_default", False)),
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

            category_id = str(raw_category.get("id") or "").strip()
            category_name = str(raw_category.get("name") or "").strip()
            category_type = str(raw_category.get("type") or "").strip().lower()
            if not category_id or not category_name:
                continue
            if category_type not in {CategoryType.EXPENSE.value, CategoryType.INCOME.value}:
                continue

            normalized_categories.append(
                {
                    "id": category_id,
                    "name": category_name,
                    "type": category_type,
                }
            )

        return normalized_categories

    async def _list_user_accounts_for_state(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        accounts = await self._account_repository.list_for_user(user_id)
        return [
            {
                "id": str(account.id),
                "name": account.name,
                "type": account.type.value,
                "balance_paise": account.balance_paise,
                "currency": account.currency,
                "is_active": bool(account.is_active),
                "is_default": bool(account.is_default),
            }
            for account in accounts
        ]

    async def _list_user_categories_for_state(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        categories = await self._category_repository.list_for_user(user_id)
        return [
            {
                "id": str(category.id),
                "name": category.name,
                "type": category.type.value,
            }
            for category in categories
        ]

    @classmethod
    def _build_accounts_catalog_for_prompt(cls, accounts: list[dict[str, Any]]) -> str:
        catalog = [
            {
                "name": str(account.get("name") or "").strip(),
                "type": str(account.get("type") or "").strip().lower(),
                "is_active": bool(account.get("is_active", False)),
                "is_default": bool(account.get("is_default", False)),
            }
            for account in cls._normalize_state_accounts(accounts)
            if bool(account.get("is_active", False))
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
        active_accounts = [account for account in accounts if account.get("is_active")]
        selected_name = cls._sanitize_category(candidate.get("selected_account"))
        hint = cls._sanitize_category(candidate.get("account_hint"))

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
                if cls._normalize_lookup_text(str(account.get("name") or "")) == normalized_request
            ]
            if len(exact_matches) == 1:
                return exact_matches[0], False
            if len(exact_matches) > 1:
                return None, True

            partial_matches = [
                account
                for account in active_accounts
                if normalized_request
                and normalized_request in cls._normalize_lookup_text(str(account.get("name") or ""))
            ]
            if len(partial_matches) == 1:
                return partial_matches[0], False
            return None, True

        default_accounts = [account for account in active_accounts if account.get("is_default")]
        if len(default_accounts) == 1:
            return default_accounts[0], False
        if len(active_accounts) == 1:
            return active_accounts[0], False
        return None, bool(active_accounts)

    @classmethod
    def _account_name_mentioned(cls, account_name: str, message: str) -> bool:
        normalized_name = cls._normalize_lookup_text(account_name)
        normalized_message = cls._normalize_lookup_text(message)
        return bool(normalized_name and f" {normalized_name} " in f" {normalized_message} ")

    @classmethod
    def _build_categories_catalog_for_prompt(cls, categories: list[dict[str, Any]]) -> str:
        if not categories:
            return "[]"

        catalog: list[dict[str, Any]] = []
        for category in categories:
            category_name = str(category.get("name") or "").strip()
            category_type = str(category.get("type") or "").strip().lower()
            if not category_name:
                continue

            normalized_name = cls._normalize_lookup_text(category_name)
            alias_tokens = [token for token in normalized_name.split(" ") if token]
            aliases = [normalized_name, *alias_tokens]
            unique_aliases = list(dict.fromkeys(alias for alias in aliases if alias))

            usage_hint = (
                f"Use this for {category_name} related {category_type} transactions."
                if category_type
                else f"Use this for {category_name} related transactions."
            )

            catalog.append(
                {
                    "name": category_name,
                    "type": category_type,
                    "when_to_use": usage_hint,
                    "aliases": unique_aliases,
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
        transaction_type = cls._map_transaction_type(str((candidate or {}).get("type") or ""))
        desired_category_type = cls._category_type_for_transaction_type(transaction_type)
        scoped_categories = (
            [item for item in normalized_categories if item["type"] == desired_category_type.value]
            if desired_category_type is not None
            else normalized_categories
        )
        return [item["name"] for item in scoped_categories]

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
        candidate_transaction_type = self._map_transaction_type(str(candidate.get("type") or ""))
        category_type = self._category_type_for_transaction_type(candidate_transaction_type)
        if category_type is None:
            return None, None, normalized_categories

        selected_category_hint = self._sanitize_category(candidate.get("selected_category"))
        selected_category_was_answered_now = not hitl_active or (
            selected_category_hint is not None
            and self._category_name_mentioned_in_message(selected_category_hint, latest_user_message)
        )
        if selected_category_hint is not None and selected_category_was_answered_now:
            selected_category = next(
                (
                    item
                    for item in normalized_categories
                    if item.get("type") == category_type.value
                    and self._normalize_lookup_text(str(item.get("name") or ""))
                    == self._normalize_lookup_text(selected_category_hint)
                ),
                None,
            )
            if selected_category is not None:
                return selected_category, selected_category_hint, normalized_categories

        category_hint = self._sanitize_category(candidate.get("category"))
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
                candidate.get("resolved_category_name"),
                category_hint,
                candidate.get("note"),
                latest_user_message,
            ],
            allow_default=False,
        )

        scoped_categories = [item for item in normalized_categories if item.get("type") == category_type.value]
        if (
            matched_category is not None
            and len(scoped_categories) == 1
            and self._extract_category_hint(latest_user_message) is None
            and not self._category_name_mentioned_in_message(
                str(matched_category.get("name") or ""),
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
        category_name = str(state.get("requested_category_name") or "").strip()
        category_type = str(state.get("requested_category_type") or "").strip().lower()
        if not category_name or category_type not in {CategoryType.EXPENSE.value, CategoryType.INCOME.value}:
            return {"category_tool_call_id": None}

        tool_call_id = f"category-tool-{uuid.uuid4().hex}"
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "create_category",
                            "args": {"category_name": category_name, "category_type": category_type},
                            "id": tool_call_id,
                            "type": "tool_call",
                        }
                    ],
                )
            ],
            "category_tool_call_id": tool_call_id,
        }

    async def _category_tool_finalize(self, state: CategoryToolGraphState) -> dict[str, Any]:
        tool_message = self._latest_tool_message(
            state.get("messages", []),
            tool_call_id=state.get("category_tool_call_id"),
        )
        if tool_message is None:
            return {"created_category": None, "category_tool_call_id": None}

        parsed_payload = self._parse_tool_payload(tool_message.content)
        category = parsed_payload.get("category")
        return {
            "created_category": category if isinstance(category, dict) else None,
            "category_tool_call_id": None,
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
            "runtime_user_id": str(user_id),
            "user_categories": existing_categories,
            "requested_category_name": category_name,
            "requested_category_type": category_type.value,
        }

        tool_result = await self._category_tool_graph.ainvoke(tool_state)
        category = tool_result.get("created_category")
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

        option_names = [str(item.get("name") or "") for item in category_options if str(item.get("name") or "").strip()]
        try:
            result = await self._llm_hitl_category_resolution_chain.ainvoke(
                {
                    "user_reply": latest_user_message,
                    "category_options_json": json.dumps(option_names, ensure_ascii=False),
                    "suggested_category_name": suggested_category_name or "",
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
            return str(matched_category.get("name") or ""), None

        affirmative_create_match = re.search(
            r"^(?:yes|yeah|yep|yup|ok|okay|sure|proceed|go ahead)\s+(.+)$",
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
                    return str(requested_existing.get("name") or ""), None
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
            r"\b(?:yes|yeah|yep|yup|ok|okay|sure|proceed|go ahead)\b",
            normalized_message,
        ):
            return None, suggested_name

        return None, None

    @classmethod
    def _extract_requested_new_category_name(cls, message: str) -> str | None:
        match = re.search(
            r"\b(?:create|add|new)\s+(?:(?:a|an)\s+)?(?:(?:expense|income)\s+)?"
            r"(?:category\s*)?(?:(?:called|named)\s*)?([A-Za-z][A-Za-z0-9 &'\-.]{1,80})",
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
        return f" {normalized_category} " in f" {normalized_message} "

    @staticmethod
    def _infer_note_from_message(message: str) -> str | None:
        cleaned_message = " ".join(message.strip().split())
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
        normalized_message = " ".join(message.lower().split())
        if LangGraphChatOrchestrator._is_non_transaction_query(normalized_message):
            return False

        has_amount = LangGraphChatOrchestrator._extract_amount_paise(normalized_message) is not None
        has_action_keyword = any(keyword in normalized_message for keyword in _STRONG_TRANSACTION_ACTION_KEYWORDS)
        return has_amount and has_action_keyword

    @staticmethod
    def _is_non_transaction_query(message: str) -> bool:
        normalized_message = " ".join(message.lower().split())
        has_query_cue = any(cue in normalized_message for cue in _NON_TRANSACTION_QUERY_CUES)
        return has_query_cue or normalized_message.endswith("?")

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

        normalized_message = " ".join(latest_user_message.lower().split())
        if not LangGraphChatOrchestrator._is_non_transaction_query(normalized_message):
            return False

        return any(hint in normalized_message for hint in _FINANCE_QUERY_HINTS)

    @staticmethod
    def _has_explicit_finance_query_cue(message: str) -> bool:
        normalized_message = " ".join(message.lower().split())
        if not LangGraphChatOrchestrator._is_non_transaction_query(normalized_message):
            return False
        query_starters = (
            "how much",
            "what did i",
            "where did i",
            "show ",
            "list ",
            "get ",
            "find ",
            "total ",
            "summarize ",
        )
        return normalized_message.startswith(query_starters) or any(
            term in normalized_message
            for term in ("spending", "spent", "transactions", "transaction history", "budget", "balance")
        )

    @staticmethod
    def _has_date_hint(message: str) -> bool:
        if "today" in message or "yesterday" in message:
            return True
        if "last week" in message or "last month" in message:
            return True
        if re.search(r"\b\d{1,3}\s+days?\s+ago\b", message):
            return True
        if re.search(r"\b\d{1,3}\s+weeks?\s+ago\b", message):
            return True
        if re.search(r"\b\d{1,3}\s+months?\s+ago\b", message):
            return True
        return bool(re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", message))

    @staticmethod
    def _has_candidate_date(candidate: dict[str, Any] | None) -> bool:
        if not isinstance(candidate, dict):
            return False

        occurred_at = candidate.get("occurred_at")
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
        normalized = " ".join(message.lower().split())
        if normalized in {"confirm", "yes", "y", "ok", "okay", "proceed", "log it"} or "confirm" in normalized:
            return "confirm_proposal"
        if normalized in {"cancel", "no", "discard", "stop"} or "cancel" in normalized or "discard" in normalized:
            return "cancel_proposal"
        if any(keyword in normalized for keyword in ("edit", "change", "instead", "make it", "update")):
            return "edit_proposal"
        if LangGraphChatOrchestrator._extract_amount_paise(message) is not None:
            return "edit_proposal"
        return None

    @staticmethod
    def _format_proposal_summary(proposal: dict[str, Any]) -> str:
        amount_inr = f"{int(proposal['amount_paise']) / 100:.2f}"
        merchant = proposal.get("merchant") or "merchant not provided"
        date_label = proposal["occurred_at"][:10]
        confidence_score = int(proposal.get("confidence_score", 0))
        details = f"merchant: {merchant}, date: {date_label}, confidence: {confidence_score}%"
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
        normalized_amount = str(value).replace(",", "").strip()
        try:
            amount_decimal = Decimal(normalized_amount)
        except InvalidOperation:
            return None

        amount_paise = int((amount_decimal * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if amount_paise <= 0:
            return None
        return amount_paise

    @staticmethod
    def _extract_merchant(message: str) -> str | None:
        match = _MERCHANT_PATTERN.search(message)
        if not match:
            return None

        merchant = match.group(1).strip(" .,!?;:")
        lowered = merchant.lower()

        for marker in (" today", " yesterday", " on ", " via ", " using "):
            marker_index = lowered.find(marker)
            if marker_index > 0:
                merchant = merchant[:marker_index].strip(" .,!?;:")
                break

        if not merchant:
            return None

        return merchant[:255]

    @staticmethod
    def _extract_message_from_prompt(prompt_value: Any) -> str:
        messages = getattr(prompt_value, "messages", [])
        if not messages:
            return ""
        return str(messages[-1].content)

    @staticmethod
    def _latest_user_message(messages: list[BaseMessage]) -> str:
        for item in reversed(messages):
            if isinstance(item, HumanMessage):
                return str(item.content)
        return ""

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
        return ""

    @staticmethod
    def _user_id_from_state(state: ChatGraphState) -> uuid.UUID:
        user_id_value = state.get("runtime_user_id")
        if not user_id_value:
            raise ValueError("Missing runtime_user_id in graph state")
        return uuid.UUID(str(user_id_value))

    @staticmethod
    def _validated_timezone_name(timezone_name: str | None) -> str:
        if not timezone_name:
            return "UTC"
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning("Invalid client timezone `%s`; using UTC.", timezone_name)
            return "UTC"
        return timezone_name

    @staticmethod
    def _as_guardrail_assessment(value: GuardrailAssessment | GuardrailDecision | str) -> GuardrailAssessment:
        if isinstance(value, GuardrailAssessment):
            return value
        if isinstance(value, GuardrailDecision):
            return GuardrailAssessment(decision=value, confidence=0.5, layer="semantic")
        normalized_value = str(value).strip().lower()
        for decision in GuardrailDecision:
            if decision.value == normalized_value:
                return GuardrailAssessment(decision=decision, confidence=0.5, layer="semantic")
        return GuardrailAssessment(decision=GuardrailDecision.BLOCK, confidence=0.5, layer="semantic")

    @staticmethod
    def _as_detected_intent(value: DetectedIntent | str) -> DetectedIntent:
        if isinstance(value, DetectedIntent):
            return value
        normalized_value = str(value).strip().lower()
        for intent in DetectedIntent:
            if intent.value == normalized_value:
                return intent
        return DetectedIntent.OFF_TOPIC
