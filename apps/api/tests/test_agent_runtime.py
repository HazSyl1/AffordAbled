from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Annotated, Any, TypedDict

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command
from pydantic import ValidationError

from app.infrastructure.ai.agents.analytics import AnalyticsToolset
from app.infrastructure.ai.agents.brains import scoped_specialist_decision_schema
from app.infrastructure.ai.agents.contracts import HandoffContext, SpecialistDecision, TaskContract, ToolAction
from app.infrastructure.ai.agents.runtime import (
    _TOOL_DESCRIPTIONS,
    _TOOL_SCHEMAS,
    SpecialistRuntime,
    ToolBoundSpecialistRuntime,
    _persistent_tool_context,
    _tool_error_message,
    merge_verified_transaction_references,
)
from app.infrastructure.ai.tools.transaction_query_tools import TransactionQueryTools


class ScriptedBrain:
    def __init__(self, decisions: list[SpecialistDecision]) -> None:
        self._decisions = decisions

    async def decide(self, _context, _observations):
        return self._decisions.pop(0)


def test_verified_transaction_reference_survives_in_tool_context() -> None:
    transaction_id = str(uuid.uuid4())
    source_request = '1608 on dinner at masato with Sudhansu Sujal and Rujul'
    refs = merge_verified_transaction_references([], [
        {'tool': 'create_transaction', 'ok': False, 'request': source_request,
         'data': {'transaction': {'id': str(uuid.uuid4()), 'amount_paise': 160800}}},
        {'tool': 'create_transaction', 'ok': True, 'request': source_request,
         'data': {'transaction': {'id': transaction_id, 'amount_paise': 160800, 'merchant': 'Masato'}}},
    ])

    assert len(refs) == 1
    assert refs[0]['id'] == transaction_id
    assert refs[0]['source_request'] == source_request
    context = _persistent_tool_context({
        'user_id': str(uuid.uuid4()), 'messages': [HumanMessage(content='Create split for this')],
        'task_request': 'Create split for this', 'task_queue': ['Create split for this'],
        'conversation_history': [{'role': 'user', 'content': source_request},
                                 {'role': 'user', 'content': 'Create split for this'}],
        'verified_transaction_references': refs,
    })
    assert context.constraints['verified_transaction_references'] == refs


def test_every_registered_specialist_tool_has_a_schema_and_description() -> None:
    registered_tools = {
        'list_accounts', 'create_account', 'update_account', 'set_default_account', 'delete_account',
        'rename_account', 'activate_account', 'deactivate_account', 'list_categories', 'create_category',
        'update_category', 'delete_category', 'extract_transaction', 'list_transactions', 'create_transaction',
        'update_transaction', 'delete_transaction', 'restore_transaction', 'create_transaction_batch',
        'list_split_contacts', 'set_split_contact_preference', 'create_split', 'create_owed',
        'create_settlement_draft', 'get_split_summary', 'get_account_balances', 'get_transactions',
        'get_current_datetime', 'get_spending_summary', 'get_spending_by_account', 'get_spending_comparison',
        'create_transaction_report',
    }

    assert registered_tools <= _TOOL_SCHEMAS.keys()
    assert registered_tools <= _TOOL_DESCRIPTIONS.keys()


def test_query_tool_schemas_expose_filters_ordering_dates_and_limits() -> None:
    transaction_input = _TOOL_SCHEMAS['get_transactions'].model_validate({
        'arguments': {
            'mode': 'relative_range', 'transaction_type': 'expense', 'category_name': 'Food',
            'account_name': 'Axis', 'order_by': 'amount', 'sort_order': 'desc', 'limit': 3,
        }
    })
    comparison_input = _TOOL_SCHEMAS['get_spending_comparison'].model_validate({
        'arguments': {
            'date_period': 'this_week', 'comparison_period': 'last_week', 'category_name': 'Food',
        }
    })
    split_input = _TOOL_SCHEMAS['get_split_summary'].model_validate({
        'arguments': {
            'kind': 'expense_split', 'status': 'outstanding', 'order_by': 'outstanding',
            'sort_order': 'desc', 'limit': 5,
        }
    })

    assert transaction_input.arguments.category_name == 'Food'
    assert comparison_input.arguments.comparison_period == 'last_week'
    assert split_input.arguments.limit == 5


