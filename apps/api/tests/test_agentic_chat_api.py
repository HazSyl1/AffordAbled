from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.core.dependencies import get_semantic_guardrail, get_transaction_extraction_llm
from app.domain.ports import GuardrailAssessment, GuardrailDecision
from app.infrastructure.ai.agents.contracts import SupervisorDecision
from tests.helpers import DEFAULT_CATEGORIES, auth_headers, register_and_get_token


class AllowingGuardrail:
    async def assess(self, _message: str) -> GuardrailAssessment:
        return GuardrailAssessment(decision=GuardrailDecision.ALLOW, confidence=1.0, layer="test")


class ScriptedAgenticLLM:
    """A scripted model exercising the public checkpointed API boundary."""

    def __init__(self) -> None:
        self.supervisor_decisions = [
            SupervisorDecision(
                action="route",
                specialist="category",
                handoff={"names": ["Food", "Groceries"]},
                tasks=["Create Food as an expense category", "Create Groceries as an expense category"],
            ),
            SupervisorDecision(action="finish", response="Created Food and Groceries as expense categories."),
        ]
        self.category_steps = 0

    def with_structured_output(self, schema: type[Any], **_kwargs: Any) -> RunnableLambda:
        def respond(prompt: Any) -> Any:
            del prompt
            if schema is SupervisorDecision:
                return self.supervisor_decisions.pop(0)
            raise AssertionError(f"Unexpected agent prompt or schema: {schema}")

        return RunnableLambda(respond)

    def bind_tools(self, _tools: list[Any], **_kwargs: Any) -> RunnableLambda:
        async def respond(messages: list[Any]) -> AIMessage:
            system = str(messages[0].content)
            if "Category specialist" in system:
                self.category_steps += 1
                calls = [
                    ("ask_user", {"question": "Should Food and Groceries be expense or income categories?"}),
                    ("create_category", {"arguments": {"name": "Food", "type": "expense"}}),
                    ("create_category", {"arguments": {"name": "Groceries", "type": "expense"}}),
                ]
                if self.category_steps <= len(calls):
                    name, args = calls[self.category_steps - 1]
                    return AIMessage(
                        content="",
                        tool_calls=[{"name": name, "args": args, "id": str(self.category_steps)}],
                    )
                return AIMessage(content="Created Food and Groceries as expense categories.")
            if "formatting specialist" in system:
                return AIMessage(content="Created Food and Groceries as expense categories.")
            raise AssertionError(f"Unexpected bound-tool prompt: {system}")

        return RunnableLambda(respond)


class TransactionSuccessLLM:
    """Create a transaction, read categories, then report completion."""

    def __init__(self, account_id: str, category_id: str) -> None:
        self.account_id = account_id
        self.category_id = category_id
        self.supervisor_prompts: list[str] = []
        self.transaction_prompts: list[str] = []
        self.supervisor_decisions = [
            SupervisorDecision(action="route", specialist="transaction"),
            SupervisorDecision(action="finish", response="Recorded the pan shop expense."),
        ]
        self.transaction_steps = 0

    def with_structured_output(self, schema: type[Any], **_kwargs: Any) -> RunnableLambda:
        def respond(_prompt: Any) -> Any:
            self.supervisor_prompts.append(str(_prompt))
            if schema is SupervisorDecision:
                return self.supervisor_decisions.pop(0)
            raise AssertionError(f"Unexpected structured output: {schema}")

        return RunnableLambda(respond)

    def bind_tools(self, _tools: list[Any], **_kwargs: Any) -> RunnableLambda:
        async def respond(messages: list[Any]) -> AIMessage:
            if "transaction specialist" not in str(messages[0].content):
                raise AssertionError("Only the transaction specialist should run")
            self.transaction_prompts.append(str(messages[1].content))
            self.transaction_steps += 1
            if self.transaction_steps == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "create_transaction",
                            "args": {
                                "arguments": {
                                    "account_id": self.account_id,
                                    "category_id": self.category_id,
                                    "type": "expense",
                                    "amount_rupees": 20,
                                    "merchant": "pan shop",
                                }
                            },
                            "id": "create-pan-expense",
                        }
                    ],
                )
            if self.transaction_steps == 2:
                return AIMessage(
                    content="",
                    tool_calls=[{"name": "list_categories", "args": {"arguments": {}}, "id": "read-categories"}],
                )
            return AIMessage(content="The expense was recorded.")

        return RunnableLambda(respond)


