from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver

from app.domain.ports import GuardrailAssessment, GuardrailDecision
from app.infrastructure.ai.agents.contracts import HandoffContext, SpecialistDecision, SupervisorDecision, ToolAction
from app.infrastructure.ai.agents.runtime import SpecialistRuntime
from app.infrastructure.ai.agents.supervisor_graph import (
    AgenticSupervisorGraph,
    _append_conversation_history,
    _category_creation_satisfied,
    _explicit_action_clauses,
    _obvious_specialist,
    _pending_transaction_followup,
    _reconcile_task_queue,
    _remaining_after_observations,
    _required_tools,
)


class AllowingGuardrail:
    async def assess(self, _message: str) -> GuardrailAssessment:
        return GuardrailAssessment(decision=GuardrailDecision.ALLOW, confidence=1.0, layer="test")


class NativeTestLlm:
    """A model double for the real bind_tools -> ToolNode specialist path."""

    def __init__(self) -> None:
        self.bound_inputs: list[list[Any]] = []

    def with_structured_output(self, _schema: Any, **_kwargs: Any) -> RunnableLambda:
        return RunnableLambda(lambda _input: None)

    def bind_tools(self, _tools: list[Any], **_kwargs: Any) -> RunnableLambda:
        async def respond(messages: list[Any]) -> AIMessage:
            self.bound_inputs.append(messages)
            return AIMessage(content="Completed by specialist.")

        return RunnableLambda(respond)


class ScriptedSupervisor:
    def __init__(self, decisions: Sequence[SupervisorDecision]) -> None:
        self.decisions = list(decisions)
        self.calls: list[tuple[HandoffContext, list[dict[str, Any]]]] = []

    async def decide(self, context: HandoffContext, results: list[dict[str, Any]]) -> SupervisorDecision:
        self.calls.append((context, results))
        return self.decisions.pop(0)