@pytest.mark.asyncio
async def test_split_summary_limit_keeps_totals_for_all_matching_rows() -> None:
    class SplitServiceStub:
        async def list_for_user(self, _user_id: uuid.UUID) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(
                    id=uuid.uuid4(), transaction_id=uuid.uuid4(), title='Large', owner_share_paise=100,
                    created_at=datetime(2026, 10, 2, tzinfo=UTC),
                    participants=[SimpleNamespace(name='A', share_paise=900, settled_paise=0)],
                ),
                SimpleNamespace(
                    id=uuid.uuid4(), transaction_id=None, title='Small', owner_share_paise=0,
                    created_at=datetime(2026, 10, 1, tzinfo=UTC),
                    participants=[SimpleNamespace(name='B', share_paise=300, settled_paise=0)],
                ),
            ]

    tools = AnalyticsToolset(None, split_service=SplitServiceStub())  # type: ignore[arg-type]
    context = HandoffContext(user_id=uuid.uuid4(), request='largest outstanding split')

    result = await tools.get_split_summary(context, {
        'status': 'outstanding', 'order_by': 'outstanding', 'sort_order': 'desc', 'limit': 1,
    })

    assert result['total_outstanding_paise'] == 1200
    assert result['matching_split_count'] == 2
    assert result['truncated_split_count'] == 1
    assert [item['title'] for item in result['splits']] == ['Large']


@pytest.mark.asyncio
async def test_current_datetime_tool_uses_trusted_handoff_clock_and_timezone() -> None:
    tools = AnalyticsToolset(None)  # type: ignore[arg-type]
    context = HandoffContext(
        user_id=uuid.uuid4(),
        request="Can I afford sushi for the rest of the month?",
        timezone="Asia/Kolkata",
        current_datetime="2026-10-23T19:41:00+05:30",
    )

    result = await tools.get_current_datetime(context, {})

    assert result == {
        "current_datetime": "2026-10-23T19:41:00+05:30",
        "current_date": "2026-10-23",
        "day_of_week": "Friday",
        "timezone": "Asia/Kolkata",
        "days_remaining_after_today": 8,
        "days_remaining_including_today": 9,
        "month_end_date": "2026-10-31",
    }


def test_tool_error_diagnostics_stay_within_observation_limit() -> None:
    message = _tool_error_message(RuntimeError("failed " + "x" * 1_000 + "\nSQL parameters"))

    assert len(message) == 600
    assert "SQL parameters" not in message


def test_persistent_tool_context_includes_recent_conversation_history() -> None:
    user_id = uuid.uuid4()
    history = [
        {"role": "user", "content": "spent 90 on pcm"},
        {"role": "assistant", "content": "Which category should be used for this expense?"},
        {"role": "user", "content": "Health"},
    ]

    context = _persistent_tool_context(
        {
            "user_id": user_id,
            "task_request": "spent 90 on pcm",
            "task_queue": ["record the pcm expense"],
            "conversation_history": history,
        }
    )

    assert context.history == history
    assert context.history[-2]["content"].startswith("Which category")
    assert len(context.history) <= 20


@pytest.mark.parametrize(
    "tool_name",
    [
        "list_accounts",
        "list_categories",
        "list_transactions",
        "list_split_contacts",
        "get_split_summary",
        "get_account_balances",
        "get_transactions",
        "get_spending_summary",
        "get_spending_by_account",
        "create_transaction_report",
        "extract_transaction",
        "delete_account",
    ],
)
def test_optional_tool_inputs_accept_injected_state_without_required_arguments(tool_name: str) -> None:
    async def handler(_context: HandoffContext, _arguments: dict[str, Any]) -> dict[str, Any]:
        return {}

    runtime = ToolBoundSpecialistRuntime(
        name="split",
        llm=None,
        system_prompt="",
        tools={tool_name: handler},
    )
    tool = runtime._persistent_tools()[0]

    parsed = tool.args_schema.model_validate({"state": {}})

    assert "arguments" not in tool.args_schema.model_json_schema().get("required", [])
    assert parsed is not None