class QueuedCategoryLLM:
    def __init__(self) -> None:
        self.supervisor_decisions = [
            SupervisorDecision(
                action="route",
                specialist="category",
                tasks=["Create Dining as an expense category", "Create Pet Care as an expense category"],
            ),
            SupervisorDecision(action="finish", response="Created Dining as an expense category."),
            SupervisorDecision(action="route", specialist="category"),
            SupervisorDecision(action="finish", response="Created Pet Care as an expense category."),
        ]
        self.category_steps = 0

    def with_structured_output(self, schema: type[Any], **_kwargs: Any) -> RunnableLambda:
        def respond(_prompt: Any) -> Any:
            assert schema is SupervisorDecision
            return self.supervisor_decisions.pop(0)

        return RunnableLambda(respond)

    def bind_tools(self, _tools: list[Any], **_kwargs: Any) -> RunnableLambda:
        async def respond(messages: list[Any]) -> AIMessage:
            assert "Category specialist" in str(messages[0].content)
            if len(messages) == 2:
                self.category_steps += 1
                name = "Dining" if self.category_steps == 1 else "Pet Care"
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "create_category",
                            "args": {"arguments": {"name": name, "type": "expense"}},
                            "id": f"create-{name.lower().replace(' ', '-')}",
                        }
                    ],
                )
            return AIMessage(content="Category created.")

        return RunnableLambda(respond)


class BatchMutationLLM:
    def __init__(
        self,
        specialist: str,
        tasks: list[str],
        calls: list[tuple[str, dict[str, Any]]],
        summary: str,
        parallel_calls: bool = False,
        specialist_reply: str = "Completed all requested actions.",
    ) -> None:
        self.specialist = specialist
        self.calls = calls
        self.steps = 0
        self.parallel_calls = parallel_calls
        self.specialist_reply = specialist_reply
        self.supervisor_prompts: list[str] = []
        self.supervisor_decisions = [
            SupervisorDecision(action="route", specialist=specialist, tasks=tasks),
            SupervisorDecision(action="finish", response=summary),
        ]

    def with_structured_output(self, schema: type[Any], **_kwargs: Any) -> RunnableLambda:
        def respond(_prompt: Any) -> Any:
            assert schema is SupervisorDecision
            self.supervisor_prompts.append(str(_prompt))
            return self.supervisor_decisions.pop(0)

        return RunnableLambda(respond)


    def bind_tools(self, _tools: list[Any], **_kwargs: Any) -> RunnableLambda:
        async def respond(messages: list[Any]) -> AIMessage:
            assert f"{self.specialist} specialist" in str(messages[0].content).casefold()
            if self.parallel_calls and self.steps == 0:
                self.steps = len(self.calls)
                return AIMessage(
                    content="",
                    tool_calls=[
                        {"name": name, "args": args, "id": f"parallel-step-{index}"}
                        for index, (name, args) in enumerate(self.calls)
                    ],
                )
            if self.steps < len(self.calls):
                name, args = self.calls[self.steps]
                self.steps += 1
                return AIMessage(
                    content="", tool_calls=[{"name": name, "args": args, "id": f"batch-step-{self.steps}"}]
                )
            return AIMessage(content=self.specialist_reply)

        return RunnableLambda(respond)