def _graph(llm: NativeTestLlm | None = None) -> AgenticSupervisorGraph:
    return AgenticSupervisorGraph(
        checkpointer=InMemorySaver(),
        llm=llm or NativeTestLlm(),
        guardrail=AllowingGuardrail(),
        category_service=None,  # type: ignore[arg-type]
        account_service=None,  # type: ignore[arg-type]
        transaction_service=None,  # type: ignore[arg-type]
        query_tools=None,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_supervisor_routes_to_native_specialist_then_returns_response() -> None:
    graph = _graph()
    supervisor = ScriptedSupervisor(
        [
            SupervisorDecision(action="route", specialist="category"),
            SupervisorDecision(action="finish", response="Created Food."),
        ]
    )
    graph._supervisor = supervisor  # type: ignore[assignment]

    result = await graph.invoke(user_id=uuid.uuid4(), thread_id="routing", message="Create Food category")

    assert result["final_response"] == "I could not verify that the requested task was completed."
    assert result["tasks_completed"] is False
    assert [item[1][-1]["specialist"] for item in supervisor.calls[1:]] == ["category"]


@pytest.mark.asyncio
async def test_supervisor_handoff_is_in_native_specialist_context() -> None:
    llm = NativeTestLlm()
    graph = _graph(llm)
    graph._supervisor = ScriptedSupervisor(
        [
            SupervisorDecision(action="route", specialist="category", handoff={"category_names": ["Food"]}),
            SupervisorDecision(action="finish", response="Done"),
        ]
    )  # type: ignore[assignment]

    await graph.invoke(user_id=uuid.uuid4(), thread_id="handoff", message="Create Food")

    category_messages = next(
        messages for messages in llm.bound_inputs if "Category specialist" in str(messages[0].content)
    )
    assert '"category_names":["Food"]' in str(category_messages[1].content)


def test_new_category_reply_keeps_the_pending_expense_queued() -> None:
    task_request, task_queue, resumes, creates_category = _pending_transaction_followup(
        {
            "task_request": "spent 99 on drugs",
            "task_queue": ["spent 99 on drugs"],
            "tasks_completed": False,
            "final_response": (
                "Which category should be used for the expense of 99 on drugs? Available categories are Food and Misc."
            ),
        },
        "Create new category Medicines",
    )

    assert task_request == "spent 99 on drugs"
    assert task_queue == ["spent 99 on drugs"]
    assert resumes is True
    assert creates_category is True


def test_affirmative_continuation_restores_unfinished_transaction_task() -> None:
    task_request, task_queue, resumes, creates_category = _pending_transaction_followup(
        {
            "task_request": "yes",
            "tasks_completed": True,
            "final_response": (
                'The "Food" category has been created. You can now proceed with recording the ₹999 expense.'
            ),
            "conversation_history": [
                {"role": "assistant", "content": 'You can now proceed with recording the ₹999 expense.'}
            ],
            "tool_event_history": [
                {
                    "tool": "ask_user",
                    "ok": True,
                    "task": "record a 999 expense in the Food category",
                    "request": "spent 999 on food",
                },
                {"tool": "create_account", "ok": True, "task": "create Axis account with 6000"},
            ],
        },
        "yes",
    )

    assert task_request == "spent 999 on food"
    assert task_queue == ["record a 999 expense in the Food category"]
    assert resumes is True
    assert creates_category is False

    remaining, satisfied = _reconcile_task_queue(
        task_queue,
        [
            {
                "tool": "create_transaction",
                "ok": True,
                "data": {
                    "transaction": {
                        "amount_paise": 99900,
                        "merchant": None,
                        "id": str(uuid.uuid4()),
                    }
                },
            }
        ],
        original_request=task_request,
        latest_reply="yes",
        available_categories=[{"name": "Food", "type": "expense"}],
        verify_categories=False,
    )
    assert remaining == []
    assert satisfied == task_queue


def test_conversation_history_reducer_appends_parallel_updates_and_bounds_history() -> None:
    existing = [{"role": "user", "content": "first"}]
    update = [{"role": "assistant", "content": "question"}, {"role": "user", "content": "answer"}]

    assert _append_conversation_history(existing, update) == [*existing, *update]
    repeated_message = {"role": "user", "content": "yes"}
    assert _append_conversation_history([repeated_message], [repeated_message]) == [repeated_message]
    assert _append_conversation_history(
        [repeated_message], [repeated_message, {"role": "user", "content": "yes"}]
    ) == [repeated_message, {"role": "user", "content": "yes"}]
    assert _append_conversation_history(existing, [*existing, *update]) == [*existing, *update]
    assert len(_append_conversation_history([{"role": "user", "content": str(i)} for i in range(100)], update)) == 100


def test_report_request_routes_to_export_and_requires_verified_report() -> None:
    task = "Export my transactions as CSV"
    assert _obvious_specialist(task) == "export"
    assert _obvious_specialist("Download my spending history as Excel") == "export"
    assert _obvious_specialist("Give me an Excel report of my expenses") == "export"
    assert _required_tools(task, "export") == {"create_transaction_report"}
    remaining, satisfied = _reconcile_task_queue(
        [task],
        [{"tool": "create_transaction_report", "data": {"export_id": str(uuid.uuid4())}}],
        original_request=task,
        latest_reply=task,
        available_categories=[],
        verify_categories=False,
    )
    assert remaining == []
    assert satisfied == [task]


@pytest.mark.asyncio
async def test_chat_report_handoff_returns_a_refreshable_download_marker() -> None:
    report_id = uuid.uuid4()

    class FakeExportService:
        async def create_report(self, **kwargs: Any) -> Any:
            assert kwargs["format"] == "csv"
            return type(
                "Report",
                (),
                {
                    "id": report_id,
                    "filename": "transactions.csv",
                    "format": "csv",
                    "row_count": 2,
                    "expires_at": datetime.now(UTC) + timedelta(hours=24),
                },
            )()

    class ExportLlm(NativeTestLlm):
        def bind_tools(self, _tools: list[Any], **_kwargs: Any) -> RunnableLambda:
            async def respond(messages: list[Any]) -> AIMessage:
                if "export specialist" not in str(messages[0].content).lower():
                    return AIMessage(content="Done.")
                if any(isinstance(message, ToolMessage) for message in messages):
                    return AIMessage(content="Your CSV report is ready with two transactions.")
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "create_transaction_report",
                        "args": {"arguments": {"format": "csv"}},
                        "id": "report-call",
                    }],
                )

            return RunnableLambda(respond)

    graph = AgenticSupervisorGraph(
        checkpointer=InMemorySaver(),
        llm=ExportLlm(),
        guardrail=AllowingGuardrail(),
        category_service=None,  # type: ignore[arg-type]
        account_service=None,  # type: ignore[arg-type]
        transaction_service=None,  # type: ignore[arg-type]
        query_tools=None,  # type: ignore[arg-type]
        export_service=FakeExportService(),  # type: ignore[arg-type]
    )
    graph._supervisor = ScriptedSupervisor([
        SupervisorDecision(action="route", specialist="export", tasks=["Export my transactions as CSV"]),
        SupervisorDecision(action="finish", response="Your CSV report is ready."),
    ])  # type: ignore[assignment]
    result = await graph.invoke(user_id=uuid.uuid4(), thread_id="export", message="Export my transactions as CSV")
    assert result["tasks_completed"] is True
    assert result["task_queue"] == []
    assert f"[[export:{report_id}]]" in result["final_response"]


