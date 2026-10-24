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
from app.infrastructure.ai.agents.contracts import (
    HandoffContext,
    SpecialistDecision,
    SupervisorDecision,
    TaskContract,
    ToolAction,
)
from app.infrastructure.ai.agents.runtime import SpecialistRuntime
from app.infrastructure.ai.agents.supervisor_graph import (
    AgenticSupervisorGraph,
    _append_conversation_history,
    _category_creation_satisfied,
    _category_reply_memory_signal,
    _explicit_action_clauses,
    _is_account_creation_reply,
    _is_complex_settlement_request,
    _is_receipt_upload_request,
    _matches_observed_action,
    _obvious_specialist,
    _pending_itemized_split_followup,
    _pending_receipt_split_invitation,
    _pending_transaction_followup,
    _reconcile_task_queue,
    _remaining_after_observations,
    _required_tools,
    _split_task_for_request,
    _sync_task_contracts,
    _verify_task_contract,
)


def test_complex_group_bill_routes_to_review_before_transaction() -> None:
    request = ('Sarthak paid 17000 for a meal shared by six people. A paid a cafe bill. '
               'Apply a 10% coupon and split the 2.7% card fee among A, C, D and E.')
    assert _is_complex_settlement_request(request)
    assert _obvious_specialist(request) == 'split'
    assert _required_tools(request, 'split') == {'create_settlement_draft'}
    assert not _is_complex_settlement_request('spent 90 on food')


def test_single_bill_quantity_and_debts_stays_on_transaction_split_flow() -> None:
    request = (
        'Spent 927383 rs on A, B, C, D, E, F, G and myself. A, B and C got 7 vodka cranberries '
        'each, which were 7000rs each. Rest of the bill is divided equally. A owes C 17000, '
        'B contributed 29000, and C owes B 20000.'
    )

    assert not _is_complex_settlement_request(request)
    split_task = _split_task_for_request(request)
    assert split_task is not None
    assert request in split_task
    assert _required_tools(split_task, 'split') == {'create_split'}


def test_legacy_string_queue_is_normalized_to_a_verifiable_task_contract() -> None:
    task = "Record salary ₹60,000."

    contracts = _sync_task_contracts([task], None, original_request="Got salary ₹60,000.")
    contract = TaskContract.model_validate(contracts[0])

    assert contract.id
    assert contract.original_text == task
    assert contract.summary == task
    assert contract.intent == "create_transaction"
    assert contract.specialist == "transaction"
    assert set(contract.required_tools) == {"create_transaction", "create_transaction_batch"}
    assert "create_transaction:transaction.id" in contract.required_evidence
    assert contract.completion_mode == "any"
    assert contract.status == "queued"


def test_task_verifier_rejects_wrong_task_id_and_requires_all_analytics_reads() -> None:
    request = "Can I afford ₹900 sushi if I need ₹1,000 each day for the rest of the month?"
    contract = TaskContract.model_validate(
        _sync_task_contracts([request], None, original_request=request)[0]
    )
    balance_observation = {
        "task_id": contract.id,
        "tool": "get_account_balances",
        "ok": True,
        "data": {"accounts": []},
    }

    assert set(contract.required_tools) == {"get_account_balances", "get_current_datetime"}
    assert not _verify_task_contract(
        contract,
        {"task_id": contract.id, "status": "success", "tool_observations": [balance_observation]},
    )
    assert not _verify_task_contract(
        contract,
        {
            "task_id": "another-task",
            "status": "success",
            "tool_observations": [
                balance_observation,
                {
                    "task_id": contract.id,
                    "tool": "get_current_datetime",
                    "ok": True,
                    "data": {"current_datetime": "2026-10-23T19:41:00+05:30"},
                },
            ],
        },
    )


def test_queue_detour_keeps_original_transaction_task_id() -> None:
    transaction_task = "Spent ₹99 on Food"
    original = _sync_task_contracts(
        [transaction_task], None, original_request=transaction_task
    )
    original_id = original[0]["id"]

    updated = _sync_task_contracts(
        ["Create account: Axis with ₹6,000", transaction_task],
        original,
        original_request=transaction_task,
    )

    assert updated[0]["id"] != original_id
    assert updated[0]["specialist"] == "account"
    assert updated[1]["id"] == original_id
    assert updated[1]["summary"] == transaction_task
