from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import InjectedState, ToolNode, tools_condition
from langgraph.types import interrupt
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.ai.agents.contracts import (
    HandoffContext,
    SpecialistDecision,
    SpecialistResult,
    ToolObservation,
)

logger = logging.getLogger(__name__)

ToolHandler = Callable[[HandoffContext, dict[str, Any]], Awaitable[dict[str, Any]]]


def _tool_error_message(exc: Exception) -> str:
    """Keep database diagnostics bounded and omit SQL parameter dumps."""
    first_line = (str(exc).splitlines() or [""])[0]
    return f"{type(exc).__name__}: {first_line}"[:600]


class CreateAccountArguments(BaseModel):
    name: str = Field(min_length=1, max_length=120, description="Account name, for example Axis.")
    type: Literal["cash", "bank", "card", "wallet"] = Field(
        default="bank", description="Account kind. Use bank for a named bank account."
    )
    balance_rupees: Decimal = Field(default=Decimal("0"), ge=0, description="Initial balance in rupees, not paise.")
    currency: str = Field(default="INR", min_length=3, max_length=3)


class CreateAccountToolInput(BaseModel):
    arguments: CreateAccountArguments


class CreateCategoryArguments(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["expense", "income"]


class CreateCategoryToolInput(BaseModel):
    arguments: CreateCategoryArguments


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


_TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "create_account": CreateAccountToolInput,
    "create_category": CreateCategoryToolInput,
    "create_transaction": CreateTransactionToolInput,
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
    "list_categories": "Read category IDs before choosing a transaction category or verifying a request.",
    "create_category": "Create an idempotent user-owned category with name and type: expense or income.",
    "update_category": "Update a user-owned category by category_id when its name or type should change.",
    "delete_category": "Delete one user-owned category only after explicit confirmation from the user.",
    "extract_transaction": "Extract fields from ambiguous transaction text or receipts; skip for clear requests.",
    "list_transactions": "Read user transactions for lookup requests; do not use to create or edit records.",
    "create_transaction": "Create one user transaction after resolving IDs; amount_rupees is in rupees.",
    "create_transaction_batch": "Create several explicit transaction rows; do not use for one transaction.",
    "update_transaction": "Edit a user transaction by transaction_id when explicitly requested.",
    "delete_transaction": "Soft-delete one user-owned transaction only after explicit confirmation.",
    "restore_transaction": "Restore one previously deleted user-owned transaction when explicitly requested.",
    "get_account_balances": "Read current account balances for balance questions, not transaction history.",
    "get_transactions": "Read transactions in a bounded date window for recent, prior, or date-range history.",
    "get_spending_summary": "Read aggregate spending for a supplied date range, not individual transactions.",
    "get_spending_by_account": "Read spending grouped by account for a supplied date range.",
    "get_spending_comparison": "Compare two supported spending periods.",
    "get_split_summary": "Read outstanding split balances for money-owed or remaining-split questions.",
    "list_split_contacts": "Read names used in prior splits to help match people; new names are allowed.",
    "create_split": "Create a split after its expense exists, using its ID and requested participants.",
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
                answer = interrupt({"agent": self.name, "question": decision.question})
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
                return ToolObservation(tool=name, ok=True, data=data)
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
        for attempt in range(self.max_tool_retries + 1):
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
            except Exception as exc:
                if self._db_session is not None:
                    try:
                        await self._db_session.rollback()
                    except Exception as rollback_exc:
                        return ToolObservation(
                            tool=name,
                            ok=False,
                            error=_tool_error_message(rollback_exc),
                        )
                if attempt == self.max_tool_retries:
                    return ToolObservation(tool=name, ok=False, error=_tool_error_message(exc))
        raise AssertionError("unreachable")

    def _result_from_messages(self, messages: list[BaseMessage]) -> SpecialistResult:
        observations: list[ToolObservation] = []
        for message in messages:
            if getattr(message, "type", "") != "tool":
                continue
            try:
                payload = json.loads(str(message.content))
                observations.append(ToolObservation.model_validate({"tool": message.name, **payload}))
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
                "get_account_balances",
                "get_transactions",
                "get_spending_summary",
                "get_spending_by_account",
                "get_spending_comparison",
                "get_split_summary",
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

        async def agent(state: dict[str, Any]) -> dict[str, Any]:
            steps = int(state.get("specialist_steps", 0))
            if steps >= self.max_iterations:
                return {
                    "specialist_messages": [
                        AIMessage(content="SPECIALIST_ITERATION_LIMIT: Specialist iteration limit reached.")
                    ],
                    "specialist_steps": steps,
                }
            return {
                "specialist_messages": [await model.ainvoke(state["specialist_messages"])],
                "specialist_steps": steps + 1,
            }

        async def finish(state: dict[str, Any]) -> dict[str, Any]:
            result = self._result_from_messages(state.get("specialist_messages", []))
            updates: dict[str, Any] = {"results": [*state.get("results", []), result.model_dump()]}
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

            async def ask_user(question: str) -> str:
                """Pause to ask the user one focused question and return their answer."""
                return json.dumps({"ok": True, "answer": str(interrupt({"agent": self.name, "question": question}))})

            tools.append(
                StructuredTool.from_function(coroutine=ask_user, name="ask_user", description=ask_user.__doc__ or "")
            )
        return tools

    def _persistent_tool(self, name: str, handler: ToolHandler) -> StructuredTool:
        """Create one tool with only model-visible arguments in its schema."""

        async def execute(arguments: dict[str, Any], state: Annotated[dict[str, Any], InjectedState]) -> str:
            context = HandoffContext(
                user_id=state["user_id"],
                request=(state.get("task_queue") or [state["task_request"]])[0],
                timezone=state.get("timezone", "UTC"),
                constraints={
                    "last_transaction_window": state.get("last_transaction_window"),
                    "original_request": state.get("task_request"),
                    "created_transaction_ids": state.get("created_transaction_ids", []),
                    "available_categories": state.get("available_categories", []),
                    "available_accounts": state.get("available_accounts", []),
                },
            )
            values = dict(arguments)
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