@pytest.mark.asyncio
async def test_zero_argument_tool_runs_through_tool_node_with_injected_state() -> None:
    class SharedState(TypedDict, total=False):
        specialist_messages: Annotated[list[BaseMessage], add_messages]
        specialist_steps: int
        user_id: str
        task_request: str
        task_queue: list[str]
        conversation_history: list[dict[str, str]]

    calls: list[tuple[HandoffContext, dict[str, Any]]] = []

    async def list_contacts(context: HandoffContext, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append((context, arguments))
        return {"contacts": ["Isha"]}

    class NoArgumentModel:
        def bind_tools(self, _tools: list[Any], **_kwargs: Any) -> RunnableLambda:
            def respond(messages: list[BaseMessage]) -> AIMessage:
                if any(message.type == "tool" for message in messages):
                    return AIMessage(content="Contacts loaded.")
                return AIMessage(
                    content="",
                    tool_calls=[{"name": "list_split_contacts", "args": {}, "id": "list-contacts"}],
                )

            return RunnableLambda(respond)

    runtime = ToolBoundSpecialistRuntime(
        name="split",
        llm=NoArgumentModel(),
        system_prompt="",
        tools={"list_split_contacts": list_contacts},
    )
    graph = runtime.build_persistent_subgraph(SharedState)
    await graph.ainvoke(
        {
            "specialist_messages": [HumanMessage(content="List the split contacts")],
            "user_id": str(uuid.uuid4()),
            "task_request": "List split contacts",
            "task_queue": ["List split contacts"],
            "conversation_history": [{"role": "user", "content": "List split contacts"}],
        }
    )

    assert len(calls) == 1
    assert calls[0][0].history == [{"role": "user", "content": "List split contacts"}]


@pytest.mark.asyncio
async def test_affordability_request_prefetches_clock_and_balance() -> None:
    class SharedState(TypedDict, total=False):
        specialist_messages: Annotated[list[BaseMessage], add_messages]
        specialist_steps: int
        user_id: str
        timezone: str
        current_datetime: str
        task_request: str
        task_queue: list[str]
        task_contracts: list[dict[str, Any]]
        conversation_history: list[dict[str, str]]
        results: list[dict[str, Any]]
        tool_event_history: list[dict[str, Any]]

    calls: list[tuple[str, HandoffContext]] = []

    async def current_time(context: HandoffContext, _arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(("get_current_datetime", context))
        return {"current_date": "2026-10-23", "days_remaining_after_today": 8}

    async def balances(context: HandoffContext, _arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(("get_account_balances", context))
        return {"accounts": [{"name": "Axis", "balance_paise": 1_338_900}]}

    class FinalAnswerModel:
        def bind_tools(self, _tools: list[Any], **_kwargs: Any) -> RunnableLambda:
            return RunnableLambda(lambda _messages: AIMessage(content="You can afford it with ₹4,489 remaining."))

    runtime = ToolBoundSpecialistRuntime(
        name="analytics",
        llm=FinalAnswerModel(),
        system_prompt="",
        tools={"get_current_datetime": current_time, "get_account_balances": balances},
    )
    graph = runtime.build_persistent_subgraph(SharedState)
    request = "Can I afford 900rps sushi if I need 1k each day for the rest of the month?"
    contract = TaskContract(
        id="affordability-task",
        original_text=request,
        summary=request,
        intent="analytics_query",
        specialist="analytics",
        required_tools=["get_current_datetime", "get_account_balances"],
        required_evidence=[
            "get_current_datetime:current_date",
            "get_account_balances:accounts",
        ],
    )

    result = await graph.ainvoke(
        {
            "specialist_messages": [HumanMessage(content=request)],
            "user_id": str(uuid.uuid4()),
            "timezone": "Asia/Kolkata",
            "current_datetime": "2026-10-23T19:41:00+05:30",
            "task_request": request,
            "task_queue": [request],
            "task_contracts": [contract.model_dump()],
            "conversation_history": [{"role": "user", "content": request}],
            "results": [],
            "tool_event_history": [],
        }
    )

    assert {name for name, _context in calls} == {"get_current_datetime", "get_account_balances"}
    assert all(context.current_datetime == "2026-10-23T19:41:00+05:30" for _name, context in calls)
    assert all(context.constraints["task_id"] == contract.id for _name, context in calls)
    assert result["results"][-1]["status"] == "success"
    assert result["results"][-1]["task_id"] == contract.id
    assert all(
        observation["task_id"] == contract.id
        for observation in result["results"][-1]["tool_observations"]
    )
    assert result["results"][-1]["summary"] == "You can afford it with ₹4,489 remaining."


@pytest.mark.asyncio
async def test_quantity_remainder_split_does_not_offer_complex_draft_tool() -> None:
    class SharedState(TypedDict, total=False):
        specialist_messages: Annotated[list[BaseMessage], add_messages]
        specialist_steps: int
        task_request: str

    invoked_with: list[set[str]] = []

    class TrackingModel:
        def bind_tools(self, tools: list[Any], **_kwargs: Any) -> RunnableLambda:
            names = {tool.name for tool in tools}

            async def respond(_messages: list[BaseMessage]) -> AIMessage:
                invoked_with.append(names)
                return AIMessage(content="Ready to calculate the split.")

            return RunnableLambda(respond)

    async def unused(_context: HandoffContext, _arguments: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("The model should only inspect the available tools.")

    runtime = ToolBoundSpecialistRuntime(
        name="split", llm=TrackingModel(), system_prompt="",
        tools={"create_split": unused, "create_settlement_draft": unused},
    )
    graph = runtime.build_persistent_subgraph(SharedState)
    request = (
        "Spent 927383 rs on A, B, C, D, E, F, G and myself. A, B and C got 7 vodka cranberries "
        "each, which were 7000rs each. Rest of the bill divided equally. A owes C 17000, "
        "B contributed 29000, and C owes B 20000."
    )
    await graph.ainvoke({"specialist_messages": [HumanMessage(content=request)], "task_request": request})
    assert "create_split" in invoked_with[-1]
    assert "create_settlement_draft" not in invoked_with[-1]

    complex_request = request + " Apply a 10% coupon to the bill."
    await graph.ainvoke({"specialist_messages": [HumanMessage(content=complex_request)],
                         "task_request": complex_request})
    assert "create_settlement_draft" in invoked_with[-1]


@pytest.mark.asyncio
async def test_specialist_cannot_call_tool_outside_its_registry() -> None:
    runtime = SpecialistRuntime(
        name="category",
        brain=ScriptedBrain([SpecialistDecision(action="call_tool", tool=ToolAction(name="create_transaction"))]),
        tools={"create_category": _unused_tool},
        max_iterations=1,
    )

    result = await runtime.run(HandoffContext(user_id=uuid.uuid4(), request="Create Food"))

    assert result.status == "failed"
    assert "tool_not_permitted:create_transaction" in result.errors


@pytest.mark.asyncio
async def test_transaction_account_answer_hands_control_back_to_parent_supervisor() -> None:
    class SharedState(TypedDict, total=False):
        specialist_messages: Annotated[list[BaseMessage], add_messages]
        specialist_steps: int
        pending_account_creation: bool
        routed: bool

    class AskForAccountModel:
        def bind_tools(self, _tools: list[Any], **_kwargs: Any) -> RunnableLambda:
            return RunnableLambda(
                lambda _messages: AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ask_user",
                            "args": {"question": "No accounts are available. Would you like to create one?"},
                            "id": "no-account-question",
                        }
                    ],
                )
            )

    runtime = ToolBoundSpecialistRuntime(
        name="transaction",
        llm=AskForAccountModel(),
        system_prompt="",
        tools={},
    )
    child = runtime.build_persistent_subgraph(SharedState)
    parent = StateGraph(SharedState)
    parent.add_node("transaction", child)
    parent.add_node("supervisor", lambda _state: {"routed": True})
    parent.add_edge(START, "transaction")
    parent.add_edge("supervisor", END)
    graph = parent.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "account-answer-handoff"}}

    interrupted = await graph.ainvoke(
        {
            "specialist_messages": [
                SystemMessage(content="Ask for the missing account."),
                HumanMessage(content="Spent 999 on Food"),
            ],
            "pending_account_creation": True,
        },
        config,
    )
    assert interrupted["__interrupt__"]

    resumed = await graph.ainvoke(Command(resume="Create Axis with 6000"), config)

    assert resumed["routed"] is True