def test_category_creation_verification_infers_expense_from_pending_transaction() -> None:
    available_categories = [{"name": "Medicines", "type": "expense"}]
    assert _category_creation_satisfied(
        "Create new category Medicines",
        "spent 99 on drugs",
        "Create new category Medicines",
        available_categories,
    )
    assert _category_creation_satisfied(
        "Create new category Medicines",
        "Create new category Medicines",
        "Create new category Medicines",
        available_categories,
    )
    assert not _category_creation_satisfied(
        "Create new category Medicines",
        "spent 99 on drugs",
        "Create new category Medicines",
        [{"name": "Medicines", "type": "income"}],
    )


@pytest.mark.asyncio
async def test_supervisor_preserves_task_queue_when_transaction_needs_input() -> None:
    graph = _graph()
    graph._supervisor = ScriptedSupervisor([SupervisorDecision(action="finish")])  # type: ignore[assignment]
    user_id = uuid.uuid4()
    update = await graph._supervise(
        {
            "messages": [HumanMessage(content="spent 99 on drugs")],
            "user_id": str(user_id),
            "task_request": "spent 99 on drugs",
            "task_queue": ["spent 99 on drugs"],
            "results": [
                {
                    "specialist": "transaction",
                    "status": "needs_input",
                    "summary": "Which category should be used for the expense of 99 on drugs?",
                }
            ],
        }
    )

    assert update["awaiting_user_input"] is True
    assert update["task_queue"] == ["spent 99 on drugs"]
    assert update["final_response"] == "Which category should be used for the expense of 99 on drugs?"


@pytest.mark.asyncio
async def test_category_type_reply_keeps_category_creation_as_supervisor_task() -> None:
    class AskingCategoryLlm(NativeTestLlm):
        def __init__(self) -> None:
            super().__init__()
            self.category_steps = 0

        def bind_tools(self, _tools: list[Any], **_kwargs: Any) -> RunnableLambda:
            async def respond(messages: list[Any]) -> AIMessage:
                if "Category specialist" in str(messages[0].content):
                    self.category_steps += 1
                    if self.category_steps == 1:
                        return AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "ask_user",
                                    "args": {"question": "Expense or income category?"},
                                    "id": "category-type-question",
                                }
                            ],
                        )
                return AIMessage(content="Category work complete.")

            return RunnableLambda(respond)

    graph = _graph(AskingCategoryLlm())
    supervisor = ScriptedSupervisor(
        [
            SupervisorDecision(action="route", specialist="category"),
            SupervisorDecision(action="finish", response="Created Enterntainment as an expense category."),
        ]
    )
    graph._supervisor = supervisor  # type: ignore[assignment]
    user_id = uuid.uuid4()

    interrupted = await graph.invoke(
        user_id=user_id, thread_id="category-only", message='create new category "Enterntainment"'
    )
    assert interrupted["__interrupt__"]

    completed = await graph.invoke(user_id=user_id, thread_id="category-only", message="expense")

    assert completed["final_response"] == "I could not verify that the requested task was completed."
    assert completed["conversation_history"] == [
        {"role": "user", "content": 'create new category "Enterntainment"'},
        {"role": "assistant", "content": "Expense or income category?"},
        {"role": "user", "content": "expense"},
    ]
    assert len(supervisor.calls) == 2
    assert supervisor.calls[1][0].request == 'create new category "Enterntainment"'
    assert supervisor.calls[1][0].constraints["latest_user_reply"] == "expense"