@pytest.mark.asyncio
async def test_complex_chat_bill_creates_review_draft_before_expense(client: AsyncClient, app: FastAPI) -> None:
    token = await register_and_get_token(client, 'complex-chat@example.com')
    message = 'I paid 102 rupees for food shared with A, including a 2 rupee card fee that A covers.'
    llm = BatchMutationLLM(
        'split', [message], [('create_settlement_draft', {'arguments': {'data': {
            'title': 'Shared food', 'participants': ['You', 'A'], 'debts': [],
            'bills': [{
                'id': 'meal', 'merchant': 'Food',
                'charges': [{'id': 'food', 'label': 'Food', 'amount_paise': 10000,
                             'shared_by': ['You', 'A'],
                             'source_quote': '102 rupees for food shared with A, including a 2 rupee card fee'}],
                'discounts': [],
                'extras': [{'label': 'Card fee', 'kind': 'fee', 'amount_paise': 200,
                            'shared_by': ['A']}],
                'payments': [{'person': 'You', 'amount_paise': 10200}],
            }],
        }}})], 'Draft prepared.', specialist_reply='Draft prepared.',
    )
    app.dependency_overrides[get_semantic_guardrail] = lambda: AllowingGuardrail()
    app.dependency_overrides[get_transaction_extraction_llm] = lambda: llm
    try:
        response = await client.post('/api/v1/chat', json={'message': message}, headers=auth_headers(token))
        assert response.status_code == 200, response.text
        assert response.json()['show_completion_popup'] is False
        assert response.json()['transaction_logged'] is False
        assert '[[settlement:' in response.json()['message']
        assert (await client.get('/api/v1/transactions', headers=auth_headers(token))).json() == []
    finally:
        app.dependency_overrides.pop(get_semantic_guardrail, None)
        app.dependency_overrides.pop(get_transaction_extraction_llm, None)


@pytest.mark.asyncio
async def test_analytics_completion_keeps_chat_open_without_popup(client: AsyncClient, app: FastAPI) -> None:
    token = await register_and_get_token(client, "agentic-analytics-no-popup@example.com")
    long_reply = "Account balances are available.\n" + "\n".join(
        f"Recent transaction {index}: ₹{index}.00" for index in range(1, 51)
    )
    assert len(long_reply) > 1_000
    llm = BatchMutationLLM(
        "analytics",
        ["Show my recent transactions"],
        [
            ("get_account_balances", {"arguments": {}}),
            (
                "get_transactions",
                {"arguments": {"date_from": "2026-10-01T00:00:00+00:00", "date_to": "2026-10-31T23:59:59+00:00"}},
            ),
        ],
        long_reply,
        specialist_reply=long_reply,
    )
    app.dependency_overrides[get_semantic_guardrail] = lambda: AllowingGuardrail()
    app.dependency_overrides[get_transaction_extraction_llm] = lambda: llm
    try:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "Show my account balances and show my recent transactions"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200, response.text
        assert response.json()["tasks_completed"] is True
        assert response.json()["show_completion_popup"] is False
        assert response.json()["message"] == long_reply
        assert llm.steps == 2
        assert "Show my account balances" in llm.supervisor_prompts[0]
        assert "show my recent transactions" in llm.supervisor_prompts[0]
        assert len(llm.supervisor_prompts) == 1
    finally:
        app.dependency_overrides.pop(get_semantic_guardrail, None)
        app.dependency_overrides.pop(get_transaction_extraction_llm, None)


@pytest.mark.asyncio
async def test_chat_creates_categories_from_parallel_tool_calls(client: AsyncClient, app: FastAPI) -> None:
    token = await register_and_get_token(client, "agentic-parallel-categories@example.com")
    headers = auth_headers(token)
    llm = BatchMutationLLM(
        "category",
        ["Create Test Snacks expense category", "Create Test Drinks expense category"],
        [
            ("create_category", {"arguments": {"name": "Test Snacks", "type": "expense"}}),
            ("create_category", {"arguments": {"name": "Test Drinks", "type": "expense"}}),
        ],
        "Created both expense categories.",
        parallel_calls=True,
    )
    app.dependency_overrides[get_semantic_guardrail] = lambda: AllowingGuardrail()
    app.dependency_overrides[get_transaction_extraction_llm] = lambda: llm
    try:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "Create Test Snacks and Test Drinks as expense categories"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["tasks_completed"] is True
        assert response.json()["show_completion_popup"] is True
        categories = await client.get("/api/v1/categories", headers=headers)
        assert {(item["name"], item["type"]) for item in categories.json()} == DEFAULT_CATEGORIES | {
            ("Test Snacks", "expense"),
            ("Test Drinks", "expense"),
        }
    finally:
        app.dependency_overrides.pop(get_semantic_guardrail, None)
        app.dependency_overrides.pop(get_transaction_extraction_llm, None)