def test_specialist_decision_schema_exposes_only_registered_tool_names() -> None:
    schema = scoped_specialist_decision_schema({"create_category", "list_categories"})

    allowed = schema.model_validate(
        {"action": "call_tool", "tool": {"name": "create_category", "arguments": {"name": "Food"}}}
    )
    assert allowed.tool is not None
    assert allowed.tool.name == "create_category"

    with pytest.raises(ValidationError):
        schema.model_validate({"action": "call_tool", "tool": {"name": "create_categories"}})


@pytest.mark.asyncio
async def test_specialist_retries_tool_error_then_finishes() -> None:
    calls = 0

    async def flaky_tool(_context, _arguments):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("temporary failure")
        return {"created": True}

    runtime = SpecialistRuntime(
        name="category",
        brain=ScriptedBrain(
            [
                SpecialistDecision(action="call_tool", tool=ToolAction(name="create_category")),
                SpecialistDecision(action="finish", summary="Created category."),
            ]
        ),
        tools={"create_category": flaky_tool},
        max_tool_retries=3,
    )

    result = await runtime.run(HandoffContext(user_id=uuid.uuid4(), request="Create Food"))

    assert calls == 3
    assert result.status == "success"
    assert result.actions_taken == [{"tool": "create_category", "ok": True}]


