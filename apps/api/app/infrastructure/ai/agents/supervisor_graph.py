from __future__ import annotations

import asyncio
import re
import uuid
from collections import Counter
from collections.abc import Mapping
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES, RemoveMessage, add_messages
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.account_service import AccountService
from app.application.services.category_service import CategoryService
from app.application.services.export_service import ExportService
from app.application.services.split_service import SplitService
from app.application.services.transaction_service import TransactionService
from app.domain.ports import ChatTurnResult, GuardrailDecision, SemanticGuardrail
from app.infrastructure.ai.agents.account import AccountToolset
from app.infrastructure.ai.agents.analytics import AnalyticsToolset
from app.infrastructure.ai.agents.brains import StructuredSupervisorBrain
from app.infrastructure.ai.agents.category import CategoryToolset
from app.infrastructure.ai.agents.contracts import HandoffContext, SupervisorDecision
from app.infrastructure.ai.agents.export import ExportToolset
from app.infrastructure.ai.agents.extraction import TransactionExtractionAgent
from app.infrastructure.ai.agents.prompts import (
    ACCOUNT_PROMPT,
    ANALYTICS_PROMPT,
    CATEGORY_PROMPT,
    EXPORT_PROMPT,
    FORMATTING_PROMPT,
    SPLIT_PROMPT,
    SUPERVISOR_PROMPT,
    TRANSACTION_PROMPT,
)
from app.infrastructure.ai.agents.runtime import ToolBoundSpecialistRuntime
from app.infrastructure.ai.agents.split import SplitToolset
from app.infrastructure.ai.agents.transaction import TransactionToolset
from app.infrastructure.ai.tools.transaction_query_tools import TransactionQueryTools
from app.infrastructure.database.repositories.sqlalchemy_memory_repository import SqlAlchemyMemoryRepository

_MAX_REROUTES = 3
_MUTATION_TOOLS = {
    "create_category",
    "update_category",
    "delete_category",
    "create_account",
    "update_account",
    "rename_account",
    "activate_account",
    "deactivate_account",
    "set_default_account",
    "create_transaction",
    "update_transaction",
    "delete_transaction",
    "restore_transaction",
    "create_split",
    "create_owed",
    "set_split_contact_preference",
}


def _split_task_for_request(request: str) -> str | None:
    normalized = request.casefold()
    # Receipt workflow instructions mention splitting as a later optional step;
    # those words are not consent to queue a split with the original transaction.
    if (
        re.search(r"\b(?:do not|don't|never)\b.{0,60}\bsplit\b", normalized)
        or re.search(r"\bask\s+(?:me\s+)?whether\b.{0,80}\bsplit\b", normalized)
        or re.search(r"\bonly after\b.{0,60}\b(?:agree|confirm)\b", normalized)
    ):
        return None
    has_split_context = re.search(
        r"\b(?:split|shared|with|divid(?:e|ed|ing)|remainder|remaining\s+(?:bill|amount|balance))\b",
        normalized,
    )
    has_transaction = re.search(r"\b(?:spent|spend|paid|pay|expense|transaction)\b", normalized)
    if not (has_split_context and has_transaction):
        return None
    if not re.search(r"\b(?:with|split|shared|divid(?:e|ed|ing)|remainder)\b", normalized):
        return None
    match = re.search(r"\bwith\s+(.+?)(?:\s+for\s+me)?(?:[.!?]|$)", request, re.IGNORECASE)
    names = match.group(1).strip() if match else "the named people"
    split_kind = 'itemized' if (
        not re.search(r'\b(?:equal|equally)\b', normalized)
        and re.search(r'\b(?:by item|itemized|had|ate|ordered|shared the)\b', normalized)
    ) else 'equal'
    return (
        f"create an {split_kind} split for the transaction just recorded with participants {names}. "
        f"Full original request: {request}"
    )


def _with_verified_split_total(task: str, transaction: Mapping[str, Any]) -> str:
    """Carry the database-confirmed amount into the pending split handoff."""
    amount_paise = transaction.get("amount_paise")
    if amount_paise is None:
        return task
    try:
        amount_paise = int(amount_paise)
    except (TypeError, ValueError):
        return task
    rupees, paise = divmod(amount_paise, 100)
    verified_total = f"Verified recorded transaction total: ₹{rupees:,}.{paise:02d}."
    task_without_total = re.sub(
        r"\s*Verified recorded transaction total: ₹[\d,]+\.\d{2}\.", "", task,
        flags=re.IGNORECASE,
    ).strip()
    return f"{task_without_total} {verified_total}"


def _canonicalize_split_task_queue(task_queue: list[str], original_request: str) -> list[str]:
    """Keep one split task tied to the full request, not lossy or duplicate LLM paraphrases."""
    split_task = _split_task_for_request(original_request)
    if not split_task:
        return task_queue
    canonical_queue = list(task_queue)
    transaction_task_index = next(
        (index for index, task in enumerate(canonical_queue) if _obvious_specialist(task) == "transaction"),
        None,
    )
    if transaction_task_index is None:
        canonical_queue.insert(0, original_request)
    else:
        # Keep the full source on the transaction task too; a terse supervisor
        # paraphrase can drop amount, merchant, or other required details.
        canonical_queue[transaction_task_index] = original_request
    split_task_indices = [
        index for index, task in enumerate(canonical_queue)
        if _required_tools(task, "split") == {"create_split"}
    ]
    if not split_task_indices:
        canonical_queue.append(split_task)
    else:
        # The model may compress or duplicate split tasks, sometimes treating
        # a remainder as a new bill. Rebuild the first from the original user
        # request and discard the other create_split tasks for this transaction.
        first_split_index = split_task_indices[0]
        canonical_queue = [
            task for index, task in enumerate(canonical_queue)
            if index not in split_task_indices or index == first_split_index
        ]
        canonical_queue[first_split_index] = split_task
    return canonical_queue


def _is_elaboration_followup(message: str) -> bool:
    return bool(
        re.search(
            r"^(?:please\s+)?(?:elaborate(?:\s+more)?|explain(?:\s+more)?|expand(?:\s+on\s+that)?|"
            r"tell\s+me\s+more|break\s+(?:it|that)\s+down|more\s+details)(?:[.!?\s]|$)",
            message.strip(),
            flags=re.IGNORECASE,
        )
    )


def _explicit_action_clauses(request: str) -> list[str]:
    """Preserve separate actions when the model omits one from its first task list."""
    clauses = [part.strip() for part in re.split(r"\s+and\s+", request, flags=re.IGNORECASE)]
    action_start = (
        r"^(?:please\s+)?(?:show|list|display|compare|create|add|record|log|pay|spend|"
        r"transfer|delete|remove|update|rename|set)\b"
    )
    return (
        clauses
        if len(clauses) > 1 and all(re.search(action_start, clause, re.IGNORECASE) for clause in clauses)
        else []
    )


def _mentions(task: str, value: str) -> bool:
    return bool(value and re.search(rf"(?<!\w){re.escape(value.casefold())}(?!\w)", task.casefold()))


