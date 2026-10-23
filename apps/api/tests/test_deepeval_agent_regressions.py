"""Stable DeepEval cases for LangGraph handoffs and financial invariants.

These cases run without an LLM or a database. They check the trusted boundaries
that must hold even when a model supplies misleading prose or tool arguments.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from deepeval import assert_test
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase
from fastapi import FastAPI
from httpx import AsyncClient

from app.application.services.quantity_split import QuantityAllocation, calculate_quantity_split
from app.core.config import get_settings
from app.infrastructure.ai.agents.contracts import HandoffContext, TaskContract
from app.infrastructure.ai.agents.runtime import merge_verified_transaction_references
from app.infrastructure.ai.agents.split import SplitToolset
from app.infrastructure.ai.agents.supervisor_graph import _verify_task_contract
from tests.helpers import auth_headers, register_and_get_token

GOLDENS = json.loads((Path(__file__).parent / "goldens" / "agent_regressions.json").read_text(encoding="utf-8"))


class ExactJsonMetric(BaseMetric):
    """Fail on any changed structured outcome, with no extra model call."""

    def __init__(self) -> None:
        self.threshold = 1.0
        self.score = 0.0
        self.reason = ""

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        self.score = float(test_case.actual_output == test_case.expected_output)
        self.reason = f"expected={test_case.expected_output}, actual={test_case.actual_output}"
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case, *args, **kwargs)

    @property
    def __name__(self) -> str:
        return "ExactJsonMetric"


def _evaluate(case: dict[str, Any]) -> Any:
    if case["kind"] == "task_completion":
        contract = TaskContract(
            id="salary-task",
            original_text="Record salary of 60000",
            summary="Record salary of 60000",
            intent="create_transaction",
            specialist="transaction",
            required_tools=["create_transaction"],
            required_evidence=["create_transaction:transaction.id"],
        )
        return _verify_task_contract(contract, case["result"])
    if case["kind"] == "followup_transaction":
        references = merge_verified_transaction_references([], case["events"])
        context = HandoffContext(
            user_id=uuid.UUID("77bba6f4-93bd-4b8d-a099-cbcd60838957"),
            request=case["reply"],
            history=[
                {"role": "user", "content": case["source_request"]},
                {"role": "user", "content": case["reply"]},
            ],
            constraints={
                "latest_user_reply": case["reply"],
                "verified_transaction_references": references,
            },
        )
        return SplitToolset._trusted_followup_transaction_id(context)
    if case["kind"] == "quantity_split":
        owner, shares, remainder = calculate_quantity_split(
            case["total_paise"],
            case["participants"],
            [QuantityAllocation(**allocation) for allocation in case["allocations"]],
        )
        return {
            "owner_share_paise": owner,
            "shares_paise": shares,
            "remainder_paise": remainder,
        }
    raise AssertionError(f"Unknown golden kind: {case['kind']}")


@pytest.mark.parametrize("case", GOLDENS, ids=lambda case: case["name"])
def test_agent_regression_golden(case: dict[str, Any]) -> None:
    if "expected_error" in case:
        with pytest.raises(ValueError, match=case["expected_error"]):
            _evaluate(case)
        return
    actual = _evaluate(case)
    test_case = LLMTestCase(
        input=case["name"],
        actual_output=json.dumps(actual, sort_keys=True),
        expected_output=json.dumps(case["expected"], sort_keys=True),
        name=case["name"],
    )
    assert_test(test_case=test_case, metrics=[ExactJsonMetric()], run_async=False)


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_DEEPEVAL_LIVE") != "1", reason="Requires an explicitly enabled Azure model run")
async def test_live_salary_chat_records_one_verified_transaction(client: AsyncClient, app: FastAPI) -> None:
    """Optional model eval; wallet writes remain inside the per-test SQLite database."""
    settings = get_settings()
    if not (settings.azure_openai_endpoint and settings.azure_openai_api_key and
            (settings.azure_openai_extraction_deployment or settings.azure_openai_deployment)):
        pytest.fail("RUN_DEEPEVAL_LIVE=1 requires Azure OpenAI endpoint, key, and deployment")

    token = await register_and_get_token(client, "deepeval-live-salary@example.com")
    headers = auth_headers(token)
    account = await client.post(
        "/api/v1/accounts",
        json={"name": "Axis", "type": "bank", "balance_paise": 0, "currency": "INR"},
        headers=headers,
    )
    assert account.status_code == 201, account.text

    response = await client.post(
        "/api/v1/chat",
        json={"message": "Record my ₹60,000 salary in the Axis account"},
        headers=headers,
    )
    transactions = await client.get("/api/v1/transactions", headers=headers)
    matching = [
        item for item in transactions.json()
        if item["type"] == "income" and item["amount_paise"] == 6_000_000
    ] if transactions.status_code == 200 else []
    passed = (
        response.status_code == 200
        and response.json().get("tasks_completed") is True
        and len(matching) == 1
        and response.json().get("created_transaction_id") == matching[0]["id"]
    )
    case = LLMTestCase(
        input="Record my ₹60,000 salary in the Axis account",
        actual_output=json.dumps(passed),
        expected_output="true",
        name="live_salary_creates_one_verified_transaction",
    )
    assert_test(test_case=case, metrics=[ExactJsonMetric()], run_async=False)