@pytest.mark.asyncio
async def test_parallel_tool_calls_share_one_session_safely_and_rollback_before_retry() -> None:
    class SessionStub:
        def __init__(self) -> None:
            self.rollbacks = 0

        async def rollback(self) -> None:
            self.rollbacks += 1

    session = SessionStub()
    active = 0
    most_active = 0
    attempts: dict[str, int] = {}

    async def create_category(_context: HandoffContext, arguments: dict[str, object]) -> dict[str, object]:
        nonlocal active, most_active
        name = str(arguments["name"])
        attempts[name] = attempts.get(name, 0) + 1
        active += 1
        most_active = max(most_active, active)
        try:
            await asyncio.sleep(0)
            if name == "Food" and attempts[name] == 1:
                raise RuntimeError("flush failed")
            return {"category": {"name": name}}
        finally:
            active -= 1

    runtime = ToolBoundSpecialistRuntime(
        name="category",
        llm=None,
        system_prompt="",
        tools={"create_category": create_category},
        max_tool_retries=1,
        db_session=session,  # type: ignore[arg-type]
    )
    context = HandoffContext(user_id=uuid.uuid4(), request="Create Food and Drinks")
    food, drinks = await asyncio.gather(
        runtime._call_handler(context, "create_category", create_category, {"name": "Food"}),
        runtime._call_handler(context, "create_category", create_category, {"name": "Drinks"}),
    )

    assert food.ok and drinks.ok
    assert most_active == 1
    assert attempts == {"Food": 2, "Drinks": 1}
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_specialist_can_delegate_only_to_its_registered_sub_agent() -> None:
    async def extract(_context, _arguments) -> dict[str, object]:
        return {"amount": "450", "missing_fields": []}

    runtime = SpecialistRuntime(
        name="transaction",
        brain=ScriptedBrain(
            [
                SpecialistDecision(action="delegate", delegate_to="extraction"),
                SpecialistDecision(action="finish", summary="Extracted"),
            ]
        ),
        tools={},
        delegates={"extraction": extract},
    )

    result = await runtime.run(HandoffContext(user_id=uuid.uuid4(), request="Spent 450 at Cafe Roma"))

    assert result.status == "success"
    assert result.actions_taken == [{"delegate": "extraction", "ok": True}]


@pytest.mark.asyncio
async def test_read_only_specialist_cannot_interrupt_the_user() -> None:
    runtime = SpecialistRuntime(
        name="analytics",
        brain=ScriptedBrain(
            [
                SpecialistDecision(action="ask_user", question="Which month?"),
                SpecialistDecision(action="finish", summary="Partial result"),
            ]
        ),
        tools={},
        allowed_actions={"call_tool", "finish"},
    )

    result = await runtime.run(HandoffContext(user_id=uuid.uuid4(), request="How much did I spend?"))

    assert result.status == "partial"
    assert result.errors == ["action_not_permitted:ask_user"]