def _matches_observed_action(task: str, action: dict[str, Any]) -> bool:
    """Match one queued creation to one verified tool result, never to a model claim."""
    tool = action.get("tool")
    data = action.get("data") or {}
    normalized_task = task.casefold()
    if tool == "list_categories":
        return "categor" in normalized_task and any(
            _mentions(task, word) for word in ("list", "show", "view", "what", "which")
        )
    if tool == "list_accounts":
        return any(_mentions(task, word) for word in ("account", "accounts", "bank", "wallet")) and any(
            _mentions(task, word) for word in ("list", "show", "view", "what", "which")
        )
    if tool == "list_transactions":
        return any(_mentions(task, word) for word in ("transaction", "transactions", "history")) and any(
            _mentions(task, word) for word in ("list", "show", "view", "what", "which")
        )
    if tool in {"create_category", "update_category", "delete_category"}:
        category = data.get("category") or {}
        category_type = str(category.get("type") or "").casefold()
        verbs = {
            "create_category": ("create", "add", "new"),
            "update_category": ("update", "rename", "change"),
            "delete_category": ("delete", "remove"),
        }[tool]
        return (
            "category" in normalized_task
            and any(_mentions(task, word) for word in verbs)
            and _mentions(task, str(category.get("name") or ""))
            and not ("expense category" in normalized_task and category_type != "expense")
            and not ("income category" in normalized_task and category_type != "income")
        )
    if tool in {
        "create_account",
        "update_account",
        "rename_account",
        "activate_account",
        "deactivate_account",
        "set_default_account",
    }:
        account = data.get("account") or {}
        verbs = {
            "create_account": ("create", "add", "open", "new"),
            "update_account": ("update", "rename", "change", "activate", "deactivate"),
            "rename_account": ("rename", "change"),
            "activate_account": ("activate",),
            "deactivate_account": ("deactivate",),
            "set_default_account": ("default",),
        }[tool]
        return (
            any(_mentions(task, word) for word in verbs)
            and (
                tool in {"set_default_account", "activate_account", "deactivate_account"}
                or any(_mentions(task, word) for word in ("account", "bank", "wallet", "cash"))
            )
            and _mentions(task, str(account.get("name") or ""))
            and not (
                tool == "create_account"
                and any(_mentions(task, kind) for kind in ("bank", "wallet", "cash"))
                and not _mentions(task, str(account.get("type") or ""))
            )
        )
    if tool == "restore_transaction":
        return _mentions(task, "restore") and _mentions(task, str(data.get("restored_transaction_id") or ""))
    if tool in {"create_transaction", "update_transaction", "delete_transaction"}:
        transaction = data.get("transaction") or {}
        amount_paise = transaction.get("amount_paise")
        amount_variants = set()
        if isinstance(amount_paise, int):
            amount = f"{amount_paise // 100}.{amount_paise % 100:02d}"
            amount_variants = {amount, amount.rstrip("0").rstrip(".")}
        merchant = str(transaction.get("merchant") or "").strip()
        verbs = {
            "create_transaction": (
                "spend",
                "spent",
                "pay",
                "paid",
                "record",
                "log",
                "transaction",
                "transfer",
                "transferred",
                "receive",
                "received",
                "deposit",
                "deposited",
                "withdraw",
                "withdrew",
            ),
            "update_transaction": ("update", "edit", "change"),
            "delete_transaction": ("delete", "remove"),
        }[tool]
        if not any(_mentions(task, word) for word in verbs):
            return False
        transaction_type = str(transaction.get("type") or "")
        if (
            tool == "create_transaction"
            and any(_mentions(task, word) for word in ("transfer", "transferred"))
            and transaction_type != "transfer"
        ):
            return False
        has_amount = bool(re.search(r"(?<!\w)\d+(?:\.\d{1,2})?(?!\w)", task))
        amount_matches = any(
            re.search(rf"(?<![\d.]){re.escape(value)}(?![\d.])", normalized_task) for value in amount_variants
        )
        id_matches = _mentions(task, str(transaction.get("id") or ""))
        merchant_matches = bool(merchant and _mentions(task, merchant))
        identified = (
            amount_matches or id_matches or (tool != "create_transaction" and merchant_matches and not has_amount)
        )
        task_mentions_merchant = bool(merchant and _mentions(task, merchant))
        return identified and (id_matches or not task_mentions_merchant or merchant_matches)
    if tool == "set_split_contact_preference":
        contact = data.get('contact') or {}
        return _mentions(task, str(contact.get('name') or '')) and any(
            _mentions(task, word)
            for word in ('remember', 'vegetarian', 'vegan', 'omnivore', 'dietary', 'veg', 'meat', 'nonveg')
        )
    if tool == "create_split":
        split = data.get("split") or {}
        return "split" in normalized_task and (
            _mentions(task, str(split.get("title") or ""))
            or any(_mentions(task, str(person.get("name") or "")) for person in split.get("participants", []))
        )
    if tool == "create_owed":
        receivable = data.get('receivable') or {}
        return (
            any(_mentions(task, word) for word in ('owe', 'owes', 'owed', 'repay me', 'pay me'))
            and _mentions(task, str(receivable.get('person') or ''))
        )
    if tool == "get_account_balances":
        return any(_mentions(task, word) for word in ("balance", "balances"))
    if tool == "get_transactions":
        return any(
            _mentions(task, word)
            for word in ("transaction", "transactions", "history", "before", "earlier", "prior", "previous")
        )
    if tool == "get_spending_comparison":
        return any(_mentions(task, word) for word in ("compare", "comparison", "versus", "vs"))
    if tool == "get_split_summary":
        return any(_mentions(task, word) for word in ("owe", "owed", "remaining", "outstanding", "split", "people"))
    if tool == "get_spending_by_account":
        return "account" in normalized_task and any(
            _mentions(task, word) for word in ("spending", "spent", "breakdown")
        )
    if tool == "get_spending_summary":
        return any(_mentions(task, word) for word in ("spending", "spend", "spent")) and any(
            _mentions(task, word) for word in ("summary", "total", "much")
        )
    if tool == "create_transaction_report":
        return bool(data.get("export_id")) and any(
            _mentions(task, word) for word in ("export", "download", "report")
        )
    return False


def _remaining_after_observations(task_queue: list[str], observed_actions: list[dict[str, Any]]) -> list[str]:
    """Consume each task only when it has its own matching tool observation."""
    unused_actions = list(observed_actions)
    remaining: list[str] = []
    for task in task_queue:
        match = next(
            (index for index, action in enumerate(unused_actions) if _matches_observed_action(task, action)),
            None,
        )
        if match is None:
            remaining.append(task)
        else:
            unused_actions.pop(match)
    return remaining


def _reconcile_task_queue(
    task_queue: list[str],
    observed_actions: list[dict[str, Any]],
    *,
    original_request: str,
    latest_reply: str,
    available_categories: list[dict[str, Any]],
    verify_categories: bool,
) -> tuple[list[str], list[str]]:
    """Use fresh category state for idempotent creates and tool evidence for other tasks."""
    remaining = (
        [
            task
            for task in task_queue
            if not _category_creation_satisfied(task, original_request, latest_reply, available_categories)
        ]
        if verify_categories
        else list(task_queue)
    )
    matching_actions = (
        [action for action in observed_actions if action.get("tool") != "create_category"]
        if verify_categories
        else observed_actions
    )
    remaining = _remaining_after_observations(remaining, matching_actions)
    remaining_counts = Counter(remaining)
    satisfied: list[str] = []
    for task in task_queue:
        if remaining_counts[task]:
            remaining_counts[task] -= 1
        else:
            satisfied.append(task)
    return remaining, satisfied


def _verified_queue_is_complete(
    task_queue: list[str],
    result: dict[str, Any],
    *,
    original_request: str,
    latest_reply: str,
    available_categories: list[dict[str, Any]],
) -> bool:
    """Allow the graph to finish without a second supervisor call only on tool evidence."""
    if not task_queue or result.get("status") != "success":
        return False
    observed_actions = (result.get("data") or {}).get("observed_actions") or []
    if not observed_actions:
        return False
    remaining, _ = _reconcile_task_queue(
        task_queue,
        observed_actions,
        original_request=original_request,
        latest_reply=latest_reply,
        available_categories=available_categories,
        verify_categories=result.get("specialist") == "category",
    )
    return not remaining


def _required_tools(task: str, specialist: str | None) -> set[str] | None:
    def says(*words: str) -> bool:
        return any(_mentions(task, word) for word in words)

    if specialist == "category":
        if says("create", "add", "new"):
            return {"create_category"}
        if says("rename", "update", "change"):
            return {"update_category"}
        if says("delete", "remove"):
            return {"delete_category"}
    if specialist == "account":
        if says("create", "add", "open", "new"):
            return {"create_account"}
        if says("default"):
            return {"set_default_account"}
        if says("deactivate"):
            return {"deactivate_account", "update_account"}
        if says("activate"):
            return {"activate_account", "update_account"}
        if says("rename", "update", "change"):
            return {"rename_account", "update_account"}
        if says("delete", "remove"):
            return {"delete_account"}
    if specialist == "transaction":
        if says("delete", "remove"):
            return {"delete_transaction"}
        if says("restore"):
            return {"restore_transaction"}
        if says("update", "edit", "change"):
            return {"update_transaction"}
        if says(
            "spend",
            "spent",
            "pay",
            "paid",
            "record",
            "log",
            "create",
            "add",
            "transfer",
            "transferred",
            "receive",
            "received",
            "deposit",
            "deposited",
            "withdraw",
            "withdrew",
        ):
            return {"create_transaction", "create_transaction_batch"}
    if specialist == "split":
        if says('owe', 'owes', 'owed', 'pay me', 'repay me') and not says('split', 'shared', 'participants'):
            return {"create_owed"}
        if says("split", "shared", "participants") and not says('remember', 'save preference'):
            return {"create_split"}
        if says('remember', 'dietary', 'vegetarian', 'vegan', 'omnivore', 'veg', 'meat', 'nonveg'):
            return {'set_split_contact_preference'}
    if specialist == "export":
        return {"create_transaction_report"}
    return None