def test_most_spending_question_routes_to_analytics() -> None:
    request = 'what did I spend the most on this week'
    assert _obvious_specialist(request) == 'analytics'
    assert _matches_observed_action(request, {
        'tool': 'get_spending_summary', 'data': {'total_spent_paise': 1000},
    })

    transaction_request = 'which transaction I spent most on'
    assert _obvious_specialist(transaction_request) == 'analytics'
    assert _matches_observed_action(transaction_request, {
        'tool': 'get_transactions', 'data': {'transactions': [{'amount_paise': 1000}]},
    })
    assert not _matches_observed_action(transaction_request, {
        'tool': 'get_spending_summary', 'data': {'total_spent_paise': 1000},
    })


@pytest.mark.parametrize("reply", ["Medicines", "Use Health", "put it under Food"])
def test_category_answer_for_pending_transaction_gets_memory_signal(reply: str) -> None:
    signal = _category_reply_memory_signal(
        pending_question="Which category should I use for this expense?",
        pending_task="spent 99 on pcm",
        reply=reply,
    )

    assert signal == {"signal_type": "category_mapping"}


def test_category_memory_signal_is_not_set_for_non_transaction_or_cancel() -> None:
    question = "Which category should I use for this expense?"
    assert _category_reply_memory_signal(
        pending_question=question, pending_task="show category totals", reply="Medicines",
    ) is None
    assert _category_reply_memory_signal(
        pending_question=question, pending_task="spent 99 on pcm", reply="cancel",
    ) is None