@pytest.mark.asyncio
async def test_chat_consumes_two_account_tasks_from_one_specialist_result(client: AsyncClient, app: FastAPI) -> None:
    token = await register_and_get_token(client, "agentic-batch-accounts@example.com")
    llm = BatchMutationLLM(
        "account",
        ["Create Axis bank account", "Create HDFC bank account"],
        [
            ("create_account", {"arguments": {"name": "Axis", "type": "bank", "balance_rupees": 100}}),
            ("create_account", {"arguments": {"name": "HDFC", "type": "bank", "balance_rupees": 200}}),
        ],
        "Created Axis and HDFC bank accounts.",
    )
    llm.supervisor_decisions[1] = SupervisorDecision(action="route", specialist="account")
    app.dependency_overrides[get_semantic_guardrail] = lambda: AllowingGuardrail()
    app.dependency_overrides[get_transaction_extraction_llm] = lambda: llm
    try:
        response = await client.post(
            "/api/v1/chat", json={"message": "Create Axis and HDFC bank accounts"}, headers=auth_headers(token)
        )
        assert response.status_code == 200, response.text
        assert response.json()["tasks_completed"] is True
        assert llm.steps == 2
        assert llm.supervisor_prompts == []  # Deterministic route and verified tool results skip the supervisor.
        accounts = await client.get("/api/v1/accounts", headers=auth_headers(token))
        assert {item["name"] for item in accounts.json()} == {"Axis", "HDFC"}
    finally:
        app.dependency_overrides.pop(get_semantic_guardrail, None)
        app.dependency_overrides.pop(get_transaction_extraction_llm, None)