def _obvious_specialist(task: str) -> str | None:
    """Keep an actionable first turn from being finished before any tool runs."""
    normalized = task.casefold()
    wants_report_file = any(
        _mentions(task, word) for word in ("export", "download", "csv", "xlsx", "excel", "pdf")
    )
    if wants_report_file and any(
        _mentions(task, word)
        for word in ("transaction", "transactions", "report", "spending", "expenses", "history")
    ):
        return "export"
    if re.search(r"\b(?:create|make|prepare|calculate)\b.{0,40}\bsplit\b", normalized):
        return "split"
    if re.search(r"\b(?:record|log|add)\b.{0,30}\b(?:expense|transaction|purchase)\b", normalized):
        return "transaction"
    if re.search(r"\b(?:\w+)\s+(?:owes|owed)\s+me\b|\b(?:owe|pay)\s+me\s+\d", normalized):
        return "split"
    if "split" in normalized and not re.search(r"\b(?:spent|spend|paid|pay|record|log)\b", normalized):
        return "split"
    if re.search(r'\b(?:remember|save)\b', normalized) and re.search(
        r'\b(?:vegetarian|vegan|omnivore|dietary|veg|meat|non-?veg)\b', normalized
    ):
        return 'split'
    if re.search(r'\b\w+\s+(?:is|eats)\s+(?:vegetarian|vegan|omnivore|veg|non-?veg|meat)\b', normalized):
        return 'split'
    if any(_mentions(task, word) for word in ("balance", "balances")):
        return "analytics"
    if re.search(r"\bcategor(?:y|ies)\b", normalized) and any(
        _mentions(task, word)
        for word in ("create", "add", "new", "rename", "update", "delete", "remove", "list", "show")
    ):
        return "category"
    if any(_mentions(task, word) for word in ("account", "bank", "wallet")) and any(
        _mentions(task, word)
        for word in (
            "create",
            "add",
            "open",
            "new",
            "rename",
            "update",
            "delete",
            "remove",
            "activate",
            "deactivate",
            "default",
            "list",
            "show",
        )
    ):
        return "account"
    if re.search(r"(?<!\w)\d+(?:\.\d{1,2})?(?!\w)", normalized) and any(
        _mentions(task, word)
        for word in (
            "spend",
            "spent",
            "pay",
            "paid",
            "record",
            "log",
            "transfer",
            "transferred",
            "receive",
            "received",
            "deposit",
            "deposited",
            "withdraw",
            "withdrew",
        )
    ):
        return "transaction"
    if any(_mentions(task, word) for word in ("balance", "balances", "history", "transactions", "spending")):
        return "analytics"
    if any(_mentions(task, word) for word in ("owe", "owed", "remaining", "outstanding", "splits")):
        return "analytics"
    if any(_mentions(task, word) for word in ("spend", "spent")) and any(
        _mentions(task, word) for word in ("how", "much", "compare", "total")
    ):
        return "analytics"
    return None


def _fast_route_specialist(task: str) -> str | None:
    """Return a high-confidence route only for a clearly single-domain request."""
    if _explicit_action_clauses(task) or _split_task_for_request(task) or _is_receipt_upload_request(task):
        return None
    # Keep connectors that often indicate separate work on the LLM planning path.
    if re.search(r"\b(?:then|after that|also)\b", task, flags=re.IGNORECASE):
        return None

    specialist = _obvious_specialist(task)
    if specialist == "account" and any(
        _mentions(task, word)
        for word in ("transaction", "transactions", "history", "spending", "spent", "balance", "balances")
    ):
        # “Show transactions from my Axis account” is analytics, not account management.
        return None
    return specialist


def _is_receipt_upload_request(request: str) -> bool:
    """Identify the generated first-stage receipt task, before split consent."""
    normalized = request.casefold()
    return (
        "i uploaded a receipt/bill image" in normalized
        and "not consent to split it" in normalized
        and "after the expense is successfully logged" in normalized
    )


def _category_creation_satisfied(
    task: str,
    original_request: str,
    latest_reply: str,
    available_categories: list[dict[str, Any]],
) -> bool:
    """Verify every named category in a create task against current user data."""
    if not any(_mentions(task, word) for word in ("create", "add", "new")):
        return False
    if not re.search(r"\bcategor(?:y|ies)\b", task.casefold()) and not re.search(
        r"\bcategor(?:y|ies)\b", original_request.casefold()
    ):
        return False

    quoted_names = re.findall(r'["“]([^"”]+)["”]', original_request)
    names = [name.strip() for name in quoted_names if _mentions(task, name.strip())]
    if not names:
        match = re.search(
            r"\b(?:create|add)\s+(?:(?:a|an|the|new)\s+)*(?:(?:expense|income)\s+)?"
            r"categor(?:y|ies)\s+(.+?)\s*$",
            task,
            flags=re.IGNORECASE,
        )
        if match:
            names = [part.strip().strip('"') for part in re.split(r"\s+and\s+|,", match.group(1))]
    if not names:
        match = re.search(
            r"\b(?:create|add)\s+(.+?)\s+(?:(?:are|as)\s+)?(?:(?:an?|the)\s+)?"
            r"(?:(?:expense|income)\s+)?categor(?:y|ies)\b",
            task,
            flags=re.IGNORECASE,
        )
        if match:
            names = [part.strip(' \t\r\n"“”') for part in re.split(r"\s+and\s+|,", match.group(1))]
        elif " and " not in task.casefold():
            names = [
                str(category["name"])
                for category in available_categories
                if _mentions(task, str(category.get("name") or ""))
            ]
    names = [name for name in names if name]
    if not names:
        return False

    task_expense = bool(re.search(r"\bexpense\s+categor(?:y|ies)\b", task.casefold()))
    task_income = bool(re.search(r"\bincome\s+categor(?:y|ies)\b", task.casefold()))
    reply_expense = _mentions(latest_reply, "expense")
    reply_income = _mentions(latest_reply, "income")
    original_expense = bool(re.search(r"\bexpense\s+categor(?:y|ies)\b", original_request.casefold()))
    original_income = bool(re.search(r"\bincome\s+categor(?:y|ies)\b", original_request.casefold()))
    if task_expense != task_income:
        expense_requested, income_requested = task_expense, task_income
    elif reply_expense != reply_income:
        expense_requested, income_requested = reply_expense, reply_income
    else:
        expense_requested, income_requested = original_expense, original_income
    category_type: str | None
    if expense_requested != income_requested:
        category_type = "expense" if expense_requested else "income"
    elif re.search(r"\b(?:spend|spent|pay|paid|purchase|purchased|buy|bought|expense)\b", original_request, re.I):
        category_type = "expense"
    elif re.search(r"\b(?:receive|received|earn|earned|deposit|deposited|income)\b", original_request, re.I):
        category_type = "income"
    else:
        # If the user omitted a type and there is no transaction context to
        # infer one from, an exact existing name is enough for idempotency.
        category_type = None
    return all(
        any(
            str(category.get("name") or "").casefold() == name.casefold()
            and (category_type is None or str(category.get("type") or "").casefold() == category_type)
            for category in available_categories
        )
        for name in names
    )


def _is_category_clarification(message: str) -> bool:
    normalized = message.casefold()
    return "categor" in normalized and any(
        phrase in normalized for phrase in ("which", "what", "choose", "use", "available", "should i")
    )


def _category_reply_memory_signal(
    *, pending_question: str, pending_task: str, reply: str, specialist_for_task=_obvious_specialist,
) -> dict[str, str] | None:
    """Tag an explicit answer to a transaction's category clarification for async review.

    This is deterministic fallback metadata: relying only on the model to add the
    optional ask_user tool fields caused valid category answers to be lost when
    the transaction was resumed and saved.
    """
    if not _is_category_clarification(pending_question):
        return None
    if specialist_for_task(pending_task) != "transaction":
        return None
    normalized_reply = reply.strip().casefold()
    if not normalized_reply or re.fullmatch(
        r"(?:no|nope|nah|cancel|skip|never mind|nevermind|don't|do not)[.! ]*", normalized_reply,
    ):
        return None
    return {"signal_type": "category_mapping"}