@pytest.mark.asyncio
async def test_plain_text_category_followup_preserves_memory_signal_without_graph_interrupt() -> None:
    graph = _graph()
    pending_question = "Which category should I use for this expense? The available categories are Food, Medicine."

    class Snapshot:
        values = {
            "task_request": "spent 83 on ibu",
            "task_queue": ["record an expense for ibu"],
            "tasks_completed": False,
            "final_response": pending_question,
            "conversation_history": [
                {"role": "user", "content": "spent 83 on ibu"},
                {"role": "assistant", "content": pending_question},
            ],
        }
        interrupts: list[Any] = []

    class CapturingGraph:
        captured_input: dict[str, Any] | None = None

        async def aget_state(self, _config: dict[str, Any]) -> Snapshot:
            return Snapshot()

        async def ainvoke(self, input_value: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            self.captured_input = input_value
            return {}

    capturing_graph = CapturingGraph()
    graph.graph = capturing_graph  # type: ignore[assignment]
    await graph.invoke(user_id=uuid.uuid4(), thread_id="thread", message="Medicine")

    assert capturing_graph.captured_input is not None
    assert capturing_graph.captured_input["memory_review_signal"] == {"signal_type": "category_mapping"}


@pytest.mark.asyncio
async def test_next_turn_recovers_verified_transaction_reference_from_legacy_checkpoint() -> None:
    graph = _graph()
    transaction_id = str(uuid.uuid4())
    source_request = '1608 on dinner at masato with Sudhansu Sujal and Rujul'

    class Snapshot:
        values = {
            'conversation_history': [{'role': 'user', 'content': source_request}],
            'tool_event_history': [{
                'tool': 'create_transaction', 'ok': True, 'request': source_request,
                'data': {'transaction': {'id': transaction_id, 'amount_paise': 160800, 'merchant': 'Masato'}},
            }],
        }
        interrupts: list[Any] = []

    class CapturingGraph:
        captured_input: dict[str, Any] | None = None

        async def aget_state(self, _config: dict[str, Any]) -> Snapshot:
            return Snapshot()

        async def ainvoke(self, input_value: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            self.captured_input = input_value
            return {}

    capturing_graph = CapturingGraph()
    graph.graph = capturing_graph  # type: ignore[assignment]
    await graph.invoke(user_id=uuid.uuid4(), thread_id='masato', message='Create split for this')

    assert capturing_graph.captured_input is not None
    references = capturing_graph.captured_input['verified_transaction_references']
    assert [reference['id'] for reference in references] == [transaction_id]
    assert references[0]['source_request'] == source_request


@pytest.mark.asyncio
async def test_supervisor_handoff_forwards_memory_signal_to_transaction_specialist() -> None:
    graph = _graph()
    supervisor = ScriptedSupervisor([SupervisorDecision(action="route", specialist="transaction")])
    graph._supervisor = supervisor  # type: ignore[assignment]
    state = {
        "user_id": str(uuid.uuid4()),
        "messages": [HumanMessage(content="Medicine")],
        "task_request": "please continue",
        "task_queue": ["save the pending expense"],
        "memory_review_signal": {"signal_type": "category_mapping"},
        "conversation_history": [
            {"role": "user", "content": "spent 83 on ibu"},
            {"role": "assistant", "content": "Which category should I use?"},
            {"role": "user", "content": "Medicine"},
        ],
    }

    await graph._supervise(state)  # type: ignore[arg-type]

    assert supervisor.calls[0][0].constraints["memory_review_signal"] == {
        "signal_type": "category_mapping",
    }

    handoff_messages = graph._initial_specialist_messages(state, "transaction", {})
    trusted_handoff = handoff_messages[-1].content
    assert isinstance(trusted_handoff, str)
    serialized_handoff = trusted_handoff.split("Trusted handoff:\n", 1)[1]
    handoff_context = json.loads(serialized_handoff)
    assert handoff_context["constraints"]["memory_review_signal"] == {
        "signal_type": "category_mapping",
    }


@pytest.mark.asyncio
async def test_memory_review_gate_requires_signal_and_verified_transaction_creation() -> None:
    signal = {"signal_type": "category_mapping"}
    transaction_id = str(uuid.uuid4())

    eligible = await AgenticSupervisorGraph._memory_review_gate({
        "memory_review_signal": signal,
        "results": [{
            "specialist": "transaction",
            "status": "success",
            "data": {"created_transactions": [{"id": transaction_id}]},
        }],
    })
    assert eligible == {
        "memory_review_eligible": True,
        "memory_review_transaction_ids": [transaction_id],
    }

    no_signal = await AgenticSupervisorGraph._memory_review_gate({
        "results": [{
            "specialist": "transaction",
            "status": "success",
            "data": {"created_transactions": [{"id": transaction_id}]},
        }],
    })
    failed_transaction = await AgenticSupervisorGraph._memory_review_gate({
        "memory_review_signal": signal,
        "results": [{
            "specialist": "transaction",
            "status": "failed",
            "data": {"created_transactions": [{"id": transaction_id}]},
        }],
    })
    assert no_signal["memory_review_eligible"] is False
    assert failed_transaction["memory_review_eligible"] is False


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
    # The clear category intent is routed directly, without asking the
    # supervisor model to repeat the deterministic route.
    assert len(supervisor.calls) == 1
    assert supervisor.calls[0][1][-1]["specialist"] == "category"


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


def test_itemized_split_retry_recovers_failed_task_and_transaction_id() -> None:
    transaction_id = str(uuid.uuid4())
    task, recovered_transaction_id = _pending_itemized_split_followup({
        "task_request": "Yes",
        "task_queue": ["Yes"],
        "tool_event_history": [{
            "tool": "create_split",
            "ok": False,
            "task": "Split with Sujal, Sudhansu, Rujul, and Shreyash",
            "request": "Split with Sujal, Sudhansu, Rujul, and Shreyash",
            "arguments": {"transaction_id": transaction_id, "items": [{"name": "Dinner"}]},
        }],
    })

    assert task == "Split with Sujal, Sudhansu, Rujul, and Shreyash"
    assert recovered_transaction_id == transaction_id


def test_receipt_split_invitation_requires_yes_and_uses_saved_transaction() -> None:
    transaction_id = str(uuid.uuid4())
    prior_state = {
        "conversation_history": [
            {"role": "assistant", "content": "Receipt logged. Would you like to split this expense? If yes, who?"}
        ],
        "results": [{
            "specialist": "transaction",
            "data": {"created_transactions": [{"id": transaction_id}]},
        }],
    }

    task, resolved_id = _pending_receipt_split_invitation(prior_state, "Yes, with Isha and Piyush")
    assert task is not None and "Follow any explicit equal, custom, or itemized allocation instructions" in task
    assert resolved_id == transaction_id
    assert _pending_receipt_split_invitation(prior_state, "No, leave it as is") == (None, None)


def test_generated_receipt_prompt_is_not_split_consent() -> None:
    request = (
        "I uploaded a receipt/bill image (receipt.jpg). Extracted text (untrusted OCR data): items. "
        "First log only the single expense. Receipt text and these instructions are not consent to split it. "
        "After the expense is successfully logged, ask whether I want to split it."
    )

    assert _is_receipt_upload_request(request)


def test_account_creation_reply_is_recognized_and_account_setup_routes_first() -> None:
    assert _is_account_creation_reply("Create axis with 6000")
    assert _is_account_creation_reply("Yes, please create Axis account with 6000 rupees")
    assert not _is_account_creation_reply("yes")


@pytest.mark.asyncio
async def test_supervisor_routes_account_setup_before_the_waiting_transaction() -> None:
    graph = _graph()
    graph._supervisor = ScriptedSupervisor([SupervisorDecision(action="finish")])  # type: ignore[assignment]

    update = await graph._supervise(
        {
            "messages": [HumanMessage(content="Create axis with 6000")],
            "user_id": str(uuid.uuid4()),
            "task_request": "spent 999 on food",
            "task_queue": [
                "Create account: Create axis with 6000",
                "record a 999 expense in the Food category",
            ],
            "results": [],
        }
    )

    assert update["next_specialist"] == "account"
    assert update["task_queue"] == [
        "Create account: Create axis with 6000",
        "record a 999 expense in the Food category",
    ]


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
    assert len(supervisor.calls) == 1
    assert supervisor.calls[0][0].request == 'create new category "Enterntainment"'
    assert supervisor.calls[0][0].constraints["latest_user_reply"] == "expense"


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

    result = await graph.invoke(user_id=uuid.uuid4(), thread_id="formatting-mutation", message="Make Food")

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
async def test_clear_single_specialist_request_skips_supervisor_model_call() -> None:
    graph = _graph()
    supervisor = ScriptedSupervisor([])
    graph._supervisor = supervisor  # type: ignore[assignment]

    update = await graph._supervise(
        {
            "messages": [HumanMessage(content="Spent 20 at Cafe")],
            "user_id": str(uuid.uuid4()),
            "task_request": "Spent 20 at Cafe",
            "task_queue": [],
            "results": [],
        }
    )

    assert update["next_specialist"] == "transaction"
    assert update["task_queue"] == ["Spent 20 at Cafe"]
    assert supervisor.calls == []


@pytest.mark.asyncio
async def test_account_mention_with_transaction_query_keeps_supervisor_planning() -> None:
    graph = _graph()
    supervisor = ScriptedSupervisor(
        [SupervisorDecision(action="route", specialist="analytics", tasks=["Show transactions from Axis"])]
    )
    graph._supervisor = supervisor  # type: ignore[assignment]
    request = "Show transactions from my Axis account"

    update = await graph._supervise(
        {
            "messages": [HumanMessage(content=request)],
            "user_id": str(uuid.uuid4()),
            "task_request": request,
            "task_queue": [],
            "results": [],
        }
    )

    assert len(supervisor.calls) == 1
    assert update["next_specialist"] == "analytics"


@pytest.mark.asyncio
async def test_transaction_that_also_requests_a_split_keeps_supervisor_planning() -> None:
    graph = _graph()
    supervisor = ScriptedSupervisor(
        [
            SupervisorDecision(
                action="route",
                specialist="transaction",
                tasks=["Record the dinner expense", "Create a split for it with Isha"],
            )
        ]
    )
    graph._supervisor = supervisor  # type: ignore[assignment]
    request = "Spent 1500 on dinner with Isha"

    update = await graph._supervise(
        {
            "messages": [HumanMessage(content=request)],
            "user_id": str(uuid.uuid4()),
            "task_request": request,
            "task_queue": [],
            "results": [],
        }
    )

    assert len(supervisor.calls) == 1
    assert update["next_specialist"] == "transaction"
    assert update["task_queue"][0] == request
    assert any("split" in task.casefold() for task in update["task_queue"])


@pytest.mark.asyncio
async def test_verified_transaction_advances_to_distinct_split_contract_before_routing() -> None:
    graph = _graph()
    supervisor = ScriptedSupervisor([])
    graph._supervisor = supervisor  # type: ignore[assignment]
    request = "Spent 1608 for dinner at Masato with Rujul Sudhansu and Sujal"
    split_task = _split_task_for_request(request)
    assert split_task is not None
    queue = [request, split_task]
    contracts = _sync_task_contracts(queue, None, original_request=request)
    transaction_contract = TaskContract.model_validate(contracts[0])
    split_contract = TaskContract.model_validate(contracts[1])
    assert transaction_contract.id != split_contract.id
    assert set(transaction_contract.required_tools) == {"create_transaction", "create_transaction_batch"}
    assert split_contract.required_tools == ["create_split"]
    transaction_id = str(uuid.uuid4())
    split_id = str(uuid.uuid4())
    transaction_summary = "Recorded the ₹1,608 Masato dinner expense."
    split_summary = "Split ₹1,608 equally; each person owes ₹402."

    transaction_result = {
        "specialist": "transaction",
        "task_id": transaction_contract.id,
        "status": "success",
        "summary": transaction_summary,
        "data": {
            "transaction": {"id": transaction_id, "amount_paise": 160800, "merchant": "Masato"},
            "created_transactions": [
                {"id": transaction_id, "amount_paise": 160800, "merchant": "Masato"},
            ],
            "observed_actions": [
                {
                    "task_id": transaction_contract.id,
                    "tool": "create_transaction",
                    "data": {"transaction": {"id": transaction_id, "amount_paise": 160800}},
                }
            ],
        },
        "tool_observations": [
            {
                "task_id": transaction_contract.id,
                "tool": "create_transaction",
                "ok": True,
                "data": {"transaction": {"id": transaction_id, "amount_paise": 160800}},
            }
        ],
    }

    after_transaction = await graph._supervise(
        {
            "messages": [HumanMessage(content=request)],
            "user_id": str(uuid.uuid4()),
            "task_request": request,
            "task_queue": queue,
            "task_contracts": contracts,
            "results": [transaction_result],
        }
    )

    assert supervisor.calls == []
    assert after_transaction["next_specialist"] == "supervisor"
    assert len(after_transaction["task_queue"]) == 1
    assert after_transaction["task_queue"][0].startswith("create an equal split")
    progressed_contracts = [TaskContract.model_validate(item) for item in after_transaction["task_contracts"]]
    assert [(item.id, item.status) for item in progressed_contracts] == [
        (transaction_contract.id, "completed"),
        (split_contract.id, "queued"),
    ]

    split_result = {
        "specialist": "split",
        "task_id": split_contract.id,
        "status": "success",
        "summary": split_summary,
        "data": {
            "observed_actions": [
                {
                    "task_id": split_contract.id,
                    "tool": "create_split",
                    "data": {"split": {"id": split_id, "transaction_id": transaction_id}},
                }
            ],
            "split": {
                "id": split_id,
                "transaction_id": transaction_id,
                "title": "Masato",
                "owner_share_paise": 40200,
                "total_paise": 160800,
                "participants": [
                    {"name": "Rujul", "share_paise": 40200},
                    {"name": "Sudhansu", "share_paise": 40200},
                    {"name": "Sujal", "share_paise": 40200},
                ],
            },
        },
        "tool_observations": [
            {
                "task_id": split_contract.id,
                "tool": "create_split",
                "ok": True,
                "data": {"split": {"id": split_id, "transaction_id": transaction_id}},
            }
        ],
    }
    completed = await graph._supervise(
        {
            "messages": [HumanMessage(content=request)],
            "user_id": str(uuid.uuid4()),
            "task_request": request,
            "task_queue": after_transaction["task_queue"],
            "task_contracts": after_transaction["task_contracts"],
            "completed_tasks": after_transaction["completed_tasks"],
            "created_transaction_ids": after_transaction["created_transaction_ids"],
            "results": [split_result],
        }
    )

    assert supervisor.calls == []
    assert completed["tasks_completed"] is True
    assert completed["task_queue"] == []
    assert completed["final_response"] == (
        "Recorded ₹1,608.00 for Masato and added an equal split with Rujul, Sudhansu, Sujal. "
        "Your share and each participant's share is ₹402.00."
    )
    assert "could not verify" not in completed["final_response"].casefold()
    assert [(item["id"], item["status"]) for item in completed["task_contracts"]] == [
        (transaction_contract.id, "completed"),
        (split_contract.id, "completed"),
    ]


@pytest.mark.asyncio
async def test_verified_terminal_tool_observation_skips_final_supervisor_call() -> None:
    graph = _graph()
    supervisor = ScriptedSupervisor([])
    graph._supervisor = supervisor  # type: ignore[assignment]
    task = "Spent 99 on pcm"
    result = {
        "specialist": "transaction",
        "status": "success",
        "summary": "The ₹99 expense was recorded under Health.",
        "data": {
            "observed_actions": [
                {
                    "tool": "create_transaction",
                        "data": {
                            "transaction": {
                                "id": str(uuid.uuid4()),
                                "amount_paise": 9900,
                                "merchant": "pcm",
                            }
                        },
                }
            ]
        },
    }

    update = await graph._supervise(
        {
            "messages": [HumanMessage(content=task)],
            "user_id": str(uuid.uuid4()),
            "task_request": task,
            "task_queue": [task],
            "results": [result],
        }
    )

    assert update["tasks_completed"] is True
    assert update["task_queue"] == []
    assert update["final_response"] == result["summary"]
    assert supervisor.calls == []


@pytest.mark.asyncio
async def test_verified_affordability_answer_is_not_replaced_by_supervisor_fallback() -> None:
    graph = _graph()
    supervisor = ScriptedSupervisor([])
    graph._supervisor = supervisor  # type: ignore[assignment]
    task = "Can I afford 900rps sushi considering I’ll need 1k each day for the rest of the month"
    summary = (
        "Today is October 23. Reserving ₹1,000 for each of the 8 days after today and spending ₹900 "
        "leaves ₹4,489 from the verified ₹13,389 balance."
    )
    result = {
        "specialist": "analytics",
        "status": "success",
        "summary": summary,
        "data": {
                "observed_actions": [
                    {
                        "tool": "get_current_datetime",
                        "data": {"current_datetime": "2026-10-23T19:41:00+05:30"},
                    },
                    {"tool": "get_account_balances", "data": {"accounts": []}},
                ]
        },
    }

    update = await graph._supervise(
        {
            "messages": [HumanMessage(content=task)],
            "user_id": str(uuid.uuid4()),
            "timezone": "Asia/Kolkata",
            "current_datetime": "2026-10-23T19:41:00+05:30",
            "task_request": task,
            "task_queue": [task],
            "results": [result],
        }
    )

    assert update["tasks_completed"] is True
    assert update["task_queue"] == []
    assert update["final_response"] == summary
    contract = TaskContract.model_validate(update["task_contracts"][0])
    assert contract.status == "completed"
    assert contract.result_summary == summary
    assert contract.intent == "analytics_query"
    assert supervisor.calls == []


@pytest.mark.asyncio
async def test_verified_salary_with_grouped_amount_and_period_is_not_replaced_by_supervisor_fallback() -> None:
    graph = _graph()
    supervisor = ScriptedSupervisor([])
    graph._supervisor = supervisor  # type: ignore[assignment]
    task = "Record salary ₹60,000."
    summary = 'The salary transaction of ₹60,000 was recorded under "Salary" in "Axis".'
    result = {
        "specialist": "transaction",
        "status": "success",
        "summary": summary,
        "data": {
            "observed_actions": [
                {
                    "tool": "create_transaction",
                    "data": {
                        "transaction": {
                            "id": str(uuid.uuid4()),
                            "amount_paise": 6_000_000,
                            "type": "income",
                            "merchant": None,
                        }
                    },
                }
            ]
        },
    }

    update = await graph._supervise(
        {
            "messages": [HumanMessage(content="Got salary ₹60,000.")],
            "user_id": str(uuid.uuid4()),
            "task_request": "Got salary ₹60,000.",
            "task_queue": [task],
            "results": [result],
        }
    )

    assert update["tasks_completed"] is True
    assert update["task_queue"] == []
    assert update["final_response"] == summary
    contract = TaskContract.model_validate(update["task_contracts"][0])
    assert contract.status == "completed"
    assert contract.result_summary == summary
    assert contract.intent == "create_transaction"
    assert supervisor.calls == []


@pytest.mark.asyncio
async def test_missing_tool_observation_still_calls_supervisor_and_cannot_finish() -> None:
    graph = _graph()
    supervisor = ScriptedSupervisor([SupervisorDecision(action="finish")])
    graph._supervisor = supervisor  # type: ignore[assignment]
    task = "Spent 99 on pcm"

    update = await graph._supervise(
        {
            "messages": [HumanMessage(content=task)],
            "user_id": str(uuid.uuid4()),
            "task_request": task,
            "task_queue": [task],
            "results": [{"specialist": "transaction", "status": "success", "summary": "Done."}],
        }
    )

    assert len(supervisor.calls) == 1
    assert update["tasks_completed"] is False


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