@pytest.mark.asyncio
async def test_chat_routes_category_creation_even_if_first_supervisor_decision_finishes(
    client: AsyncClient, app: FastAPI
) -> None:
    token = await register_and_get_token(client, "agentic-premature-category-finish@example.com")
    headers = auth_headers(token)
    llm = BatchMutationLLM(
        "category",
        ["Create Food as an expense category", "Create Drinks as an expense category"],
        [
            ("create_category", {"arguments": {"name": "Food", "type": "expense"}}),
            ("create_category", {"arguments": {"name": "Drinks", "type": "expense"}}),
        ],
        "Food already exists and Drinks was created as an expense category.",
    )
    llm.supervisor_decisions[0] = SupervisorDecision(
        action="finish",
        response="I could not complete that request.",
        tasks=["Create Food as an expense category", "Create Drinks as an expense category"],
    )
    app.dependency_overrides[get_semantic_guardrail] = lambda: AllowingGuardrail()
    app.dependency_overrides[get_transaction_extraction_llm] = lambda: llm
    try:
        response = await client.post(
            "/api/v1/chat", json={"message": 'create "Food" and "Drinks" are expense categories'}, headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["tasks_completed"] is True
        assert response.json()["message"] == "Food already exists and Drinks was created as an expense category."
        categories = await client.get("/api/v1/categories", headers=headers)
        assert [(item["name"], item["type"]) for item in categories.json()].count(("Food", "expense")) == 1
        assert ("Drinks", "expense") in {(item["name"], item["type"]) for item in categories.json()}
    finally:
        app.dependency_overrides.pop(get_semantic_guardrail, None)
        app.dependency_overrides.pop(get_transaction_extraction_llm, None)


@pytest.mark.asyncio
async def test_category_queue_completes_when_only_missing_category_needs_a_tool(
    client: AsyncClient, app: FastAPI
) -> None:
    token = await register_and_get_token(client, "agentic-existing-food-new-drinks@example.com")
    headers = auth_headers(token)
    llm = BatchMutationLLM(
        "category",
        ["Create Food as an expense category", "Create Drinks as an expense category"],
        [("create_category", {"arguments": {"name": "Drinks", "type": "expense"}})],
        "Food already exists and Drinks was created as an expense category.",
    )
    app.dependency_overrides[get_semantic_guardrail] = lambda: AllowingGuardrail()
    app.dependency_overrides[get_transaction_extraction_llm] = lambda: llm
    try:
        response = await client.post(
            "/api/v1/chat", json={"message": 'create "Food" and "Drinks" are expense categories'}, headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["tasks_completed"] is True
        assert response.json()["message"] == "Food already exists and Drinks was created as an expense category."
        assert llm.steps == 1
        assert llm.supervisor_prompts == []  # The requested categories were verified from saved rows.
        categories = await client.get("/api/v1/categories", headers=headers)
        assert {(item["name"], item["type"]) for item in categories.json()} == DEFAULT_CATEGORIES | {
            ("Food", "expense"),
            ("Drinks", "expense"),
        }
    finally:
        app.dependency_overrides.pop(get_semantic_guardrail, None)
        app.dependency_overrides.pop(get_transaction_extraction_llm, None)


@pytest.mark.asyncio
async def test_category_queue_stays_incomplete_when_requested_category_is_missing(
    client: AsyncClient, app: FastAPI
) -> None:
    token = await register_and_get_token(client, "agentic-missing-drinks@example.com")
    headers = auth_headers(token)
    llm = BatchMutationLLM(
        "category",
        ["Create Food as an expense category", "Create Drinks as an expense category"],
        [("create_category", {"arguments": {"name": "Food", "type": "expense"}})],
        "Food and Drinks are ready.",
    )
    llm.supervisor_decisions.append(SupervisorDecision(action="finish", response="Done."))
    llm.supervisor_decisions.append(SupervisorDecision(action="finish", response="Done."))
    app.dependency_overrides[get_semantic_guardrail] = lambda: AllowingGuardrail()
    app.dependency_overrides[get_transaction_extraction_llm] = lambda: llm
    try:
        response = await client.post(
            "/api/v1/chat", json={"message": 'create "Food" and "Drinks" are expense categories'}, headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["tasks_completed"] is False
        categories = await client.get("/api/v1/categories", headers=headers)
        assert {(item["name"], item["type"]) for item in categories.json()} == DEFAULT_CATEGORIES
    finally:
        app.dependency_overrides.pop(get_semantic_guardrail, None)
        app.dependency_overrides.pop(get_transaction_extraction_llm, None)


@pytest.mark.asyncio
async def test_chat_consumes_two_transaction_tasks_from_one_batch(client: AsyncClient, app: FastAPI) -> None:
    token = await register_and_get_token(client, "agentic-batch-transactions@example.com")
    headers = auth_headers(token)
    account = await client.post(
        "/api/v1/accounts",
        json={"name": "Axis", "type": "bank", "balance_paise": 100000, "currency": "INR"},
        headers=headers,
    )
    category = await client.post("/api/v1/categories", json={"name": "Food", "type": "expense"}, headers=headers)
    assert account.status_code == 201
    assert category.status_code == 201
    llm = BatchMutationLLM(
        "transaction",
        ["Spent 20 at Cafe", "Paid 50 at Zepto"],
        [
            (
                "create_transaction_batch",
                {
                    "arguments": {
                        "transactions": [
                            {
                                "account_id": account.json()["id"],
                                "category_id": category.json()["id"],
                                "type": "expense",
                                "amount_rupees": 20,
                                "merchant": "Cafe",
                            },
                            {
                                "account_id": account.json()["id"],
                                "category_id": category.json()["id"],
                                "type": "expense",
                                "amount_rupees": 50,
                                "merchant": "Zepto",
                            },
                        ]
                    }
                },
            )
        ],
        "Recorded the Cafe and Zepto expenses.",
    )
    app.dependency_overrides[get_semantic_guardrail] = lambda: AllowingGuardrail()
    app.dependency_overrides[get_transaction_extraction_llm] = lambda: llm
    try:
        response = await client.post(
            "/api/v1/chat", json={"message": "Spent 20 at Cafe and 50 at Zepto"}, headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["tasks_completed"] is True
        assert response.json()["transaction_logged"] is True
        transactions = await client.get("/api/v1/transactions", headers=headers)
        assert {item["merchant"] for item in transactions.json()} == {"Cafe", "Zepto"}
    finally:
        app.dependency_overrides.pop(get_semantic_guardrail, None)
        app.dependency_overrides.pop(get_transaction_extraction_llm, None)


@pytest.mark.asyncio
async def test_agentic_chat_completes_all_queued_category_tasks(client: AsyncClient, app: FastAPI) -> None:
    token = await register_and_get_token(client, "agentic-queued-categories@example.com")
    llm = QueuedCategoryLLM()
    app.dependency_overrides[get_semantic_guardrail] = lambda: AllowingGuardrail()
    app.dependency_overrides[get_transaction_extraction_llm] = lambda: llm

    try:
        response = await client.post(
            "/api/v1/chat",
                json={"message": "Create Dining and Pet Care as expense categories"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200, response.text
        assert response.json()["tasks_completed"] is True
        assert response.json()["message"] == (
            "Created Dining as an expense category.\nCreated Pet Care as an expense category."
        )
        categories = await client.get("/api/v1/categories", headers=auth_headers(token))
        assert {(item["name"], item["type"]) for item in categories.json()} == DEFAULT_CATEGORIES | {
            ("Dining", "expense"),
            ("Pet Care", "expense"),
        }
    finally:
        app.dependency_overrides.pop(get_semantic_guardrail, None)
        app.dependency_overrides.pop(get_transaction_extraction_llm, None)


@pytest.mark.asyncio
async def test_chat_sets_success_flag_after_verified_transaction_even_if_another_tool_runs(
    client: AsyncClient, app: FastAPI
) -> None:
    token = await register_and_get_token(client, "agentic-transaction-success@example.com")
    headers = auth_headers(token)
    account = await client.post(
        "/api/v1/accounts",
        json={"name": "Axis", "type": "bank", "balance_paise": 600000, "currency": "INR"},
        headers=headers,
    )
    category = await client.post("/api/v1/categories", json={"name": "Pan", "type": "expense"}, headers=headers)
    assert account.status_code == 201
    assert category.status_code == 201
    app.dependency_overrides[get_semantic_guardrail] = lambda: AllowingGuardrail()
    llm = TransactionSuccessLLM(account.json()["id"], category.json()["id"])
    app.dependency_overrides[get_transaction_extraction_llm] = lambda: llm

    try:
        response = await client.post("/api/v1/chat", json={"message": "spent 20 on pan shop"}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["transaction_logged"] is True
        assert response.json()["tasks_completed"] is True
        assert llm.supervisor_prompts == []  # The direct transaction route skips the supervisor model.
        assert "Axis" in llm.transaction_prompts[0]
        assert "Pan" in llm.transaction_prompts[0]
        transaction_id = response.json()["created_transaction_id"]
        assert transaction_id
        saved = await client.get(f"/api/v1/transactions/{transaction_id}", headers=headers)
        assert saved.status_code == 200
        assert saved.json()["amount_paise"] == 2000
    finally:
        app.dependency_overrides.pop(get_semantic_guardrail, None)
        app.dependency_overrides.pop(get_transaction_extraction_llm, None)


@pytest.mark.asyncio
async def test_agentic_chat_creates_multiple_categories_after_interrupt_resume(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    token = await register_and_get_token(client, "agentic-multiple-categories@example.com")
    llm = ScriptedAgenticLLM()
    app.dependency_overrides[get_semantic_guardrail] = lambda: AllowingGuardrail()
    # The app builds dependencies once per request, so retain the model object
    # across requests and verify graph checkpoint resume at the HTTP boundary.
    app.dependency_overrides[get_transaction_extraction_llm] = lambda: llm

    try:
        clarification = await client.post(
            "/api/v1/chat",
            json={"message": "Create 2 categories: Food and Groceries"},
            headers=auth_headers(token),
        )
        assert clarification.status_code == 200, clarification.text
        clarification_payload = clarification.json()
        assert "expense or income" in clarification_payload["message"]
        assert clarification_payload["tasks_completed"] is False

        completed = await client.post(
            "/api/v1/chat",
            json={"message": "Both expense", "thread_id": clarification_payload["thread_id"]},
            headers=auth_headers(token),
        )
        assert completed.status_code == 200, completed.text
        assert "Food" in completed.json()["message"]
        assert "Groceries" in completed.json()["message"]
        assert completed.json()["tasks_completed"] is True

        categories = await client.get("/api/v1/categories", headers=auth_headers(token))
        assert categories.status_code == 200
        assert {(item["name"], item["type"]) for item in categories.json()} == DEFAULT_CATEGORIES | {
            ("Food", "expense"),
            ("Groceries", "expense"),
        }
        transactions = await client.get("/api/v1/transactions", headers=auth_headers(token))
        assert transactions.status_code == 200
        assert transactions.json() == []
        assert completed.json()["transaction_logged"] is False
    finally:
        app.dependency_overrides.pop(get_semantic_guardrail, None)
        app.dependency_overrides.pop(get_transaction_extraction_llm, None)