async def _unused_tool(_context, _arguments):
    raise AssertionError("A non-permitted tool must not be invoked")


@pytest.mark.asyncio
async def test_analytics_period_comparison_is_scoped_to_handoff_user_and_timezone() -> None:
    user_id = uuid.uuid4()
    queries = _ComparisonQueries()

    result = await AnalyticsToolset(queries).registry()["get_spending_comparison"](
        HandoffContext(user_id=user_id, request="Compare this month with last month", timezone="Asia/Kolkata"),
        {"date_period": "this_month", "comparison_period": "last_month"},
    )

    assert queries.window_args == ("this_month", "last_month", "Asia/Kolkata")
    assert queries.comparison_args["user_id"] == user_id
    assert result == {"direction": "higher", "delta_paise": 100}


@pytest.mark.asyncio
async def test_spending_tools_resolve_missing_dates_from_relative_request() -> None:
    user_id = uuid.uuid4()
    expected_from = datetime(2026, 10, 19, 18, 30, tzinfo=UTC)
    expected_to = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

    class SpendingQueries:
        def __init__(self) -> None:
            self.resolve_calls: list[tuple[str, str]] = []
            self.summary_args: dict[str, object] = {}
            self.account_args: dict[str, object] = {}

        def resolve_date_window(self, request: str, *, timezone_name: str) -> tuple[datetime, datetime]:
            self.resolve_calls.append((request, timezone_name))
            return expected_from, expected_to

        async def get_spending_summary(self, **kwargs: object) -> dict[str, object]:
            self.summary_args = kwargs
            return {"total_paise": 9900}

        async def get_spending_by_account(self, **kwargs: object) -> dict[str, object]:
            self.account_args = kwargs
            return {"accounts": []}

    queries = SpendingQueries()
    tools = AnalyticsToolset(queries)  # type: ignore[arg-type]
    context = HandoffContext(
        user_id=user_id, request="what did I spend the most on this week", timezone="Asia/Kolkata"
    )

    assert await tools.get_spending_summary(context, {}) == {"total_paise": 9900}
    assert await tools.get_spending_by_account(context, {}) == {"accounts": []}
    assert queries.resolve_calls == [
        (context.request, "Asia/Kolkata"),
        (context.request, "Asia/Kolkata"),
    ]
    assert queries.summary_args == {
        "user_id": user_id, "date_from": expected_from, "date_to": expected_to,
    }
    assert queries.account_args == {
        "user_id": user_id, "date_from": expected_from, "date_to": expected_to, "limit": 10,
    }


@pytest.mark.asyncio
async def test_spending_tools_reject_partial_explicit_date_range() -> None:
    context = HandoffContext(user_id=uuid.uuid4(), request="spending", timezone="Asia/Kolkata")
    with pytest.raises(ValueError, match="both date_from and date_to"):
        await AnalyticsToolset(_ComparisonQueries()).get_spending_summary(  # type: ignore[arg-type]
            context, {"date_from": "2026-10-20T00:00:00+00:00"},
        )


@pytest.mark.asyncio
async def test_largest_spending_transaction_uses_amount_ranking_and_expense_filter() -> None:
    class RankedQueries:
        def __init__(self) -> None:
            self.query_args: dict[str, object] = {}

        async def get_transactions(self, **kwargs: object) -> list[dict[str, object]]:
            self.query_args = kwargs
            return [{"id": "largest", "amount_paise": 99900, "type": "expense"}]

    queries = RankedQueries()
    context = HandoffContext(
        user_id=uuid.uuid4(), request="which transaction I spent most on", timezone="Asia/Kolkata"
    )

    result = await AnalyticsToolset(queries).get_transactions(context, {})  # type: ignore[arg-type]

    assert result["transactions"][0]["id"] == "largest"
    assert queries.query_args["date_from"] == datetime(1970, 1, 1, tzinfo=UTC)
    assert queries.query_args["transaction_type"].value == "expense"  # type: ignore[union-attr]
    assert queries.query_args["order_by"] == "amount"
    assert queries.query_args["sort_order"] == "desc"
    assert queries.query_args["limit"] == 1
    assert result["order_by"] == "amount"


