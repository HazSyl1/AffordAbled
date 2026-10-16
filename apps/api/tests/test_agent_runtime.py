from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.infrastructure.ai.agents.analytics import AnalyticsToolset
from app.infrastructure.ai.agents.brains import scoped_specialist_decision_schema
from app.infrastructure.ai.agents.contracts import HandoffContext, SpecialistDecision, ToolAction
from app.infrastructure.ai.agents.runtime import SpecialistRuntime, ToolBoundSpecialistRuntime, _tool_error_message
from app.infrastructure.ai.tools.transaction_query_tools import TransactionQueryTools


class ScriptedBrain:
    def __init__(self, decisions: list[SpecialistDecision]) -> None:
        self._decisions = decisions

    async def decide(self, _context, _observations):
        return self._decisions.pop(0)


def test_tool_error_diagnostics_stay_within_observation_limit() -> None:
    message = _tool_error_message(RuntimeError("failed " + "x" * 1_000 + "\nSQL parameters"))

    assert len(message) == 600
    assert "SQL parameters" not in message


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