@pytest.mark.asyncio
async def test_supervisor_processes_all_planned_tasks_before_completion() -> None:
    graph = _graph()
    supervisor = ScriptedSupervisor(
        [
            SupervisorDecision(
                action="route",
                specialist="formatting",
                tasks=["Summarize Food", "Summarize Groceries"],
            ),
            SupervisorDecision(action="finish", response="Food summarized."),
            SupervisorDecision(action="route", specialist="formatting"),
            SupervisorDecision(action="finish", response="Groceries summarized."),
        ]
    )
    graph._supervisor = supervisor  # type: ignore[assignment]

    result = await graph.invoke(
        user_id=uuid.uuid4(), thread_id="two-tasks", message="Summarize Food and Groceries separately"
    )

    assert result["task_queue"] == []
    assert result["tasks_completed"] is True
    assert result["final_response"] == "Food summarized.\nGroceries summarized."
    assert [call[0].request for call in supervisor.calls] == [
        "Summarize Food and Groceries separately",
        "Summarize Food",
        "Summarize Groceries",
        "Summarize Groceries",
    ]


@pytest.mark.asyncio
async def test_earlier_transaction_follow_ups_advance_the_checkpointed_query_window() -> None:
    class QueryStub:
        def __init__(self) -> None:
            self.windows: list[tuple[uuid.UUID, datetime, datetime]] = []

        @staticmethod
        def resolve_date_window(_request: str, *, timezone_name: str) -> tuple[datetime, datetime]:
            del timezone_name
            return datetime.fromisoformat("2026-10-02T00:00:00+00:00"), datetime.fromisoformat(
                "2026-10-16T23:59:59+00:00"
            )

        async def get_transactions(
            self, *, user_id: uuid.UUID, date_from: datetime, date_to: datetime, limit: int
        ) -> list[dict[str, str]]:
            del limit
            self.windows.append((user_id, date_from, date_to))
            return []

    class AnalyticsLlm(NativeTestLlm):
        def bind_tools(self, _tools: list[Any], **_kwargs: Any) -> RunnableLambda:
            async def respond(messages: list[Any]) -> AIMessage:
                if len(messages) == 2:
                    return AIMessage(
                        content="",
                        tool_calls=[{"name": "get_transactions", "args": {"arguments": {}}, "id": str(uuid.uuid4())}],
                    )
                data = json.loads(str(messages[-1].content))["data"]
                return AIMessage(content=f'Transactions from {data["date_from"]} to {data["date_to"]}.')

            return RunnableLambda(respond)

    queries = QueryStub()
    graph = AgenticSupervisorGraph(
        checkpointer=InMemorySaver(),
        llm=AnalyticsLlm(),
        guardrail=AllowingGuardrail(),
        category_service=None,  # type: ignore[arg-type]
        account_service=None,  # type: ignore[arg-type]
        transaction_service=None,  # type: ignore[arg-type]
        query_tools=queries,  # type: ignore[arg-type]
    )
    graph._supervisor = ScriptedSupervisor(  # type: ignore[assignment]
        [
            SupervisorDecision(action="route", specialist="analytics"),
            SupervisorDecision(action="finish"),
            SupervisorDecision(action="route", specialist="analytics", tasks=["Show recent transactions"]),
            SupervisorDecision(action="finish"),
            SupervisorDecision(action="route", specialist="analytics", tasks=["Show recent transactions"]),
            SupervisorDecision(action="finish"),
        ]
    )
    user_id = uuid.uuid4()
    first = await graph.invoke(user_id=user_id, thread_id="history", message="recent transactions")
    second = await graph.invoke(user_id=user_id, thread_id="history", message="what about before that")
    third = await graph.invoke(user_id=user_id, thread_id="history", message="before this")

    assert all(item["tasks_completed"] for item in (first, second, third))
    assert all(window[0] == user_id for window in queries.windows)
    assert len(queries.windows) == 3
    assert queries.windows[1][2] < queries.windows[0][1]
    assert queries.windows[2][2] < queries.windows[1][1]
    assert second["last_transaction_window"]["date_to"] == queries.windows[1][2].isoformat()