def _last_assistant_reply(history: list[dict[str, str]]) -> str:
    return next((item.get("content", "") for item in reversed(history) if item.get("role") == "assistant"), "")


def _append_conversation_history(
    current: list[dict[str, str]] | None,
    update: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    """Merge transcript snapshots, tolerating concurrent and stale subgraph updates."""
    existing = current or []
    incoming = update or []
    # Attached specialist subgraphs can propagate the current state snapshot
    # back to the parent. Treat that as a snapshot, not a second append.
    if len(incoming) >= len(existing) and incoming[: len(existing)] == existing:
        return incoming[-100:]
    if len(existing) >= len(incoming) and existing[: len(incoming)] == incoming:
        return existing[-100:]
    common_prefix_length = 0
    for old_event, new_event in zip(existing, incoming, strict=False):
        if old_event != new_event:
            break
        common_prefix_length += 1
    merged = [
        *existing[:common_prefix_length],
        *existing[common_prefix_length:],
        *incoming[common_prefix_length:],
    ]
    return merged[-100:]


def _pending_transaction_followup(
    prior_state: dict[str, Any], message: str
) -> tuple[str, list[str], bool, bool]:
    """Restore a transaction task when the user answers a clarification or continuation prompt."""
    task_request = str(prior_state.get("task_request") or "")
    task_queue = list(prior_state.get("task_queue") or [])
    history = prior_state.get("conversation_history") or []
    pending_question = str(prior_state.get("final_response") or _last_assistant_reply(history))
    category_question = _is_category_clarification(pending_question) or bool(
        prior_state.get("awaiting_user_input") and _required_tools(message, "category") == {"create_category"}
    )
    is_pending = bool(
        not prior_state.get("tasks_completed")
        and category_question
        and _obvious_specialist(task_request) == "transaction"
    )
    if not is_pending and re.fullmatch(
        r"\s*(?:yes|yeah|yep|yup|sure|okay|ok|go ahead|please do|do it|proceed)[.! ]*\s*",
        message,
        flags=re.IGNORECASE,
    ):
        continuation_prompt = bool(
            re.search(r"\b(?:proceed|continue|go ahead)\b", pending_question, flags=re.IGNORECASE)
            and re.search(r"\b(?:expense|transaction|purchase)\b", pending_question, flags=re.IGNORECASE)
        )
        events = prior_state.get("tool_event_history") or []
        pending_event_index = next(
            (
                index
                for index in range(len(events) - 1, -1, -1)
                if events[index].get("tool") == "ask_user"
                and _obvious_specialist(str(events[index].get("task") or "")) == "transaction"
            ),
            None,
        )
        if continuation_prompt and pending_event_index is not None:
            pending_event = events[pending_event_index]
            transaction_was_created = any(
                event.get("tool") == "create_transaction" and event.get("ok")
                for event in events[pending_event_index + 1 :]
            )
            if not transaction_was_created:
                task_request = str(pending_event.get("request") or task_request)
                task_queue = [str(pending_event.get("task") or task_request)]
                is_pending = True
    if is_pending and not task_queue:
        task_queue = [task_request]
    is_category_create = bool(
        is_pending
        and task_queue
        and _required_tools(message, "category") == {"create_category"}
        and _obvious_specialist(message) == "category"
    )
    return task_request, task_queue, is_pending, is_category_create


def _pending_itemized_split_followup(prior_state: dict[str, Any]) -> tuple[str | None, str | None]:
    """Recover the active itemized split and its transaction after a rejected tool call."""
    failed_split_event = next(
        (
            event
            for event in reversed(prior_state.get('tool_event_history') or [])
            if event.get('tool') == 'create_split'
            and not event.get('ok')
            and isinstance(event.get('arguments'), dict)
            and isinstance(event['arguments'].get('items'), list)
        ),
        None,
    )
    if failed_split_event is None:
        return None, None

    arguments = failed_split_event['arguments']
    transaction_id = arguments.get('transaction_id')
    transaction_id = transaction_id or prior_state.get('pending_split_transaction_id')
    created_ids = prior_state.get('created_transaction_ids') or []
    transaction_id = transaction_id or (created_ids[-1] if created_ids else None)
    handoff = prior_state.get('handoff') or {}
    transaction_id = transaction_id or handoff.get('transaction_id')
    task = str(failed_split_event.get('task') or failed_split_event.get('request') or '').strip()
    return (task or None), (str(transaction_id) if transaction_id else None)


def _pending_receipt_split_invitation(
    prior_state: dict[str, Any], message: str
) -> tuple[str | None, str | None]:
    """Turn an affirmative reply to the post-receipt split question into a split task."""
    previous_question = _last_assistant_reply(prior_state.get('conversation_history') or [])
    asked_about_split = re.search(
        r"\b(?:would you like|do you want|want me to|should i)\b.{0,80}\bsplit\b",
        previous_question,
        re.I,
    )
    if not asked_about_split:
        return None, None
    reply = message.strip()
    if re.match(r"^(?:no|nope|nah|don't|do not|not now)\b", reply, re.I):
        return None, None
    if not re.match(r"^(?:yes|yeah|yep|yup|sure|okay|ok|please|go ahead|do it|split\b)", reply, re.I) and not re.search(
        r"\bwith\s+[A-Za-z]", reply, re.I,
    ):
        return None, None

    transaction_id = next(
        (str(value) for value in reversed(prior_state.get('created_transaction_ids') or []) if value),
        None,
    )
    if transaction_id is None:
        for result in reversed(prior_state.get('results') or []):
            data = result.get('data') or {}
            transactions = data.get('created_transactions') or []
            transaction = data.get('transaction') or (transactions[-1] if transactions else {})
            if result.get('specialist') == 'transaction' and isinstance(transaction, dict) and transaction.get('id'):
                transaction_id = str(transaction['id'])
                break
    if transaction_id is None:
        for event in reversed(prior_state.get('tool_event_history') or []):
            if event.get('tool') != 'create_transaction' or not event.get('ok'):
                continue
            transaction = (event.get('data') or {}).get('transaction') or {}
            if transaction.get('id'):
                transaction_id = str(transaction['id'])
                break
    if transaction_id is None:
        return None, None
    task = (
        'Create a split for the receipt transaction using only participants named or confirmed in the chat. '
        f'Follow any explicit equal, custom, or itemized allocation instructions in the chat. User reply: {reply}. '
        'If required participants or allocation details are unclear, ask before saving. '
        'Do not record the expense again.'
    )
    return task, transaction_id


def _is_account_creation_reply(message: str) -> bool:
    """Recognize a concrete create-account answer to the transaction's no-account prompt."""
    return bool(
        re.search(
            r"^\s*(?:(?:yes|yeah|yep|sure|okay|ok)[, ]*)?(?:please\s+)?(?:create|add|open)\b"
            r".+\b(?:with|balance|initial)\b.+\d",
            message,
            flags=re.IGNORECASE,
        )
    )


class AgentGraphState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    # Chat transcript updates are append-only. A reducer is required because
    # a resumed interrupt can apply the resume update alongside specialist
    # state updates in the same LangGraph step.
    conversation_history: Annotated[list[dict[str, str]], _append_conversation_history]
    user_id: str
    timezone: str
    task_request: str
    task_queue: list[str]
    completed_tasks: list[str]
    created_transaction_ids: list[str]
    pending_split_transaction_id: str | None
    pending_account_creation: bool
    tasks_completed: bool
    awaiting_user_input: bool
    show_completion_popup: bool
    available_categories: list[dict[str, Any]]
    available_accounts: list[dict[str, Any]]
    available_split_contacts: list[str]
    confirmed_memories: list[dict[str, Any]]
    memory_review_signal: dict[str, Any] | None
    memory_review_eligible: bool
    memory_review_transaction_ids: list[str]
    specialist_messages: Annotated[list[BaseMessage], add_messages]
    next_specialist: str | None
    handoff: dict[str, Any]
    results: list[dict[str, Any]]
    prior_results: list[dict[str, Any]]
    tool_event_history: list[dict[str, Any]]
    contextual_followup: bool
    reroutes: int
    specialist_steps: int
    final_response: str | None
    last_transaction_window: dict[str, str]


class AgenticSupervisorGraph:
    """Supervisor-only root graph; specialists own all domain tools."""

    def __init__(
        self,
        *,
        checkpointer: Any,
        llm: Any,
        guardrail: SemanticGuardrail,
        category_service: CategoryService,
        account_service: AccountService,
        transaction_service: TransactionService,
        query_tools: TransactionQueryTools,
        export_service: ExportService | None = None,
        split_service: SplitService | None = None,
        memory_repository: SqlAlchemyMemoryRepository | None = None,
        db_session: AsyncSession | None = None,
    ) -> None:
        self._guardrail = guardrail
        self._category_service = category_service
        self._account_service = account_service
        self._split_service = split_service
        self._memory_repository = memory_repository

        # Callers may provide a single shared model or a per-agent mapping.
        # This keeps cost/quality selection configuration outside agent logic.
        def model_for(name: str) -> Any:
            if isinstance(llm, Mapping):
                return llm.get(name) or llm.get("default")
            return llm

        supervisor_llm = model_for("supervisor")
        category_llm = model_for("category")
        account_llm = model_for("account")
        transaction_llm = model_for("transaction")
        split_llm = model_for("split")
        analytics_llm = model_for("analytics")
        export_llm = model_for("export")
        formatting_llm = model_for("formatting")
        self._supervisor = StructuredSupervisorBrain(llm=supervisor_llm, system_prompt=SUPERVISOR_PROMPT)
        extraction_agent = TransactionExtractionAgent(transaction_llm)
        category_tools = CategoryToolset(category_service).registry()
        account_tools = AccountToolset(account_service).registry()
        transaction_tools = TransactionToolset(transaction_service, extraction_agent=extraction_agent).registry()
        analytics_tools = AnalyticsToolset(query_tools, split_service=split_service).registry()
        export_tools = ExportToolset(export_service).registry() if export_service else {}
        split_tools = SplitToolset(split_service, transaction_service).registry() if split_service else {}
        tool_lock = asyncio.Lock()
        self._specialists = {
            "category": ToolBoundSpecialistRuntime(
                name="category",
                llm=category_llm,
                system_prompt=CATEGORY_PROMPT,
                tools=category_tools,
                destructive_tools={"delete_category"},
                db_session=db_session,
                tool_lock=tool_lock,
            ),
            "account": ToolBoundSpecialistRuntime(
                name="account",
                llm=account_llm,
                system_prompt=ACCOUNT_PROMPT,
                tools=account_tools,
                db_session=db_session,
                tool_lock=tool_lock,
            ),
            "transaction": ToolBoundSpecialistRuntime(
                name="transaction",
                llm=transaction_llm,
                system_prompt=TRANSACTION_PROMPT,
                tools=transaction_tools,
                destructive_tools={"delete_transaction"},
                db_session=db_session,
                tool_lock=tool_lock,
            ),
            "split": ToolBoundSpecialistRuntime(
                name="split", llm=split_llm, system_prompt=SPLIT_PROMPT,
                tools=split_tools, non_retryable_tools={"create_split", "create_owed"},
                db_session=db_session, tool_lock=tool_lock,
            ),
            "analytics": ToolBoundSpecialistRuntime(
                name="analytics",
                llm=analytics_llm,
                system_prompt=ANALYTICS_PROMPT,
                tools=analytics_tools,
                allow_interrupts=False,
                db_session=db_session,
                tool_lock=tool_lock,
            ),
            "export": ToolBoundSpecialistRuntime(
                name="export",
                llm=export_llm,
                system_prompt=EXPORT_PROMPT,
                tools=export_tools,
                allow_interrupts=False,
                db_session=db_session,
                tool_lock=tool_lock,
            ),
            "formatting": ToolBoundSpecialistRuntime(
                name="formatting",
                llm=formatting_llm,
                system_prompt=FORMATTING_PROMPT,
                tools={},
                allow_interrupts=False,
                db_session=db_session,
                tool_lock=tool_lock,
            ),
        }
        graph = StateGraph(AgentGraphState)
        graph.add_node("guardrails", self._guardrails)
        graph.add_node("supervisor", self._supervise)
        graph.add_node("memory_review_gate", self._memory_review_gate)
        for name in self._specialists:
            graph.add_node(name, self._specialists[name].build_persistent_subgraph(AgentGraphState))
        graph.add_edge(START, "guardrails")
        graph.add_conditional_edges("guardrails", self._after_guardrails, {"supervisor": "supervisor", END: END})
        graph.add_conditional_edges(
            "supervisor",
            self._after_supervisor,
            {**{name: name for name in self._specialists}, "supervisor": "supervisor", END: END},
        )
        for name in self._specialists:
            graph.add_edge(name, "memory_review_gate" if name == "transaction" else "supervisor")
        graph.add_edge("memory_review_gate", "supervisor")
        self.graph = graph.compile(checkpointer=checkpointer)

    async def invoke(
        self, *, user_id: uuid.UUID, thread_id: str, message: str, timezone: str = "UTC"
    ) -> dict[str, Any]:
        config = {"configurable": {"thread_id": f"{user_id}:{thread_id}"}}
        snapshot = await self.graph.aget_state(config)
        prior_state = snapshot.values or {}
        conversation_history = prior_state.get("conversation_history") or []
        (
            prior_task_request,
            pending_queue,
            resume_pending_transaction,
            is_new_category_for_pending_transaction,
        ) = _pending_transaction_followup(prior_state, message)
        if snapshot.interrupts:
            interrupt_payload = getattr(snapshot.interrupts[0], "value", {})
            pending_question = (
                str(interrupt_payload.get("question") or "")
                if isinstance(interrupt_payload, dict)
                else str(interrupt_payload)
            )
            updated_history = list(conversation_history)
            if pending_question and (
                not conversation_history
                or conversation_history[-1].get("role") != "assistant"
                or conversation_history[-1].get("content") != pending_question
            ):
                updated_history.append({"role": "assistant", "content": pending_question})
            updated_history.append({"role": "user", "content": message})
            resume_update: dict[str, Any] = {
                "messages": [HumanMessage(content=message)],
                "conversation_history": updated_history[-100:],
            }
            if isinstance(interrupt_payload, dict) and interrupt_payload.get("memory_signal"):
                signal_type = str(interrupt_payload.get("memory_signal"))
                if signal_type in {"category_mapping", "account_mapping", "preference", "split_preference"}:
                    resume_update["memory_review_signal"] = {
                        "signal_type": signal_type,
                        "subject_hint": str(interrupt_payload.get("subject_hint") or "")[:120],
                    }
            # The model's optional ask_user metadata is helpful, but must not be
            # the sole path. A user answering a category question for a pending
            # transaction is itself a strong, typed signal. The background
            # analyzer will identify the merchant/category from the bounded chat
            # transcript after the transaction is successfully saved.
            if "memory_review_signal" not in resume_update:
                category_signal = _category_reply_memory_signal(
                    pending_question=pending_question,
                    pending_task=prior_task_request,
                    reply=message,
                )
                if category_signal:
                    resume_update["memory_review_signal"] = category_signal
            if is_new_category_for_pending_transaction:
                resume_update["task_queue"] = [message, *pending_queue]
            account_setup_answer = bool(
                isinstance(interrupt_payload, dict)
                and interrupt_payload.get("agent") == "transaction"
                and re.search(r"\bno accounts?\b|\bcreate (?:an? )?account\b", pending_question, re.I)
                and _is_account_creation_reply(message)
            )
            if account_setup_answer:
                transaction_task = (prior_state.get("task_queue") or [prior_task_request])[0]
                resume_update["task_queue"] = [
                    f"Create account: {message}",
                    str(transaction_task or prior_task_request),
                ]
                resume_update["pending_account_creation"] = True
            return await self.graph.ainvoke(
                Command(resume=message, update=resume_update),
                config=config,
            )
        prior_results = prior_state.get("results") or []
        pending_split_task, pending_split_transaction_id = _pending_itemized_split_followup(prior_state)
        pending_itemized_split = bool(pending_split_task and pending_split_transaction_id)
        receipt_split_task, receipt_transaction_id = _pending_receipt_split_invitation(prior_state, message)
        pending_receipt_split = bool(receipt_split_task and receipt_transaction_id)
        if pending_receipt_split:
            pending_split_task = receipt_split_task
            pending_split_transaction_id = receipt_transaction_id
        if pending_itemized_split:
            pending_queue = [str(pending_split_task)]
            prior_task_request = str(pending_split_task)
        elif pending_receipt_split:
            pending_queue = [str(receipt_split_task)]
            prior_task_request = str(receipt_split_task)
        tool_event_history = prior_state.get("tool_event_history") or []
        contextual_followup = bool(prior_results and _is_elaboration_followup(message))
        resumed_category_signal = None
        if resume_pending_transaction:
            resumed_category_signal = _category_reply_memory_signal(
                pending_question=str(prior_state.get("final_response") or _last_assistant_reply(conversation_history)),
                pending_task=prior_task_request,
                reply=message,
            )
        task_queue = (
            [message, *pending_queue]
            if is_new_category_for_pending_transaction
            else pending_queue
            if (resume_pending_transaction or pending_itemized_split or pending_receipt_split)
            else []
        )
        return await self.graph.ainvoke(
            {
                "messages": [HumanMessage(content=message)],
                # Keep chat context separate from specialist working messages,
                # which are intentionally cleared when handing off to a specialist.
                "conversation_history": [
                    *conversation_history,
                    {"role": "user", "content": message},
                ][-100:],
                "user_id": str(user_id),
                "timezone": timezone,
                # This is the task the active specialist must complete. It
                # survives an interrupt; the newest message is only its
                # clarification answer, not a replacement task.
                "task_request": (
                    prior_task_request
                    if (resume_pending_transaction or pending_itemized_split or pending_receipt_split)
                    else message
                ),
                "task_queue": task_queue or (["elaborate on the prior verified answer"] if contextual_followup else []),
                "completed_tasks": list(prior_state.get("completed_tasks") or []) if resume_pending_transaction else [],
                "created_transaction_ids": (
                    list(prior_state.get("created_transaction_ids") or [])
                    if resume_pending_transaction
                    else [str(receipt_transaction_id)] if pending_receipt_split and receipt_transaction_id else []
                ),
                "pending_split_transaction_id": (
                    pending_split_transaction_id
                ) if (pending_itemized_split or pending_receipt_split) else None,
                "tasks_completed": False,
                "awaiting_user_input": False,
                "show_completion_popup": False,
                "results": [],
                # Keep a bounded window of the previous turn's structured tool
                # observations available to every new task, not only follow-ups.
                "prior_results": prior_results[-5:],
                "tool_event_history": tool_event_history,
                # Some assistant turns ask for a missing category in plain text
                # and finish normally instead of yielding a LangGraph interrupt.
                # Preserve the same typed signal on that follow-up route too.
                "memory_review_signal": resumed_category_signal,
                "memory_review_eligible": False,
                "memory_review_transaction_ids": [],
                "contextual_followup": contextual_followup,
                "reroutes": 0,
                "final_response": None,
                "next_specialist": None,
            },
            config=config,
        )

    async def _guardrails(self, state: AgentGraphState) -> dict[str, Any]:
        assessment = await self._guardrail.assess(str(state["messages"][-1].content))
        if assessment.decision == GuardrailDecision.BLOCK:
            return {"final_response": "I can only help with personal-finance requests.", "tasks_completed": False}
        return {}

    @staticmethod
    async def _memory_review_gate(state: AgentGraphState) -> dict[str, Any]:
        """Mark a chat signal eligible only after verified transaction creation.

        The transaction tool persists the analysis outbox row atomically with
        the transaction. This graph node records the eligibility decision for
        orchestration/tracing; it does not invoke an LLM or enqueue duplicate work.
        """
        signal = state.get("memory_review_signal")
        if not isinstance(signal, dict) or signal.get("signal_type") not in {
            "category_mapping", "account_mapping", "preference", "split_preference",
        }:
            return {"memory_review_eligible": False, "memory_review_transaction_ids": []}

        transaction_result = next(
            (
                result
                for result in reversed(state.get("results", []))
                if result.get("specialist") == "transaction"
            ),
            None,
        )
        if not transaction_result or transaction_result.get("status") != "success":
            return {"memory_review_eligible": False, "memory_review_transaction_ids": []}

        created_transactions = (transaction_result.get("data") or {}).get("created_transactions") or []
        transaction_ids = [
            str(transaction["id"])
            for transaction in created_transactions
            if isinstance(transaction, dict) and transaction.get("id")
        ]
        transaction_ids = list(dict.fromkeys([
            *(state.get("memory_review_transaction_ids") or []),
            *transaction_ids,
        ]))
        return {
            "memory_review_eligible": bool(transaction_ids),
            "memory_review_transaction_ids": transaction_ids,
        }

    @staticmethod
    def _after_guardrails(state: AgentGraphState) -> Literal["supervisor", "__end__"]:
        return END if state.get("final_response") else "supervisor"

    async def _supervise(self, state: AgentGraphState) -> dict[str, Any]:
        categories = (
            await self._category_service.list_categories(uuid.UUID(state["user_id"]))
            if self._category_service is not None
            else []
        )
        accounts = (
            await self._account_service.list_accounts(uuid.UUID(state["user_id"]))
            if self._account_service is not None
            else []
        )
        available_categories = [{"id": str(item.id), "name": item.name, "type": item.type.value} for item in categories]
        available_accounts = [
            {
                "id": str(item.id),
                "name": item.name,
                "type": item.type.value,
                "is_active": item.is_active,
                "is_default": item.is_default,
            }
            for item in accounts
        ]
        available_split_contacts = (
            await self._split_service.contact_names(uuid.UUID(state["user_id"]))
            if self._split_service is not None
            else []
        )
        confirmed_memories = []
        if self._memory_repository is not None:
            memories = await self._memory_repository.relevant_confirmed(
                uuid.UUID(state['user_id']), subjects=[], scopes=['user', 'merchant', 'person', 'account', 'category'],
            )
            confirmed_memories = [
                {
                    'scope': memory.scope,
                    'subject_key': memory.subject_key,
                    'memory_type': memory.memory_type,
                    'value': memory.value_json,
                    'evidence_count': memory.evidence_count,
                }
                for memory in memories
            ]
        history = (state.get("conversation_history") or [])[-20:]
        task_queue = state.get("task_queue") or []
        context = HandoffContext(
            user_id=uuid.UUID(state["user_id"]),
            request=task_queue[0] if task_queue else state.get("task_request") or str(state["messages"][-1].content),
            history=history,
            timezone=state.get("timezone", "UTC"),
            constraints={
                "latest_user_reply": str(state["messages"][-1].content),
                "completed_tasks": state.get("completed_tasks", []),
                "remaining_tasks": task_queue,
                "available_categories": available_categories,
                "available_accounts": available_accounts,
                "available_split_contacts": available_split_contacts,
                "created_transaction_ids": state.get("created_transaction_ids", []),
                "pending_split_transaction_id": state.get('pending_split_transaction_id'),
                "last_transaction_window": state.get("last_transaction_window"),
                "original_request": state.get("task_request"),
                "prior_specialist_results": state.get("prior_results", []),
                "recent_tool_observations": state.get("tool_event_history", [])[-12:],
                "confirmed_memories": confirmed_memories,
                "memory_review_signal": state.get("memory_review_signal"),
            },
        )
        results = state.get("results", [])
        task_request = str(state.get("task_request") or state["messages"][-1].content)
        latest_reply = str(state["messages"][-1].content)
        fast_route = None
        if (
            not results
            and not task_queue
            and not state.get("completed_tasks")
            and not state.get("contextual_followup")
        ):
            fast_route = _fast_route_specialist(task_request)

        latest_result = (results or [{}])[-1]
        verified_terminal = (
            bool(results)
            and not state.get("contextual_followup")
            and _verified_queue_is_complete(
                task_queue,
                latest_result,
                original_request=task_request,
                latest_reply=latest_reply,
                available_categories=available_categories,
            )
        )
        if fast_route is not None:
            # Clear, single-domain requests do not need an LLM merely to repeat
            # a route already recognized by the deterministic intent helpers.
            task_queue = [task_request]
            decision = SupervisorDecision(
                action="route",
                specialist=fast_route,
                handoff={"queued_task": task_request, "deterministic_route": True},
            )
        elif verified_terminal:
            # The specialist summary and successful observations are already
            # authoritative. The normal completion block below will assemble
            # the final response and UI metadata without another LLM roundtrip.
            decision = SupervisorDecision(action="finish")
        else:
            decision = await self._supervisor.decide(context, results)
        prior_results = state.get("prior_results") or []
        if state.get("contextual_followup") and not state.get("results") and prior_results:
            prior_specialist = prior_results[-1].get("specialist")
            if prior_specialist in self._specialists:
                decision = SupervisorDecision(
                    action="route",
                    specialist=prior_specialist,
                    handoff={"contextual_followup": True, "reuse_prior_results": True},
                )
        if not task_queue and not state.get("completed_tasks"):
            task_queue = [task.strip() for task in (decision.tasks or []) if task.strip()]
            explicit_clauses = _explicit_action_clauses(state.get("task_request", ""))
            if len(explicit_clauses) > len(task_queue):
                task_queue = explicit_clauses
            receipt_upload = _is_receipt_upload_request(str(state.get("task_request") or ""))
            if receipt_upload:
                # The generated receipt prompt mentions a later optional split.
                # That is not user consent and must not become a queued action.
                task_queue = [task for task in task_queue if _obvious_specialist(task) != "split"]
            task_queue = _canonicalize_split_task_queue(
                task_queue,
                state.get("task_request") or str(state["messages"][-1].content),
            )
            if not task_queue:
                task_queue = [state.get("task_request") or str(state["messages"][-1].content)]
        receipt_upload = _is_receipt_upload_request(str(state.get("task_request") or ""))
        if receipt_upload and not state.get("results"):
            decision = SupervisorDecision(
                action="route",
                specialist="transaction",
                handoff={**decision.handoff, "queued_task": task_queue[0]},
            )
        if not state.get("results"):
            queued_specialist = _obvious_specialist(task_queue[0]) if task_queue else None
            setup_then_transaction = bool(
                len(task_queue) > 1
                and queued_specialist in {"account", "category"}
                and _obvious_specialist(task_queue[1]) == "transaction"
            )
            continuing_completed_work = bool(state.get("completed_tasks") and queued_specialist == "transaction")
            if queued_specialist is not None and (setup_then_transaction or continuing_completed_work) and (
                decision.action != "route" or decision.specialist != queued_specialist
            ):
                decision = SupervisorDecision(
                    action="route",
                    specialist=queued_specialist,
                    handoff={**decision.handoff, "queued_task": task_queue[0]},
                )
        if not state.get("results") and (decision.action != "route" or decision.specialist is None):
            specialist = _obvious_specialist(task_queue[0]) or _obvious_specialist(state.get("task_request", ""))
            if specialist is None and state.get("last_transaction_window") and re.search(
                r"\b(?:before|earlier|prior|previous|preceding)\b", task_queue[0], flags=re.IGNORECASE
            ):
                specialist = "analytics"
            if specialist is not None:
                decision = SupervisorDecision(
                    action="route",
                    specialist=specialist,
                    handoff={**decision.handoff, "original_request": state.get("task_request", "")},
                )
        latest_result = (state.get("results") or [{}])[-1]
        if (
            task_queue
            and _obvious_specialist(task_queue[0]) == "category"
            and latest_result.get("specialist") == "transaction"
            and latest_result.get("status") != "failed"
        ):
            return {
                "results": [],
                "next_specialist": "supervisor",
                "task_queue": task_queue,
                "awaiting_user_input": False,
            }
        if latest_result.get("status") == "needs_input":
            return {
                "final_response": latest_result.get("summary") or "I need one more detail to continue.",
                "next_specialist": None,
                "task_queue": task_queue,
                "tasks_completed": False,
                "awaiting_user_input": True,
            }
        if latest_result.get('specialist') == 'split' and any(
            'Itemized split was not saved' in str(error) for error in latest_result.get('errors', [])
        ):
            return {
                'final_response': latest_result.get('summary') or 'The split was not saved. Tell me what to change.',
                'next_specialist': None,
                'task_queue': task_queue,
                'tasks_completed': False,
                'awaiting_user_input': True,
            }
        if latest_result.get("status") in {"success", "partial"}:
            observed_actions = (latest_result.get("data") or {}).get("observed_actions") or []
            remaining_tasks, satisfied_tasks = _reconcile_task_queue(
                task_queue,
                observed_actions,
                original_request=state.get("task_request", ""),
                latest_reply=str(state["messages"][-1].content),
                available_categories=available_categories,
                verify_categories=latest_result.get("specialist") == "category",
            )
            if latest_result.get("specialist") == "transaction" and remaining_tasks:
                created = (latest_result.get("data") or {}).get("created_transactions") or []
                if not created:
                    transaction = (latest_result.get("data") or {}).get("transaction")
                    created = [transaction] if isinstance(transaction, Mapping) else []
                verified_transaction = next(
                    (
                        item
                        for item in reversed(created)
                        if isinstance(item, Mapping) and item.get("amount_paise") is not None
                    ),
                    None,
                )
                if verified_transaction is not None:
                    remaining_tasks = [
                        _with_verified_split_total(task, verified_transaction)
                        if _obvious_specialist(task) == "split"
                        else task
                        for task in remaining_tasks
                    ]
            # A resumed transaction turn can be a confirmation/correction
            # reply after the transaction was already created. In that case
            # the specialist may return a verified success summary without
            # repeating the create_transaction observation. Consume the
            # queued transaction task from that summary instead of reporting
            # an incomplete request.
            if (
                latest_result.get("specialist") == "transaction"
                and latest_result.get("status") == "success"
                and not observed_actions
                and remaining_tasks
                and _obvious_specialist(remaining_tasks[0]) == "transaction"
                and re.search(r"\b(?:successfully logged|already been logged|transaction has been logged)\b",
                              str(latest_result.get("summary", "")), flags=re.IGNORECASE)
            ):
                satisfied_tasks = [remaining_tasks[0]]
                remaining_tasks = remaining_tasks[1:]
            if state.get("contextual_followup") and latest_result.get("status") == "success":
                remaining_tasks, satisfied_tasks = [], list(task_queue)
            if (
                latest_result.get("specialist") == "formatting"
                and latest_result.get("status") == "success"
                and task_queue
                and _obvious_specialist(task_queue[0]) is None
            ):
                remaining_tasks, satisfied_tasks = task_queue[1:], task_queue[:1]
            if satisfied_tasks:
                category_create_satisfied = latest_result.get("specialist") == "category" and any(
                    _category_creation_satisfied(
                        task,
                        state.get("task_request", ""),
                        str(state["messages"][-1].content),
                        available_categories,
                    )
                    for task in satisfied_tasks
                )
                show_completion_popup = bool(
                    state.get("show_completion_popup")
                    or category_create_satisfied
                    or any(action.get("tool") in _MUTATION_TOOLS for action in observed_actions)
                )
                summary = (
                    decision.response or latest_result.get("summary", "Completed.")
                    if not remaining_tasks or len(satisfied_tasks) == 1
                    else "Completed: " + "; ".join(satisfied_tasks)
                )
                receipt_request = str(state.get("task_request") or "").casefold()
                receipt_transaction_created = bool(
                    latest_result.get("specialist") == "transaction"
                    and latest_result.get("status") == "success"
                    and (latest_result.get("data") or {}).get("created_transactions")
                    and "receipt/bill image" in receipt_request
                    and "ask whether i want" in receipt_request
                )
                if receipt_transaction_created:
                    # Keep the user's optional split question explicit and prevent
                    # the supervisor from suggesting participant transactions.
                    created = (latest_result.get("data") or {}).get("created_transactions") or []
                    transaction = created[-1] if created and isinstance(created[-1], dict) else {}
                    amount = int(transaction.get("amount_paise") or 0)
                    merchant = str(transaction.get("merchant") or "this receipt")
                    summary = (
                        f"Logged one receipt expense of ₹{amount / 100:,.2f} for {merchant}. "
                        "Would you like to split this expense? If yes, who should be included?"
                    )
                    # The receipt follow-up is an inline question, not a timed
                    # completion popup that could disappear before the user answers.
                    show_completion_popup = False
                report_actions = [
                    action for action in observed_actions
                    if action.get("tool") == "create_transaction_report"
                ]
                if report_actions:
                    report = report_actions[-1].get("data") or {}
                    if report.get("export_id"):
                        summary += f"\n[[export:{report['export_id']}]]"
                completed_tasks = [*state.get("completed_tasks", []), summary]
                created_transaction_ids = [
                    *state.get("created_transaction_ids", []),
                    *[
                        str(item["id"])
                        for item in (latest_result.get("data") or {}).get("created_transactions", [])
                        if isinstance(item, dict) and item.get("id")
                    ],
                ]
                if not remaining_tasks:
                    return {
                        "final_response": "\n".join(completed_tasks),
                        "next_specialist": None,
                        "task_queue": [],
                        "completed_tasks": completed_tasks,
                        "created_transaction_ids": created_transaction_ids,
                        "tasks_completed": True,
                        "awaiting_user_input": False,
                        "show_completion_popup": show_completion_popup,
                    }
                return {
                    "task_queue": remaining_tasks,
                    "completed_tasks": completed_tasks,
                    "created_transaction_ids": created_transaction_ids,
                    "show_completion_popup": show_completion_popup,
                    "results": [],
                    "reroutes": 0,
                    "next_specialist": "supervisor",
                }
        quoted_category_names = re.findall(r'["“]([^"”]+)["”]', state.get("task_request", ""))
        category_tasks = [
            task
            for task in task_queue
            if _required_tools(task, "category") == {"create_category"}
            and (
                _obvious_specialist(task) == "category"
                or (
                    _obvious_specialist(state.get("task_request", "")) == "category"
                    and any(_mentions(task, name) for name in quoted_category_names)
                )
            )
        ]
        if category_tasks and (
            (latest_result.get("specialist") == "category" and latest_result.get("status") == "success")
            or (
                not state.get("results")
                and state.get("completed_tasks")
                and all(
                    _category_creation_satisfied(
                        task,
                        state.get("task_request", ""),
                        str(state["messages"][-1].content),
                        available_categories,
                    )
                    for task in category_tasks
                )
            )
        ):
            satisfied_tasks = [
                task
                for task in category_tasks
                if _category_creation_satisfied(
                    task,
                    state.get("task_request", ""),
                    str(state["messages"][-1].content),
                    available_categories,
                )
            ]
            if (
                not satisfied_tasks
                and latest_result.get("specialist") == "category"
                and not any(
                    action.get("tool") == "create_category" and action.get("ok")
                    for action in latest_result.get("actions_taken", [])
                )
            ):
                return {
                    "final_response": "I could not verify that the requested task was completed.",
                    "next_specialist": None,
                    "task_queue": task_queue,
                    "tasks_completed": False,
                }
            remaining_tasks = [task for task in task_queue if task not in satisfied_tasks]
            completed_tasks = list(state.get("completed_tasks", []))
            if latest_result.get("specialist") == "category" and satisfied_tasks:
                completed_tasks.append(decision.response or latest_result.get("summary", "Completed."))
            if not remaining_tasks:
                return {
                    "final_response": "\n".join(completed_tasks),
                    "next_specialist": None,
                    "task_queue": [],
                    "completed_tasks": completed_tasks,
                    "tasks_completed": True,
                    "awaiting_user_input": False,
                    "show_completion_popup": True,
                }
            if not satisfied_tasks and state.get("reroutes", 0) >= _MAX_REROUTES:
                return {
                    "final_response": "I could not verify that every requested category exists.",
                    "next_specialist": None,
                    "task_queue": remaining_tasks,
                    "tasks_completed": False,
                }
            return {
                "task_queue": remaining_tasks,
                "completed_tasks": completed_tasks,
                "show_completion_popup": bool(state.get("show_completion_popup") or satisfied_tasks),
                "results": [],
                "reroutes": 0 if satisfied_tasks else state.get("reroutes", 0),
                "next_specialist": "supervisor",
            }
        if decision.action == "finish":
            return {
                "final_response": (
                    latest_result.get("summary", "I could not complete that request.")
                    if latest_result.get("status") not in {"success", "partial"}
                    else "I could not verify that the requested task was completed."
                ),
                "next_specialist": None,
                "task_queue": task_queue,
                "tasks_completed": False,
            }
        if state.get("reroutes", 0) >= _MAX_REROUTES:
            return {
                "final_response": latest_result.get("summary", "I could not complete that request."),
                "next_specialist": None,
                "task_queue": task_queue,
            }
        if decision.action == "refuse" or decision.specialist is None:
            return {
                "final_response": decision.response or "I cannot help with that request.",
                "next_specialist": None,
                "task_queue": task_queue,
            }
        return {
            "task_queue": task_queue,
            "available_categories": available_categories,
            "available_accounts": available_accounts,
            "available_split_contacts": available_split_contacts,
            "confirmed_memories": confirmed_memories,
            "next_specialist": decision.specialist,
            "handoff": decision.handoff,
            "reroutes": state.get("reroutes", 0) + 1,
            "specialist_steps": 0,
            "specialist_messages": self._initial_specialist_messages(
                {
                    **state,
                    "task_queue": task_queue,
                    "available_categories": available_categories,
                    "available_accounts": available_accounts,
                    "available_split_contacts": available_split_contacts,
                    "confirmed_memories": confirmed_memories,
                },
                decision.specialist,
                decision.handoff,
            ),
        }

    @staticmethod
    def _after_supervisor(state: AgentGraphState) -> str:
        return state.get("next_specialist") or END

    def _initial_specialist_messages(
        self, state: AgentGraphState, name: str, handoff: dict[str, Any]
    ) -> list[BaseMessage]:
        # The supervisor may propose arithmetic in a dynamic handoff. The split
        # tool must derive amounts from the saved transaction and raw user facts.
        specialist_handoff = (
            {key: value for key, value in handoff.items() if key == 'transaction_id'}
            if name == 'split' else handoff
        )
        context = HandoffContext(
            user_id=uuid.UUID(state["user_id"]),
            request=(state.get("task_queue") or [state.get("task_request") or str(state["messages"][-1].content)])[0],
            history=(state.get("conversation_history") or [])[-20:],
            timezone=state.get("timezone", "UTC"),
            constraints={
                "specialist_results": state.get("results", []),
                "prior_specialist_results": state.get("prior_results", []),
                "recent_tool_observations": state.get("tool_event_history", [])[-12:],
                "completed_tasks": state.get("completed_tasks", []),
                "supervisor_handoff": specialist_handoff,
                "latest_user_reply": str(state["messages"][-1].content),
                "available_categories": state.get("available_categories", []),
                "available_accounts": state.get("available_accounts", []),
                "available_split_contacts": state.get("available_split_contacts", []),
                "confirmed_memories": state.get("confirmed_memories", []),
                # This signal is created when the user answers a pending
                # transaction clarification. Preserve it in the trusted
                # specialist handoff so create_transaction can enqueue the
                # conversation for background memory analysis.
                "memory_review_signal": state.get("memory_review_signal"),
                "created_transaction_ids": state.get("created_transaction_ids", []),
                "pending_split_transaction_id": state.get('pending_split_transaction_id'),
                "last_transaction_window": state.get("last_transaction_window"),
                "original_request": state.get("task_request"),
            },
        )
        return [RemoveMessage(id=REMOVE_ALL_MESSAGES), *self._specialists[name].initial_messages(context)]


class AgenticChatOrchestrator:
    """Adapter that preserves the existing chat-service port during migration."""

    def __init__(self, graph: AgenticSupervisorGraph) -> None:
        self._graph = graph

    async def run_turn(
        self,
        *,
        user_id: uuid.UUID,
        thread_id: str,
        message: str,
        timezone: str | None = None,
    ) -> ChatTurnResult:
        result = await self._graph.invoke(
            user_id=user_id,
            thread_id=thread_id,
            message=message,
            timezone=timezone or "UTC",
        )
        interrupts = result.get("__interrupt__", [])
        if interrupts:
            payload = getattr(interrupts[0], "value", {})
            reply = (
                str(payload.get("question") or "What additional detail do you need?")
                if isinstance(payload, dict)
                else str(payload)
            )
        else:
            reply = str(result.get("final_response") or "I could not complete that request.")
        # Preserve the user-facing transcript independently from the messages
        # used by specialist subgraphs. Those working messages are cleared at
        # handoff, while this bounded history remains available on later turns.
        if not interrupts:
            await self._graph.graph.aupdate_state(
                {"configurable": {"thread_id": f"{user_id}:{thread_id}"}},
                {
                    "messages": [AIMessage(content=reply)],
                    "conversation_history": [
                        *((result.get("conversation_history") or [])[-99:]),
                        {"role": "assistant", "content": reply},
                    ],
                    "memory_review_signal": None,
                },
            )
        transaction_id: str | None = (result.get("created_transaction_ids") or [None])[-1]
        for specialist_result in reversed(result.get("results") or []):
            if specialist_result.get("specialist") != "transaction":
                continue
            created_transactions = (specialist_result.get("data") or {}).get("created_transactions") or []
            if created_transactions:
                transaction_id = str(created_transactions[-1]["id"])
                break
        return ChatTurnResult(
            message=reply,
            tasks_completed=not interrupts and bool(result.get("tasks_completed")),
            show_completion_popup=not interrupts
            and bool(result.get("tasks_completed"))
            and bool(result.get("show_completion_popup")),
            transaction_logged=transaction_id is not None,
            created_transaction_id=transaction_id,
        )
