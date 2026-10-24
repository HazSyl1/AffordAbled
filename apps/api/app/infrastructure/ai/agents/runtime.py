from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import InjectedState, ToolNode, tools_condition
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.complex_settlement import SettlementInput
from app.infrastructure.ai.agents.contracts import (
    HandoffContext,
    SpecialistDecision,
    SpecialistResult,
    ToolObservation,
    VerifiedTransactionReference,
)

logger = logging.getLogger(__name__)

ToolHandler = Callable[[HandoffContext, dict[str, Any]], Awaitable[dict[str, Any]]]


def merge_verified_transaction_references(
    existing: list[dict[str, Any]] | None, events: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Keep a bounded, validated record of transactions returned by successful tools."""
    references: dict[str, dict[str, Any]] = {}
    for raw in existing or []:
        try:
            reference = VerifiedTransactionReference.model_validate(raw)
        except (TypeError, ValueError):
            continue
        references[str(reference.id)] = reference.model_dump(mode='json')
    for event in events or []:
        if not isinstance(event, dict) or event.get('ok') is not True:
            continue
        if event.get('tool') not in {'create_transaction', 'create_transaction_batch'}:
            continue
        data = event.get('data') or {}
        if not isinstance(data, dict):
            continue
        transactions = (
            [data['transaction']]
            if isinstance(data.get('transaction'), dict)
            else data.get('transactions') or []
        )
        if not isinstance(transactions, list):
            continue
        for transaction in transactions:
            if not isinstance(transaction, dict):
                continue
            try:
                reference = VerifiedTransactionReference.model_validate({
                    'id': transaction.get('id'),
                    'source_request': event.get('request') or event.get('task'),
                    'amount_paise': transaction.get('amount_paise'),
                    'merchant': transaction.get('merchant'),
                    'task_id': event.get('task_id'),
                })
            except (TypeError, ValueError):
                continue
            key = str(reference.id)
            references.pop(key, None)
            references[key] = reference.model_dump(mode='json')
    return list(references.values())[-12:]


def _active_task_identity(state: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """Return the active durable task ID and contract, including legacy queue fallbacks."""
    queue = state.get("task_queue") or []
    active_text = str(queue[0]) if queue else str(state.get("task_request") or "")
    contracts = [item for item in state.get("task_contracts", []) if isinstance(item, dict)]
    active = next(
        (
            item
            for item in contracts
            if item.get("status") != "completed" and str(item.get("summary") or "") == active_text
        ),
        next((item for item in contracts if item.get("status") != "completed"), None),
    )
    return (str(active.get("id")) if active and active.get("id") else None, active)


def _is_single_bill_quantity_split(request: str) -> bool:
    """Keep a priced-per-person remainder split on the transaction-backed calculator."""
    text = request.casefold()
    return bool(
        re.search(r'\b\d+\b.{0,100}\beach\b', text)
        and re.search(r'\b(?:rest|remainder|remaining)\b', text)
        and not re.search(r'\b(?:discount|coupon|tip|fee|fees|multiple bills?|cafes?)\b', text)
    )


def _tool_error_message(exc: Exception) -> str:
    """Keep database diagnostics bounded and omit SQL parameter dumps."""
    first_line = (str(exc).splitlines() or [""])[0]
    return f"{type(exc).__name__}: {first_line}"[:600]


def _persistent_tool_context(state: dict[str, Any]) -> HandoffContext:
    """Build trusted handler context, preserving the conversation needed for follow-ups."""
    task_id, task_contract = _active_task_identity(state)
    return HandoffContext(
        user_id=state["user_id"],
        request=(state.get("task_queue") or [state["task_request"]])[0],
        history=(state.get("conversation_history") or [])[-20:],
        timezone=state.get("timezone", "UTC"),
        current_datetime=state.get("current_datetime"),
        constraints={
            "task_id": task_id,
            "task_contract": task_contract,
            "latest_user_reply": str(state["messages"][-1].content) if state.get("messages") else "",
            "last_transaction_window": state.get("last_transaction_window"),
            "original_request": state.get("task_request"),
            "created_transaction_ids": state.get("created_transaction_ids", []),
            "verified_transaction_references": state.get("verified_transaction_references", []),
            "prior_specialist_results": state.get("prior_results", []),
            "supervisor_handoff": state.get("handoff", {}),
            "pending_split_transaction_id": state.get("pending_split_transaction_id"),
            "available_categories": state.get("available_categories", []),
            "available_accounts": state.get("available_accounts", []),
            "available_split_contacts": state.get("available_split_contacts", []),
            "confirmed_memories": state.get("confirmed_memories", []),
            "memory_review_signal": state.get("memory_review_signal"),
        },
    )


class CreateAccountArguments(BaseModel):
    name: str = Field(min_length=1, max_length=120, description="Account name, for example Axis.")
    type: Literal["cash", "bank", "card", "wallet"] = Field(
        default="bank", description="Account kind. Use bank for a named bank account."
    )
    balance_rupees: Decimal = Field(default=Decimal("0"), ge=0, description="Initial balance in rupees, not paise.")
    currency: str = Field(default="INR", min_length=3, max_length=3)


class CreateAccountToolInput(BaseModel):
    arguments: CreateAccountArguments


class AccountIdArguments(BaseModel):
    account_id: str = Field(min_length=1, description='ID returned by list_accounts.')


class AccountIdToolInput(BaseModel):
    arguments: AccountIdArguments


class UpdateAccountArguments(AccountIdArguments):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class UpdateAccountToolInput(BaseModel):
    arguments: UpdateAccountArguments


class RenameAccountArguments(AccountIdArguments):
    name: str = Field(min_length=1, max_length=120, description='New account name.')


class RenameAccountToolInput(BaseModel):
    arguments: RenameAccountArguments


class CreateCategoryArguments(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["expense", "income"]


class CreateCategoryToolInput(BaseModel):
    arguments: CreateCategoryArguments


class UpdateCategoryArguments(BaseModel):
    category_id: str = Field(min_length=1, description='ID returned by list_categories.')
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: Literal['expense', 'income'] | None = None


class UpdateCategoryToolInput(BaseModel):
    arguments: UpdateCategoryArguments


class DeleteCategoryArguments(BaseModel):
    category_id: str = Field(min_length=1, description='ID returned by list_categories.')
    confirmed: bool = False


class DeleteCategoryToolInput(BaseModel):
    arguments: DeleteCategoryArguments


class CreateTransactionArguments(BaseModel):
    account_id: str = Field(min_length=1, description="ID returned by list_accounts.")
    type: Literal["expense", "income", "transfer"]
    amount_rupees: Decimal = Field(gt=0, description="Transaction amount in rupees, not paise.")
    category_id: str | None = Field(default=None, description="ID returned by list_categories.")
    to_account_id: str | None = None
    occurred_at: str | None = Field(default=None, description="ISO timestamp; omit to use the current time.")
    merchant: str | None = None
    note: str | None = None


class CreateTransactionToolInput(BaseModel):
    arguments: CreateTransactionArguments


class CreateTransactionBatchArguments(BaseModel):
    transactions: list[CreateTransactionArguments] = Field(min_length=1, max_length=10)


class CreateTransactionBatchToolInput(BaseModel):
    arguments: CreateTransactionBatchArguments


class UpdateTransactionArguments(BaseModel):
    transaction_id: str = Field(min_length=1, description='ID returned by list_transactions or get_transactions.')
    amount_paise: int | None = Field(default=None, gt=0, description='Corrected amount in paise.')
    merchant: str | None = Field(default=None, max_length=255)
    note: str | None = None


class UpdateTransactionToolInput(BaseModel):
    arguments: UpdateTransactionArguments


class TransactionIdArguments(BaseModel):
    transaction_id: str = Field(min_length=1, description='A verified user-owned transaction ID.')
    confirmed: bool = False


class TransactionIdToolInput(BaseModel):
    arguments: TransactionIdArguments


class SplitPersonArguments(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    share_paise: int = Field(default=0, ge=0)


class SplitItemArguments(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    amount_paise: int = Field(gt=0, description='Verified item or shared-charge amount in paise, not rupees.')
    shared_by: list[str] = Field(
        min_length=1, max_length=21, description='Names who shared this row; use me for owner.'
    )
    food_type: Literal['vegetarian', 'vegan', 'contains_meat', 'unknown', 'shared_charge'] = 'unknown'
    owner_excluded: bool = Field(
        default=False,
        description='True only when the user explicitly says the wallet owner did not share this row.',
    )


class QuantitySplitArguments(BaseModel):
    item_name: str = Field(default='Priced item', min_length=1, max_length=255,
                           description='Short item label for the reviewed allocation.')
    people: list[str] = Field(
        min_length=1, max_length=20, description='Named participants receiving this priced quantity.'
    )
    quantity_per_person: int = Field(gt=0, description='Number of items each named person received.')
    unit_price_rupees: Decimal = Field(gt=0, description='Price of one item in rupees; code converts to paise.')


class SplitDebtArguments(BaseModel):
    debtor: str = Field(min_length=1, max_length=100, description='Person who owes the other person.')
    creditor: str = Field(min_length=1, max_length=100, description='Person who should receive the debt.')
    amount_rupees: Decimal = Field(gt=0, description='Existing debt amount in rupees.')


class SplitContributionArguments(BaseModel):
    person: str = Field(min_length=1, max_length=100, description='Participant who already paid part of this bill.')
    amount_rupees: Decimal = Field(gt=0, description='Amount already contributed toward this bill, in rupees.')


class CreateSplitArguments(BaseModel):
    transaction_id: str | None = Field(default=None, description='Expense ID; omit for a newly recorded expense.')
    title: str | None = None
    mode: Literal['equal', 'custom'] = 'equal'
    participants: list[str | SplitPersonArguments] | None = None
    people: list[str | SplitPersonArguments] | None = None
    owner_share_paise: int | None = Field(default=None, ge=0)
    owner_share_rupees: Decimal | None = Field(default=None, ge=0)
    items: list[SplitItemArguments] | None = Field(
        default=None, max_length=20,
        description='Every verified receipt line and shared charge for an itemized split. Omit for equal splits.',
    )
    quantity_allocations: list[QuantitySplitArguments] | None = Field(
        default=None, min_length=1, max_length=50,
        description=(
            'Only for an explicit "N items each at X rupees per item; divide the rest equally" rule. '
            'For a total such as "1800 rupees of alcohol shared by A and B", use an items row instead. '
            'Supply names, quantity, and unit price; the tool calculates the remainder from the transaction.'
        ),
    )
    debts: list[SplitDebtArguments] | None = Field(
        default=None, max_length=50,
        description='Existing debts between the listed participants to include in the settlement plan.',
    )
    contributions: list[SplitContributionArguments] | None = Field(
        default=None, max_length=20,
        description='Amounts participants already paid toward this transaction; the owner paid the remainder.',
    )


class CreateSplitToolInput(BaseModel):
    arguments: CreateSplitArguments


class CreateOwedArguments(BaseModel):
    name: str = Field(min_length=1, max_length=100, description='Person who owes the authenticated user.')
    amount_paise: int = Field(gt=0, description='Amount they owe, in paise.')
    title: str | None = Field(default=None, max_length=255, description='Optional short reason for the debt.')


class CreateOwedToolInput(BaseModel):
    arguments: CreateOwedArguments


class CreateSettlementDraftArguments(BaseModel):
    data: SettlementInput = Field(description='Complete verified bills, charges, discounts, fees, payments, and debts.')


class CreateSettlementDraftToolInput(BaseModel):
    arguments: CreateSettlementDraftArguments


class SetSplitContactPreferenceArguments(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dietary_preference: Literal['vegetarian', 'vegan', 'omnivore'] | None = Field(
        description='Explicitly confirmed preference; null clears it. Never infer from one receipt.'
    )


class SetSplitContactPreferenceToolInput(BaseModel):
    arguments: SetSplitContactPreferenceArguments


class EmptyArgumentsToolInput(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class GetAccountBalancesArguments(BaseModel):
    account_names: list[str] | None = Field(
        default=None,
        description="Optional account names to filter by; omit to return balances for all accounts.",
    )
    account_types: list[Literal['cash', 'bank', 'card', 'wallet']] | None = Field(
        default=None, description='Optional account kinds to include.'
    )
    order_by: Literal['default', 'name', 'balance'] = Field(
        default='default', description='Use balance for richest/lowest-balance account questions.'
    )
    sort_order: Literal['asc', 'desc'] = Field(default='asc')
    limit: int = Field(default=25, ge=1, le=25)


class GetAccountBalancesToolInput(BaseModel):
    arguments: GetAccountBalancesArguments = Field(default_factory=GetAccountBalancesArguments)


class GetTransactionsArguments(BaseModel):
    mode: Literal['recent', 'previous_window', 'relative_range', 'date_range', 'all_time'] = Field(
        default='recent',
        description=(
            'recent for latest rows, previous_window for the period before the last query, '
            'relative_range for a period named in the request, date_range for explicit dates, '
            'or all_time for the full history.'
        ),
    )
    date_from: str | None = Field(default=None, description='Required only for date_range. Inclusive ISO start date.')
    date_to: str | None = Field(default=None, description='Required only for date_range. Inclusive ISO end date.')
    limit: int | None = Field(
        default=None, ge=1, le=25,
        description='Maximum rows. Omit to use 1 for a largest/smallest query and 10 otherwise.',
    )
    transaction_type: Literal['expense', 'income', 'transfer'] | None = Field(
        default=None, description='Filter transaction kind. Use expense when the user asks what they spent.'
    )
    category_name: str | None = Field(default=None, description='Optional exact user-owned category name.')
    account_name: str | None = Field(default=None, description='Optional exact active account name.')
    order_by: Literal['occurred_at', 'amount'] | None = Field(
        default=None, description='Use amount for largest, highest, smallest, or lowest transaction questions.'
    )
    sort_order: Literal['asc', 'desc'] | None = Field(
        default=None, description='Use desc for largest/highest and asc for smallest/lowest.'
    )


class GetTransactionsToolInput(BaseModel):
    arguments: GetTransactionsArguments = Field(default_factory=GetTransactionsArguments)


class SpendingWindowArguments(BaseModel):
    mode: Literal['relative_range', 'date_range', 'all_time'] = Field(
        default='relative_range',
        description='relative_range for a named period, date_range for explicit dates, or all_time.',
    )
    date_from: str | None = Field(
        default=None, description="Optional ISO start for an explicit range; omit for relative periods."
    )
    date_to: str | None = Field(
        default=None, description="Optional ISO end for an explicit range; omit for relative periods."
    )
    category_name: str | None = Field(
        default=None, description='Optional exact user-owned expense category name to filter.'
    )


class GetSpendingSummaryArguments(SpendingWindowArguments):
    limit: int = Field(default=5, ge=1, le=25, description='Maximum category rows to return.')
    order_by: Literal['amount', 'name'] = Field(default='amount', description='Category ranking field.')
    sort_order: Literal['asc', 'desc'] = Field(default='desc')


class GetSpendingSummaryToolInput(BaseModel):
    arguments: GetSpendingSummaryArguments = Field(default_factory=GetSpendingSummaryArguments)


class GetSpendingByAccountArguments(SpendingWindowArguments):
    limit: int = Field(default=10, ge=1, le=25, description='Maximum account rows to return.')
    account_names: list[str] | None = Field(
        default=None, description='For account breakdowns, optional exact account names to include.'
    )
    order_by: Literal['amount', 'transaction_count', 'name'] = Field(
        default='amount', description='Ranking field. transaction_count applies only to account breakdowns.'
    )
    sort_order: Literal['asc', 'desc'] = Field(default='desc')


class GetSpendingToolInput(BaseModel):
    arguments: GetSpendingByAccountArguments = Field(default_factory=GetSpendingByAccountArguments)


class GetSpendingComparisonArguments(BaseModel):
    date_period: Literal['this_week', 'this_month']
    comparison_period: Literal['last_week', 'last_month']
    category_name: str | None = Field(default=None, description='Optional exact expense category name.')


class GetSpendingComparisonToolInput(BaseModel):
    arguments: GetSpendingComparisonArguments


class GetSplitSummaryArguments(BaseModel):
    kind: Literal['all', 'expense_split', 'money_owed'] = 'all'
    status: Literal['all', 'outstanding', 'settled'] = 'all'
    person_name: str | None = Field(default=None, description='Optional participant name filter.')
    order_by: Literal['outstanding', 'created_at', 'title'] = 'outstanding'
    sort_order: Literal['asc', 'desc'] = 'desc'
    limit: int = Field(default=10, ge=1, le=25)


class GetSplitSummaryToolInput(BaseModel):
    arguments: GetSplitSummaryArguments = Field(default_factory=GetSplitSummaryArguments)


class CreateTransactionReportArguments(BaseModel):
    format: Literal["csv", "xlsx", "pdf"] = Field(default="pdf", description="Report file format.")
    date_from: str | None = Field(default=None, description="Inclusive local start date YYYY-MM-DD.")
    date_to: str | None = Field(default=None, description="Inclusive local end date YYYY-MM-DD.")


class CreateTransactionReportToolInput(BaseModel):
    arguments: CreateTransactionReportArguments = Field(default_factory=CreateTransactionReportArguments)


_TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "list_accounts": EmptyArgumentsToolInput,
    "list_categories": EmptyArgumentsToolInput,
    "list_transactions": EmptyArgumentsToolInput,
    "list_split_contacts": EmptyArgumentsToolInput,
    "extract_transaction": EmptyArgumentsToolInput,
    "delete_account": EmptyArgumentsToolInput,
    "get_current_datetime": EmptyArgumentsToolInput,
    "get_account_balances": GetAccountBalancesToolInput,
    "create_account": CreateAccountToolInput,
    "update_account": UpdateAccountToolInput,
    "rename_account": RenameAccountToolInput,
    "activate_account": AccountIdToolInput,
    "deactivate_account": AccountIdToolInput,
    "set_default_account": AccountIdToolInput,
    "create_category": CreateCategoryToolInput,
    "update_category": UpdateCategoryToolInput,
    "delete_category": DeleteCategoryToolInput,
    "create_transaction": CreateTransactionToolInput,
    "create_transaction_batch": CreateTransactionBatchToolInput,
    "update_transaction": UpdateTransactionToolInput,
    "delete_transaction": TransactionIdToolInput,
    "restore_transaction": TransactionIdToolInput,
    "create_split": CreateSplitToolInput,
    "create_owed": CreateOwedToolInput,
    "create_settlement_draft": CreateSettlementDraftToolInput,
    "set_split_contact_preference": SetSplitContactPreferenceToolInput,
    "get_transactions": GetTransactionsToolInput,
    "get_spending_summary": GetSpendingSummaryToolInput,
    "get_spending_by_account": GetSpendingToolInput,
    "get_spending_comparison": GetSpendingComparisonToolInput,
    "get_split_summary": GetSplitSummaryToolInput,
    "create_transaction_report": CreateTransactionReportToolInput,
}

_TOOL_DESCRIPTIONS = {
    "list_accounts": "Read user accounts and IDs before a transaction when an account is missing or ambiguous.",
    "create_account": "Create a user account when absent; supply name, type, and balance_rupees.",
    "update_account": "Update one existing user-owned account by account_id, such as its name or active status.",
    "rename_account": "Rename an existing user-owned account when explicitly requested.",
    "activate_account": "Activate one existing user-owned account so it can be used for transactions.",
    "deactivate_account": "Deactivate one existing user-owned account. Use only when the user explicitly requests it.",
    "set_default_account": "Set one existing user-owned account as the default for future transaction choices.",
    "delete_account": "Account deletion capability; use only if supported and report verified limitations.",
    "get_current_datetime": (
        "Read the trusted current date and time in the user's timezone, including the number of days left in the "
        "month. Use it for today, rest-of-month, deadline, and affordability calculations; never assume a date."
    ),
    "list_categories": "Read category IDs before choosing a transaction category or verifying a request.",
    "create_category": "Create an idempotent user-owned category with name and type: expense or income.",
    "update_category": "Update a user-owned category by category_id when its name or type should change.",
    "delete_category": "Delete one user-owned category only after explicit confirmation from the user.",
    "extract_transaction": "Extract fields from ambiguous transaction text or receipts; skip for clear requests.",
    "list_transactions": "Read user transactions for lookup requests; do not use to create or edit records.",
    "create_transaction": "Create one user transaction after resolving IDs; amount_rupees is in rupees.",
    "create_transaction_batch": (
        "Create multiple independent transactions only when the user explicitly requested them. Never use this to "
        "turn receipt line items into transactions; one receipt is one transaction for its grand total."
    ),
    "update_transaction": "Edit a user transaction by transaction_id when explicitly requested.",
    "delete_transaction": "Soft-delete one user-owned transaction only after explicit confirmation.",
    "restore_transaction": "Restore one previously deleted user-owned transaction when explicitly requested.",
    "get_account_balances": (
        "Read and rank current active account balances. Filter by exact account names or account types; use "
        "order_by=balance with desc for highest and asc for lowest. This tool does not read transaction history."
    ),
    "get_transactions": (
        "Read and rank user-owned transactions. For largest expense use transaction_type=expense, "
        "order_by=amount, sort_order=desc, and limit=1. Use relative_range for a named period, all_time when no "
        "period is given, recent for latest rows, previous_window for the prior page, or date_range for explicit "
        "dates. Use category_name and account_name for verified user-visible filters; never invent IDs."
    ),
    "get_spending_summary": (
        "Read and rank aggregate expense spending by category. Use relative_range for named periods, date_range "
        "with both ISO dates, or all_time. Filter by exact category_name; order by amount or name and set limit."
    ),
    "get_spending_by_account": (
        "Read and rank expense spending grouped by account. Use relative_range for named periods, date_range with "
        "both ISO dates, or all_time. Filter by account_names or category_name; order by amount, transaction_count, "
        "or name and set limit."
    ),
    "get_spending_comparison": (
        "Compare verified expense totals for this_week versus last_week or this_month versus last_month. An "
        "optional exact category_name limits both windows consistently."
    ),
    "get_split_summary": (
        "Read split and standalone receivable balances. Filter by kind, settled status, or participant; rank by "
        "outstanding amount, creation time, or title and set a bounded limit."
    ),
    "list_split_contacts": (
        "Read prior split names and explicitly confirmed dietary preferences. Preferences guide suggestions "
        "but never prove who ate a particular item."
    ),
    "set_split_contact_preference": (
        "Save or clear one user's confirmed dietary preference for a named split contact. Use only when the user "
        "explicitly states or approves that preference; never infer lasting memory from a receipt."
    ),
    "create_split": (
        "Create a split after its expense exists. For itemized receipts, supply every item with amount_paise, "
        "and use only amounts printed in the user's receipt/OCR; never invent a remaining-bill or residual row. "
        "shared_by names (use me for the owner). Never list the owner (me/myself/you) as a participant or ask "
        "what to call the owner; the owner's share is tracked separately. Include food_type. The tool calculates "
        "exact shares and asks the "
        "user to confirm before saving. Do not invent item prices or who ate an item."
        " For quantity and unit-price requests with the rest split equally, provide quantity_allocations; "
        "the tool calculates the remainder from the saved transaction. Provide a separate allocation for each "
        "item/group with different people, quantities, or prices. Include existing debts as debts and prior "
        "payments toward this bill as contributions; the tool calculates a separate net settlement plan."
    ),
    "create_owed": (
        "Record money a named person owes the authenticated user, even when there is no expense transaction. "
        "Use only when the user explicitly says someone owes/is to repay them; provide amount_paise and a reason. "
        "This is a receivable tracker entry, not an expense split and does not create a transaction."
    ),
    "create_settlement_draft": (
        "Calculate and save a review-only draft for a complex group settlement. Provide every bill and who paid it. "
        "No wallet transaction is created until the user confirms the draft in the planner. Do not invent missing "
        "bill amounts, allocations, fee bases, or coupon eligibility; ask_user first. If a single payer's quoted "
        "amount is before fee/discount, omit payment.amount_paise and the calculator derives the final payment. "
        "With multiple payers, use covered_charge_ids and covered_extra_ids to derive a payment from known "
        "item and tip rows; give referenced extras unique IDs. Keep promises separate from actual payments. "
        "Set discount.include_extras=true only when the coupon applies after fees/tips."
    ),
    "create_transaction_report": (
        "Generate a user-owned transaction report for download. Use for export or download requests; "
        "choose CSV, XLSX, or PDF and optional local date range."
    ),
}


class SpecialistBrain(Protocol):
    async def decide(
        self,
        context: HandoffContext,
        observations: list[ToolObservation],
    ) -> SpecialistDecision: ...


class SpecialistRuntime:
    """Bounded reason/act/observe loop with a capability-scoped tool registry."""

    def __init__(
        self,
        *,
        name: str,
        brain: SpecialistBrain,
        tools: dict[str, ToolHandler],
        max_iterations: int = 8,
        max_tool_retries: int = 3,
        timeout_seconds: float = 45,
        destructive_tools: set[str] | None = None,
        delegates: dict[str, ToolHandler] | None = None,
        allowed_actions: set[str] | None = None,
    ) -> None:
        self.name = name
        self.brain = brain
        self.tools = dict(tools)
        self.max_iterations = max(1, max_iterations)
        self.max_tool_retries = max(0, max_tool_retries)
        self.timeout_seconds = max(1.0, timeout_seconds)
        self.destructive_tools = destructive_tools or set()
        self.delegates = dict(delegates or {})
        self.allowed_actions = allowed_actions or {"call_tool", "ask_user", "delegate", "finish"}

    async def run(self, context: HandoffContext) -> SpecialistResult:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await self._run(context)
        except TimeoutError:
            return SpecialistResult(
                specialist=self.name, status="failed", summary="Specialist timed out.", errors=["specialist_timeout"]
            )

    async def _run(self, context: HandoffContext) -> SpecialistResult:
        observations: list[ToolObservation] = []
        actions_taken: list[dict[str, Any]] = []
        errors: list[str] = []
        for iteration in range(1, self.max_iterations + 1):
            decision = await self.brain.decide(context, observations)
            logger.info("agent.decision", extra={"agent": self.name, "iteration": iteration, "action": decision.action})
            if decision.action not in self.allowed_actions:
                error = f"action_not_permitted:{decision.action}"
                errors.append(error)
                observations.append(ToolObservation(tool="action_policy", ok=False, error=error))
                continue
            if decision.action == "finish":
                return SpecialistResult(
                    specialist=self.name,
                    status="partial" if errors else "success",
                    summary=decision.summary or "Completed.",
                    data=observations[-1].data if observations and observations[-1].ok else {},
                    actions_taken=actions_taken,
                    errors=errors,
                )
            if decision.action == "ask_user":
                if not decision.question:
                    errors.append("brain_requested_input_without_question")
                    continue
                answer = interrupt({
                    "agent": self.name,
                    "question": decision.question,
                    "memory_signal": decision.memory_signal,
                    "subject_hint": decision.memory_subject_hint,
                })
                observations.append(ToolObservation(tool="user_input", ok=True, data={"answer": str(answer)}))
                continue
            if decision.action == "delegate":
                delegate_name = decision.delegate_to or "unknown"
                handler = self.delegates.get(delegate_name)
                if handler is None:
                    errors.append(f"unsupported_delegate:{delegate_name}")
                    observations.append(ToolObservation(tool="delegate", ok=False, error=errors[-1]))
                    continue
                observation = await self._call_handler(context, f"delegate:{delegate_name}", handler, {})
                observations.append(observation)
                actions_taken.append({"delegate": delegate_name, "ok": observation.ok})
                if observation.error:
                    errors.append(observation.error)
                continue
            if decision.tool is None or decision.tool.name not in self.tools:
                error = f"tool_not_permitted:{decision.tool.name if decision.tool else 'missing'}"
                errors.append(error)
                observations.append(ToolObservation(tool="tool_registry", ok=False, error=error))
                continue

            tool_arguments = dict(decision.tool.arguments)
            if decision.tool.name in self.destructive_tools and tool_arguments.get("confirmed") is not True:
                answer = interrupt(
                    {
                        "agent": self.name,
                        "question": f"Please confirm that you want to {decision.tool.name.replace('_', ' ')}.",
                    }
                )
                if str(answer).strip().casefold() not in {"yes", "y", "confirm", "confirmed", "proceed"}:
                    observations.append(
                        ToolObservation(tool=decision.tool.name, ok=False, error="destructive_action_not_confirmed")
                    )
                    errors.append("destructive_action_not_confirmed")
                    continue
                tool_arguments["confirmed"] = True

            observation = await self._call_tool(context, decision.tool.name, tool_arguments)
            observations.append(observation)
            actions_taken.append({"tool": decision.tool.name, "ok": observation.ok})
            if observation.error:
                errors.append(observation.error)

        return SpecialistResult(
            specialist=self.name,
            status="failed",
            summary="Specialist iteration limit reached.",
            actions_taken=actions_taken,
            errors=[*errors, "iteration_limit"],
        )

    async def _call_tool(self, context: HandoffContext, name: str, arguments: dict[str, Any]) -> ToolObservation:
        return await self._call_handler(context, name, self.tools[name], arguments)

    async def _call_handler(
        self,
        context: HandoffContext,
        name: str,
        handler: ToolHandler,
        arguments: dict[str, Any],
    ) -> ToolObservation:
        started = time.perf_counter()
        for attempt in range(self.max_tool_retries + 1):
            try:
                data = await handler(context, arguments)
                logger.info(
                    "agent.tool",
                    extra={
                        "agent": self.name,
                        "tool": name,
                        "attempt": attempt + 1,
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                    },
                )
                return ToolObservation(tool=name, ok=True, arguments=arguments, data=data)
            except Exception as exc:  # tool failures are observations, not graph crashes
                if attempt == self.max_tool_retries:
                    return ToolObservation(tool=name, ok=False, error=_tool_error_message(exc))
        raise AssertionError("unreachable")


class ToolBoundSpecialistRuntime:
    """A specialist LLM that chooses only real LangChain tools via ToolNode."""

    def __init__(
        self,
        *,
        name: str,
        llm: Any,
        system_prompt: str,
        tools: dict[str, ToolHandler],
        allow_interrupts: bool = True,
        destructive_tools: set[str] | None = None,
        non_retryable_tools: set[str] | None = None,
        max_iterations: int = 8,
        max_tool_retries: int = 3,
        timeout_seconds: float = 45,
        db_session: AsyncSession | None = None,
        tool_lock: asyncio.Lock | None = None,
    ) -> None:
        self.name = name
        self.llm = llm
        self.system_prompt = system_prompt
        self.tools = dict(tools)
        self.allow_interrupts = allow_interrupts
        self.destructive_tools = destructive_tools or set()
        self.non_retryable_tools = non_retryable_tools or set()
        self.max_iterations = max_iterations
        self.max_tool_retries = max_tool_retries
        self.timeout_seconds = timeout_seconds
        self._db_session = db_session
        self._tool_lock = tool_lock or asyncio.Lock()

    async def _call_handler(
        self, context: HandoffContext, name: str, handler: ToolHandler, arguments: dict[str, Any]
    ) -> ToolObservation:
        # ToolNode may dispatch several calls from one model message at once.
        # All specialists in a request share one AsyncSession, which cannot be
        # used concurrently, even for a read beside a write.
        async with self._tool_lock:
            return await self._call_handler_serial(context, name, handler, arguments)

    async def _call_handler_serial(
        self, context: HandoffContext, name: str, handler: ToolHandler, arguments: dict[str, Any]
    ) -> ToolObservation:
        started = time.perf_counter()
        retry_limit = 0 if name in self.non_retryable_tools else self.max_tool_retries
        for attempt in range(retry_limit + 1):
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    data = await handler(context, arguments)
                logger.info(
                    "agent.tool",
                    extra={
                        "agent": self.name,
                        "tool": name,
                        "attempt": attempt + 1,
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                    },
                )
                return ToolObservation(tool=name, ok=True, data=data)
            except GraphBubbleUp:
                raise
            except Exception as exc:
                if self._db_session is not None:
                    try:
                        await self._db_session.rollback()
                    except Exception as rollback_exc:
                        return ToolObservation(
                            tool=name,
                            ok=False,
                            arguments=arguments,
                            error=_tool_error_message(rollback_exc),
                        )
                if isinstance(exc, ValueError) or attempt == retry_limit:
                    return ToolObservation(tool=name, ok=False, arguments=arguments, error=_tool_error_message(exc))
        raise AssertionError("unreachable")

    def _result_from_messages(self, messages: list[BaseMessage]) -> SpecialistResult:
        observations: list[ToolObservation] = []
        calls_by_id = {
            str(call.get("id")): call.get("args", {})
            for message in messages
            if isinstance(message, AIMessage)
            for call in message.tool_calls
        }
        for message in messages:
            if getattr(message, "type", "") != "tool":
                continue
            try:
                payload = json.loads(str(message.content))
                observations.append(
                    ToolObservation.model_validate(
                        {
                            "tool": message.name,
                            **payload,
                            "arguments": payload.get("arguments")
                            or calls_by_id.get(str(getattr(message, "tool_call_id", "")), {}),
                        }
                    )
                )
            except Exception:
                observations.append(ToolObservation(tool=message.name, ok=False, error="invalid_tool_observation"))
        errors = [item.error for item in observations if item.error]
        final = next((message for message in reversed(messages) if isinstance(message, AIMessage)), None)
        summary = str(final.content).strip() if final and final.content else "Completed."
        reached_limit = summary.startswith("SPECIALIST_ITERATION_LIMIT:")
        needs_input = summary.startswith("NEEDS_INPUT:")
        data = next((item.data for item in reversed(observations) if item.ok), {}).copy()
        created_transactions = [
            transaction
            for item in observations
            if item.ok and item.tool in {"create_transaction", "create_transaction_batch"}
            for transaction in (
                [item.data["transaction"]]
                if isinstance(item.data.get("transaction"), dict)
                else item.data.get("transactions", [])
            )
            if isinstance(transaction, dict) and transaction.get("id")
        ]
        if created_transactions:
            data["created_transactions"] = created_transactions
        observed_categories = [
            item.data["category"]
            for item in observations
            if item.ok and item.tool == "create_category" and isinstance(item.data.get("category"), dict)
        ]
        if observed_categories:
            data["observed_categories"] = observed_categories
        observed_actions = [
            {"tool": item.tool, "data": {} if item.tool.startswith("get_") else item.data}
            for item in observations
            if item.ok
            and item.tool
            in {
                "create_category",
                "list_categories",
                "update_category",
                "delete_category",
                "create_account",
                "list_accounts",
                "update_account",
                "rename_account",
                "activate_account",
                "deactivate_account",
                "set_default_account",
                "update_transaction",
                "list_transactions",
                "delete_transaction",
                "restore_transaction",
                "create_split",
                "create_owed",
                "create_settlement_draft",
                "set_split_contact_preference",
                "get_account_balances",
                "get_current_datetime",
                "get_transactions",
                "get_spending_summary",
                "get_spending_by_account",
                "get_spending_comparison",
                "get_split_summary",
                "create_transaction_report",
            }
        ]
        observed_actions.extend(
            {"tool": "create_transaction", "data": {"transaction": transaction}} for transaction in created_transactions
        )
        if observed_actions:
            data["observed_actions"] = observed_actions
        transaction_query = next(
            (item for item in reversed(observations) if item.ok and item.tool == "get_transactions"), None
        )
        if transaction_query and transaction_query.data.get("date_from") and transaction_query.data.get("date_to"):
            data["transaction_query_window"] = {
                "date_from": str(transaction_query.data["date_from"]),
                "date_to": str(transaction_query.data["date_to"]),
            }
        return SpecialistResult(
            specialist=self.name,
            status="failed" if reached_limit else "needs_input" if needs_input else "partial" if errors else "success",
            summary=summary.removeprefix("SPECIALIST_ITERATION_LIMIT:").removeprefix("NEEDS_INPUT:").strip(),
            data=data,
            actions_taken=[{"tool": item.tool, "ok": item.ok} for item in observations],
            tool_observations=[item.model_dump() for item in observations],
            errors=[*(["iteration_limit"] if reached_limit else []), *[error for error in errors if error]],
        )

    def initial_messages(self, context: HandoffContext) -> list[BaseMessage]:
        return [
            SystemMessage(
                content=(
                    f"{self.system_prompt}\n\nThe trusted handoff request is the active queued task. "
                    "Perform only that task or the supervisor's handoff needed to complete it. "
                    "Earlier conversation is context, not permission to execute other queued tasks. "
                    "Available categories and accounts in the handoff are user-scoped snapshots; "
                    "tool observations are authoritative for changes."
                )
            ),
            HumanMessage(content=f"Trusted handoff:\n{context.model_dump_json()}"),
        ]

    def build_persistent_subgraph(self, state_schema: type[Any]):
        """Build an attached subgraph; its ToolNode messages are parent-checkpointed."""
        tools = self._persistent_tools()
        model = self.llm.bind_tools(tools)
        quantity_split_model = (
            self.llm.bind_tools([tool for tool in tools if tool.name != "create_settlement_draft"])
            if self.name == "split" and "create_settlement_draft" in self.tools else None
        )

        async def agent(state: dict[str, Any]) -> dict[str, Any]:
            steps = int(state.get("specialist_steps", 0))
            messages = state.get("specialist_messages", [])
            if (
                self.name == "transaction"
                and state.get("pending_account_creation")
                and messages
                and getattr(messages[-1], "name", None) == "ask_user"
            ):
                # The transaction subgraph cannot create an account. Return to
                # the parent supervisor, which has queued account creation
                # before the original transaction.
                return Command(
                    graph=Command.PARENT,
                    update={"pending_account_creation": False},
                    goto="supervisor",
                )
            if steps >= self.max_iterations:
                return {
                    "specialist_messages": [
                        AIMessage(content="SPECIALIST_ITERATION_LIMIT: Specialist iteration limit reached.")
                    ],
                    "specialist_steps": steps,
                }
            if self.name == "analytics" and steps == 0:
                request = str(state.get("task_queue", [state.get("task_request", "")])[0]).casefold()
                tool_calls: list[dict[str, Any]] = []
                if "get_split_summary" in self.tools and re.search(
                    r"\b(?:owe|owed|remaining|outstanding|unpaid|splits?)\b", request
                ):
                    tool_calls.append(
                        {"name": "get_split_summary", "args": {"arguments": {}}, "id": "split-summary-intent"}
                    )
                needs_clock = bool(re.search(
                    r"\b(?:today|tonight|tomorrow|rest of (?:the )?month|days? left|end of (?:the )?month)\b",
                    request,
                ))
                if needs_clock and "get_current_datetime" in self.tools:
                    tool_calls.append(
                        {"name": "get_current_datetime", "args": {"arguments": {}}, "id": "current-time-intent"}
                    )
                if needs_clock and "get_account_balances" in self.tools and re.search(
                    r"\b(?:afford|budget|enough|spend|buy|purchase)\b", request
                ):
                    tool_calls.append(
                        {"name": "get_account_balances", "args": {"arguments": {}}, "id": "balance-intent"}
                    )
                if tool_calls:
                    return {
                        "specialist_messages": [
                            AIMessage(content="", tool_calls=tool_calls)
                        ],
                        "specialist_steps": steps + 1,
                    }
            active_model = model
            if quantity_split_model is not None and _is_single_bill_quantity_split(
                str(state.get("task_request") or "")
            ):
                active_model = quantity_split_model
            return {
                "specialist_messages": [await active_model.ainvoke(state["specialist_messages"])],
                "specialist_steps": steps + 1,
            }

        async def finish(state: dict[str, Any]) -> dict[str, Any]:
            result = self._result_from_messages(state.get("specialist_messages", []))
            task_id, _task_contract = _active_task_identity(state)
            result.task_id = task_id
            result.actions_taken = [
                {**action, "task_id": task_id}
                for action in result.actions_taken
            ]
            result.tool_observations = [
                {**observation, "task_id": task_id}
                for observation in result.tool_observations
            ]
            if isinstance(result.data.get("observed_actions"), list):
                result.data["observed_actions"] = [
                    {**action, "task_id": task_id}
                    for action in result.data["observed_actions"]
                ]
            updates: dict[str, Any] = {"results": [*state.get("results", []), result.model_dump()]}
            active_task = (state.get("task_queue") or [state.get("task_request", "")])[0]
            prior_events = state.get("tool_event_history") or []
            new_events = [
                {
                    **observation,
                    "task_id": task_id,
                    "specialist": self.name,
                    "task": active_task,
                    "request": state.get("task_request", ""),
                    "created_at": datetime.now(UTC).isoformat(),
                }
                for observation in result.tool_observations
            ]
            if new_events:
                updates["tool_event_history"] = [*prior_events, *new_events][-100:]
                updates["verified_transaction_references"] = merge_verified_transaction_references(
                    state.get("verified_transaction_references"), new_events,
                )
            if self.name == "analytics" and result.data.get("transaction_query_window"):
                updates["last_transaction_window"] = result.data["transaction_query_window"]
            return updates

        graph = StateGraph(state_schema)
        graph.add_node("agent", agent)
        graph.add_node("tools", ToolNode(tools, messages_key="specialist_messages"))
        graph.add_node("finish", finish)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges(
            "agent",
            lambda state: tools_condition(state, messages_key="specialist_messages"),
            {"tools": "tools", END: "finish"},
        )
        graph.add_edge("tools", "agent")
        graph.add_edge("finish", END)
        return graph.compile()

    def _persistent_tools(self) -> list[StructuredTool]:
        tools: list[StructuredTool] = []
        for name, handler in self.tools.items():
            tools.append(self._persistent_tool(name, handler))
        if self.allow_interrupts:

            async def ask_user(
                question: str,
                memory_signal: Literal[
                    "category_mapping", "account_mapping", "preference", "split_preference",
                ] | None = None,
                subject_hint: str | None = None,
            ) -> str:
                """Ask one question. Mark memory_signal for reusable preference clarifications, not missing fields."""
                return json.dumps({"ok": True, "answer": str(interrupt({
                    "agent": self.name,
                    "question": question,
                    "memory_signal": memory_signal,
                    "subject_hint": subject_hint,
                }))})

            tools.append(
                StructuredTool.from_function(coroutine=ask_user, name="ask_user", description=ask_user.__doc__ or "")
            )
        return tools

    def _persistent_tool(self, name: str, handler: ToolHandler) -> StructuredTool:
        """Create one tool with only model-visible arguments in its schema."""

        async def execute(arguments: dict[str, Any], state: Annotated[dict[str, Any], InjectedState]) -> str:
            context = _persistent_tool_context(state)
            values = arguments.model_dump() if isinstance(arguments, BaseModel) else {
                key: value.model_dump() if isinstance(value, BaseModel) else value
                for key, value in arguments.items()
            }
            if name in self.destructive_tools and values.get("confirmed") is not True:
                answer = interrupt(
                    {"agent": self.name, "question": f"Please confirm that you want to {name.replace('_', ' ')}."}
                )
                if str(answer).strip().casefold() not in {"yes", "y", "confirm", "confirmed", "proceed"}:
                    return json.dumps({"ok": False, "error": "destructive_action_not_confirmed"})
                values["confirmed"] = True
            observation = await self._call_handler(context, name, handler, values)
            return json.dumps(observation.model_dump(), default=str)

        return StructuredTool.from_function(
            coroutine=execute,
            name=name,
            description=_TOOL_DESCRIPTIONS.get(name, f"{name} for {self.name}."),
            args_schema=_TOOL_SCHEMAS.get(name),
        )