@pytest.mark.asyncio
async def test_formatting_result_cannot_complete_a_mutation_task() -> None:
    graph = _graph()
    graph._supervisor = ScriptedSupervisor(
        [
            SupervisorDecision(action="route", specialist="formatting", tasks=["Create Food expense category"]),
            SupervisorDecision(action="finish", response="Food was created."),
        ]
    )  # type: ignore[assignment]

    result = await graph.invoke(user_id=uuid.uuid4(), thread_id="formatting-mutation", message="Create Food category")

    assert result["tasks_completed"] is False
    assert result["task_queue"] == ["Create Food expense category"]


def test_verified_actions_consume_only_the_matching_queued_tasks() -> None:
    category_actions = [
        {"tool": "create_category", "data": {"category": {"name": "Food", "type": "expense"}}},
        {"tool": "create_category", "data": {"category": {"name": "Groceries", "type": "expense"}}},
    ]
    assert _remaining_after_observations(
        ["Create Food expense category", "Create Groceries expense category", "Record 20 rupees at Cafe"],
        category_actions,
    ) == ["Record 20 rupees at Cafe"]

    account_actions = [
        {"tool": "create_account", "data": {"account": {"name": "Axis", "type": "bank"}}},
        {"tool": "create_account", "data": {"account": {"name": "HDFC", "type": "bank"}}},
    ]
    assert (
        _remaining_after_observations(["Create Axis bank account", "Create HDFC bank account"], account_actions) == []
    )

    transaction_actions = [
        {"tool": "create_transaction", "data": {"transaction": {"amount_paise": 2000, "merchant": "Cafe"}}},
        {"tool": "create_transaction", "data": {"transaction": {"amount_paise": 5000, "merchant": "Zepto"}}},
    ]
    assert _remaining_after_observations(["Spent 20 at Cafe", "Paid 50 at Zepto"], transaction_actions) == []
    assert _remaining_after_observations(["Spent 20 at Cafe", "Spent 20 at Cafe"], transaction_actions[:1]) == [
        "Spent 20 at Cafe"
    ]
    assert _remaining_after_observations(
        ["Create Axis bank account", "Create HDFC bank account"], account_actions[1:]
    ) == ["Create Axis bank account"]
    assert _remaining_after_observations(["Spent 20 at Cafe", "Paid 50 at Zepto"], transaction_actions[1:]) == [
        "Spent 20 at Cafe"
    ]
    assert _remaining_after_observations(["Create Axis bank account"], transaction_actions) == [
        "Create Axis bank account"
    ]
    assert _remaining_after_observations(
        ["Log a transaction for 1139 rupees from the receipt"],
        [
            {
                "tool": "create_transaction",
                "data": {
                    "transaction": {
                        "amount_paise": 113900,
                        "merchant": "Liquor Street (ODVJH Private Limited)",
                    }
                },
            }
        ],
    ) == []
    assert (
        _remaining_after_observations(
            ["Rename Food category to Dining", "Delete Groceries category"],
            [
                {"tool": "update_category", "data": {"category": {"name": "Dining", "type": "expense"}}},
                {"tool": "delete_category", "data": {"category": {"name": "Groceries", "type": "expense"}}},
            ],
        )
        == []
    )
    assert (
        _remaining_after_observations(
            ["Show my accounts", "Show my categories", "Show my transaction history"],
            [{"tool": tool, "data": {}} for tool in ("list_accounts", "list_categories", "list_transactions")],
        )
        == []
    )
    assert (
        _remaining_after_observations(
            ["Delete Cafe transaction"],
            [{"tool": "delete_transaction", "data": {"transaction": {"amount_paise": 2000, "merchant": "Cafe"}}}],
        )
        == []
    )
    remaining, satisfied = _reconcile_task_queue(
        ["Create Food expense category", "Paid 50 at Zepto"],
        transaction_actions[1:],
        original_request="Create Food expense category and pay 50 at Zepto",
        latest_reply="Create Food expense category and pay 50 at Zepto",
        available_categories=[{"name": "Food", "type": "expense"}],
        verify_categories=True,
    )
    assert remaining == []
    assert satisfied == ["Create Food expense category", "Paid 50 at Zepto"]
    assert _reconcile_task_queue(
        ["Create Drinks expense category"],
        [{"tool": "create_category", "data": {"category": {"name": "Drinks", "type": "expense"}}}],
        original_request="Create Drinks expense category",
        latest_reply="Create Drinks expense category",
        available_categories=[],
        verify_categories=True,
    )[0] == ["Create Drinks expense category"]
    assert _required_tools("Create Axis account", "account") == {"create_account"}
    assert _required_tools("Deactivate Axis account", "account") == {"deactivate_account", "update_account"}
    assert _required_tools("Delete the Cafe transaction", "transaction") == {"delete_transaction"}
    assert _obvious_specialist('create "Food" and "Drinks" are expense categories') == "category"
    assert _obvious_specialist("Open an Axis bank account") == "account"
    assert _obvious_specialist("Spent 20 at Cafe") == "transaction"
    assert _obvious_specialist("How much did I spend last month?") == "analytics"
    assert _obvious_specialist("Show my account balances") == "analytics"
    assert _explicit_action_clauses("Show my account balances and show my recent transactions") == [
        "Show my account balances",
        "show my recent transactions",
    ]
    assert _explicit_action_clauses("Create Food and Drinks categories") == []
    assert _obvious_specialist("Transfer 100 from Axis to HDFC") == "transaction"
    assert (
        _remaining_after_observations(
            ["Transfer 100 from Axis to HDFC"],
            [{"tool": "create_transaction", "data": {"transaction": {"amount_paise": 10000, "type": "transfer"}}}],
        )
        == []
    )
    assert (
        _remaining_after_observations(
            ["Set Axis as default"],
            [{"tool": "set_default_account", "data": {"account": {"name": "Axis"}}}],
        )
        == []
    )
    available = [{"name": "Food", "type": "expense"}, {"name": "Drinks", "type": "expense"}]
    original = 'create "Food" and "Drinks" are expense categories'
    assert _category_creation_satisfied("Create Drinks as an expense category", original, original, available)
    assert _category_creation_satisfied(original, original, original, available)
    assert not _category_creation_satisfied(original, original, original, available[:1])
    assert _category_creation_satisfied(
        "Create Food category", "Create Food and Drinks categories", "Both expense", available
    )
    assert _category_creation_satisfied(
        "Create Food expense category",
        "Create Food expense category and Salary income category",
        "Create Food expense category and Salary income category",
        [*available, {"name": "Salary", "type": "income"}],
    )
    assert (
        _remaining_after_observations(
            ["Show my account balances", "Compare spending this month versus last month"],
            [
                {"tool": "get_account_balances", "data": {}},
                {"tool": "get_spending_comparison", "data": {}},
            ],
        )
        == []
    )


@pytest.mark.asyncio
async def test_specialist_iteration_cap_and_tool_retry_are_bounded() -> None:
    attempts = 0

    async def failing_tool(_context: HandoffContext, _arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("temporary")

    class ScriptedBrain:
        def __init__(self) -> None:
            self.decisions = [
                SpecialistDecision(action="call_tool", tool=ToolAction(name="create_category")),
                SpecialistDecision(action="call_tool", tool=ToolAction(name="create_category")),
            ]

        async def decide(self, _context: HandoffContext, _observations: list[Any]) -> SpecialistDecision:
            return self.decisions.pop(0)

    runtime = SpecialistRuntime(
        name="category",
        brain=ScriptedBrain(),
        tools={"create_category": failing_tool},
        max_iterations=2,
        max_tool_retries=2,
    )
    result = await runtime.run(HandoffContext(user_id=uuid.uuid4(), request="Create Food"))

    assert attempts == 6
    assert result.status == "failed"
    assert "iteration_limit" in result.errors