@pytest.mark.asyncio
async def test_recent_transactions_use_current_server_window_even_if_model_supplies_old_dates() -> None:
    class RecentQueries:
        resolve_date_window = staticmethod(TransactionQueryTools.resolve_date_window)

        def __init__(self) -> None:
            self.date_from: datetime | None = None
            self.date_to: datetime | None = None

        async def get_transactions(self, *, date_from: datetime, date_to: datetime, **_kwargs: object) -> list[object]:
            self.date_from, self.date_to = date_from, date_to
            return []

    queries = RecentQueries()
    result = await AnalyticsToolset(queries).get_transactions(  # type: ignore[arg-type]
        HandoffContext(user_id=uuid.uuid4(), request="Show my recent transactions", timezone="Asia/Kolkata"),
        {"date_from": "2023-10-01T00:00:00+00:00", "date_to": "2023-10-31T23:59:59+00:00"},
    )

    assert queries.date_from is not None and queries.date_to is not None
    assert queries.date_to >= datetime.now(UTC) - timedelta(minutes=1)
    assert (queries.date_to - queries.date_from).days <= 14
    assert result["date_from"] == queries.date_from.isoformat()


@pytest.mark.asyncio
async def test_prior_transaction_follow_up_uses_the_previous_result_window() -> None:
    class PriorQueries:
        resolve_date_window = staticmethod(TransactionQueryTools.resolve_date_window)

        def __init__(self) -> None:
            self.date_from: datetime | None = None
            self.date_to: datetime | None = None

        async def get_transactions(self, *, date_from: datetime, date_to: datetime, **_kwargs: object) -> list[object]:
            self.date_from, self.date_to = date_from, date_to
            return []

    queries = PriorQueries()
    result = await AnalyticsToolset(queries).get_transactions(  # type: ignore[arg-type]
        HandoffContext(
            user_id=uuid.uuid4(),
            request="show recent transactions",
            timezone="Asia/Kolkata",
            constraints={
                "original_request": "what about before that",
                "last_transaction_window": {
                    "date_from": "2026-10-01T18:30:00+00:00",
                    "date_to": "2026-10-16T18:29:59.999999+00:00",
                }
            },
        ),
        {"date_from": "2026-10-02T00:00:00+00:00", "date_to": "2026-10-16T23:59:59+00:00"},
    )

    assert queries.date_from == datetime(2026, 9, 16, 18, 30, tzinfo=UTC)
    assert queries.date_to == datetime(2026, 10, 1, 18, 29, 59, 999999, tzinfo=UTC)
    assert result["date_from"] == queries.date_from.isoformat()


@pytest.mark.asyncio
async def test_standalone_previous_transaction_query_uses_full_history_fallback() -> None:
    class PriorQueries:
        resolve_date_window = staticmethod(TransactionQueryTools.resolve_date_window)

        def __init__(self) -> None:
            self.date_from: datetime | None = None
            self.date_to: datetime | None = None

        async def get_transactions(self, *, date_from: datetime, date_to: datetime, **_kwargs: object) -> list[object]:
            self.date_from, self.date_to = date_from, date_to
            return []

    queries = PriorQueries()
    result = await AnalyticsToolset(queries).get_transactions(
        HandoffContext(user_id=uuid.uuid4(), request="what was my previous transaction?", timezone="Asia/Kolkata"),
        {},
    )

    assert queries.date_from == datetime(1970, 1, 1, tzinfo=UTC)
    assert queries.date_to is not None
    assert result["date_from"] == queries.date_from.isoformat()


class _ComparisonQueries:
    def __init__(self) -> None:
        self.window_args: tuple[str, str, str] | None = None
        self.comparison_args: dict[str, object] = {}

    def resolve_spending_comparison_windows(
        self, *, date_period: str, comparison_period: str, timezone_name: str
    ) -> tuple[datetime, datetime, datetime, datetime]:
        self.window_args = (date_period, comparison_period, timezone_name)
        anchor = datetime(2026, 1, 1, tzinfo=UTC)
        return anchor, anchor, anchor, anchor

    async def get_spending_comparison(self, **kwargs: object) -> dict[str, object]:
        self.comparison_args = kwargs
        return {"direction": "higher", "delta_paise": 100}
