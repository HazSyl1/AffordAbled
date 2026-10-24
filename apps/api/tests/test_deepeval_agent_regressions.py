"""Stable DeepEval cases for LangGraph handoffs and financial invariants.

These cases run without an LLM or a database. They check the trusted boundaries
that must hold even when a model supplies misleading prose or tool arguments.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from deepeval import assert_test
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase
from fastapi import FastAPI
from httpx import AsyncClient

from app.application.services.image_service import ImageService
from app.application.services.itemized_split import ItemAllocation, calculate_itemized_split
from app.application.services.memory_service import candidates_for_event
from app.application.services.quantity_split import QuantityAllocation, calculate_quantity_split
from app.application.services.settlement_split import (
    SettlementDebt,
    SplitContribution,
    calculate_settlement_split,
)
from app.core.config import get_settings
from app.infrastructure.ai.agents.contracts import HandoffContext, TaskContract
from app.infrastructure.ai.agents.runtime import merge_verified_transaction_references
from app.infrastructure.ai.agents.split import SplitToolset
from app.infrastructure.ai.agents.supervisor_graph import _verify_task_contract
from app.infrastructure.ai.tools.transaction_query_tools import TransactionQueryTools
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


class BooleanCriteriaMetric(BaseMetric):
    """Score named workflow invariants and report the exact failed criteria."""

    def __init__(self) -> None:
        self.threshold = 1.0
        self.score = 0.0
        self.reason = ""

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        try:
            criteria = json.loads(test_case.actual_output)
        except (TypeError, json.JSONDecodeError) as error:
            self.score = 0.0
            self.reason = f"criteria output is not valid JSON: {error}"
            self.success = False
            return self.score

        failed = [
            f"{name} (expected={details.get('expected')!r}, observed={details.get('observed')!r})"
            for name, details in criteria.items()
            if not details.get("passed")
        ]
        self.score = (len(criteria) - len(failed)) / len(criteria) if criteria else 0.0
        self.reason = "all workflow criteria passed" if not failed else "failed: " + "; ".join(failed)
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case, *args, **kwargs)

    @property
    def __name__(self) -> str:
        return "BooleanCriteriaMetric"


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
    if case["kind"] == "settlement_split":
        calculation = calculate_settlement_split(
            case["total_paise"],
            case["participants"],
            [QuantityAllocation(**item) for item in case["allocations"]],
            [SplitContribution(**item) for item in case.get("contributions", [])],
            [SettlementDebt(**item) for item in case.get("debts", [])],
        )
        return {
            "owner_share_paise": calculation.owner_share_paise,
            "participant_shares": calculation.participant_shares,
            "priced_items_paise": calculation.priced_items_paise,
            "remainder_paise": calculation.remainder_paise,
            "transfers": [
                {"debtor": item.debtor, "creditor": item.creditor, "amount_paise": item.amount_paise}
                for item in calculation.transfers
            ],
        }
    if case["kind"] == "itemized_split":
        calculation = calculate_itemized_split(
            case["total_paise"], case["participants"],
            [ItemAllocation(**item) for item in case["items"]],
        )
        return {
            "owner_share_paise": calculation.owner_share_paise,
            "participant_shares": calculation.participant_shares,
        }
    if case["kind"] == "memory_candidate":
        return [
            {"scope": item.scope, "subject_key": item.subject_key,
             "memory_type": item.memory_type, "value_json": item.value_json}
            for item in candidates_for_event(
                action=case["action"], before=case["before"], after=case["after"],
            )
        ]
    if case["kind"] == "date_window":
        start, end = TransactionQueryTools.resolve_date_window(
            case["message"], now_utc=datetime.fromisoformat(case["now_utc"]),
            timezone_name=case.get("timezone", "UTC"),
            date_period=case.get("date_period"),
        )
        return {"start": start.isoformat(), "end": end.isoformat()}
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


def _require_live_model() -> None:
    settings = get_settings()
    if not (settings.azure_openai_endpoint and settings.azure_openai_api_key and
            (settings.azure_openai_extraction_deployment or settings.azure_openai_deployment)):
        pytest.fail("RUN_DEEPEVAL_LIVE=1 requires Azure OpenAI endpoint, key, and deployment")


async def _live_wallet(client: AsyncClient, email: str) -> tuple[dict[str, str], str]:
    _require_live_model()
    token = await register_and_get_token(client, email)
    headers = auth_headers(token)
    account = await client.post(
        "/api/v1/accounts",
        json={"name": "Axis", "type": "bank", "balance_paise": 10_000_000, "currency": "INR"},
        headers=headers,
    )
    assert account.status_code == 201, account.text
    return headers, account.json()["id"]


def _assert_live_result(name: str, actual: dict[str, Any], expected: dict[str, Any]) -> None:
    if actual != expected:
        artifact = _write_live_failure_artifact(name, {
            "metric": "ExactJsonMetric",
            "expected": expected,
            "observed": actual,
        })
        print(f"DEEPEVAL FAILURE ARTIFACT: {artifact}")
    assert_test(
        test_case=LLMTestCase(
            input=name, actual_output=json.dumps(actual, sort_keys=True),
            expected_output=json.dumps(expected, sort_keys=True), name=name,
        ),
        metrics=[ExactJsonMetric()], run_async=False,
    )


def _assert_live_criteria(
    name: str,
    criteria: dict[str, tuple[bool, Any, Any]],
    *,
    debug_context: dict[str, Any] | None = None,
) -> None:
    """Evaluate several named invariants while retaining expected and observed values."""
    output = {
        criterion: {"passed": passed, "expected": expected, "observed": observed}
        for criterion, (passed, expected, observed) in criteria.items()
    }
    failed = {criterion: details for criterion, details in output.items() if not details["passed"]}
    if failed:
        artifact = _write_live_failure_artifact(name, {
            "metric": "BooleanCriteriaMetric",
            "failed_criteria": failed,
            "all_criteria": output,
            "debug_context": debug_context or {},
        })
        print(f"DEEPEVAL FAILURE ARTIFACT: {artifact}")
    assert_test(
        test_case=LLMTestCase(
            input=name,
            actual_output=json.dumps(output, sort_keys=True, default=str),
            expected_output="Every named workflow criterion must pass.",
            name=name,
        ),
        metrics=[BooleanCriteriaMetric()],
        run_async=False,
    )


def _write_live_failure_artifact(name: str, payload: dict[str, Any]) -> Path:
    configured_directory = os.getenv("DEEPEVAL_ARTIFACT_DIR")
    artifact_directory = (
        Path(configured_directory)
        if configured_directory
        else Path(__file__).resolve().parents[1] / ".deepeval-results" / "direct-pytest"
    )
    artifact_directory.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name).strip("-") or "live-evaluation"
    artifact_path = artifact_directory / f"{safe_name}.json"
    artifact_path.write_text(
        json.dumps({
            "test": name,
            "recorded_at": datetime.now(UTC).isoformat(),
            **payload,
        }, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return artifact_path


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_DEEPEVAL_LIVE") != "1", reason="Requires an explicitly enabled Azure model run")
async def test_live_one_turn_expense_and_split_are_saved_once_and_reported_coherently(
    client: AsyncClient,
) -> None:
    headers, _account_id = await _live_wallet(client, "deepeval-live-one-turn-split@example.com")
    prompt = (
        "Record an expense of 1608 rupees for dinner at Masato from Axis and split it equally "
        "between me, Rujul, Sudhansu, and Sujal."
    )
    response = await client.post("/api/v1/chat", json={"message": prompt}, headers=headers)
    payload = response.json() if response.status_code == 200 else {}
    transactions_response = await client.get("/api/v1/transactions", headers=headers)
    splits_response = await client.get("/api/v1/splits", headers=headers)
    transactions = transactions_response.json() if transactions_response.status_code == 200 else []
    splits = splits_response.json() if splits_response.status_code == 200 else []
    expenses = [item for item in transactions if item["type"] == "expense"]
    linked_splits = [
        item for item in splits
        if expenses and str(item.get("transaction_id")) == expenses[0]["id"]
    ]
    split = linked_splits[0] if linked_splits else {}
    participant_shares = {
        item["name"].casefold(): item["share_paise"] for item in split.get("participants", [])
    }
    final_message = str(payload.get("message") or "")

    _assert_live_criteria("live_one_turn_expense_and_split", {
        "chat endpoint succeeds": (response.status_code == 200, 200, response.status_code),
        "graph completes every planned task": (
            payload.get("tasks_completed") is True, True, payload.get("tasks_completed"),
        ),
        "completion popup is enabled": (
            payload.get("show_completion_popup") is True, True, payload.get("show_completion_popup"),
        ),
        "exactly one expense is written": (len(expenses) == 1, 1, len(expenses)),
        "expense amount is exact in paise": (
            len(expenses) == 1 and expenses[0]["amount_paise"] == 160_800,
            160_800,
            expenses[0]["amount_paise"] if expenses else None,
        ),
        "response references the persisted transaction": (
            len(expenses) == 1 and payload.get("created_transaction_id") == expenses[0]["id"],
            expenses[0]["id"] if expenses else None,
            payload.get("created_transaction_id"),
        ),
        "exactly one split is linked to that expense": (len(linked_splits) == 1, 1, len(linked_splits)),
        "owner share is exact": (split.get("owner_share_paise") == 40_200, 40_200,
                                  split.get("owner_share_paise")),
        "participant shares are exact": (
            participant_shares == {"rujul": 40_200, "sudhansu": 40_200, "sujal": 40_200},
            {"rujul": 40_200, "sudhansu": 40_200, "sujal": 40_200},
            participant_shares,
        ),
        "all shares reconcile to the expense": (
            split.get("owner_share_paise", 0) + sum(participant_shares.values()) == 160_800,
            160_800,
            split.get("owner_share_paise", 0) + sum(participant_shares.values()),
        ),
        "final response reports both operations": (
            "record" in final_message.casefold() and "split" in final_message.casefold(),
            "a coherent response mentioning the recorded expense and split",
            final_message,
        ),
        "verification fallback is absent": (
            "could not verify" not in final_message.casefold(),
            "no verification fallback",
            final_message,
        ),
    }, debug_context={
        "prompt": prompt,
        "chat": {"status_code": response.status_code, "body": payload},
        "transactions": {
            "status_code": transactions_response.status_code,
            "body": transactions,
        },
        "splits": {"status_code": splits_response.status_code, "body": splits},
    })


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_DEEPEVAL_LIVE") != "1", reason="Requires an explicitly enabled Azure model run")
async def test_live_complex_quantity_debt_and_contribution_split_reconciles_exactly(
    client: AsyncClient,
) -> None:
    headers, _account_id = await _live_wallet(client, "deepeval-live-complex-split@example.com")
    prompt = (
        "Record a 927383 rupee dinner expense from Axis and split it among A, B, C, D, E, F, G, "
        "and me. A, B, and C each had 7 vodka cranberries costing 7000 rupees each. Divide the "
        "remaining bill equally among all eight of us. A owes C 17000 rupees, B already contributed "
        "29000 rupees, and C owes B 20000 rupees. Include all of those adjustments in this split."
    )
    review = await client.post("/api/v1/chat", json={"message": prompt}, headers=headers)
    review_payload = review.json() if review.status_code == 200 else {}
    confirmation = await client.post(
        "/api/v1/chat",
        json={"thread_id": review_payload.get("thread_id"), "message": "yes"},
        headers=headers,
    ) if review_payload.get("thread_id") else None
    confirmation_payload = (
        confirmation.json() if confirmation is not None and confirmation.status_code == 200 else {}
    )
    transactions_response = await client.get("/api/v1/transactions", headers=headers)
    splits_response = await client.get("/api/v1/splits", headers=headers)
    transactions = transactions_response.json() if transactions_response.status_code == 200 else []
    splits = splits_response.json() if splits_response.status_code == 200 else []
    expenses = [item for item in transactions if item["type"] == "expense"]
    linked_splits = [
        item for item in splits
        if expenses and str(item.get("transaction_id")) == expenses[0]["id"]
    ]
    split = linked_splits[0] if linked_splits else {}
    shares = {item["name"]: item["share_paise"] for item in split.get("participants", [])}
    breakdown = split.get("settlement_breakdown") or {}
    transfers = sorted(
        (item.get("debtor"), item.get("creditor"), item.get("amount_paise"))
        for item in breakdown.get("transfers", [])
    )
    expected_transfers = sorted([
        ("A", "You", 16_354_788), ("B", "You", 9_754_788), ("C", "You", 14_954_788),
        ("D", "You", 9_754_787), ("E", "You", 9_754_787), ("F", "You", 9_754_787),
        ("G", "You", 9_754_787),
    ])
    final_message = str(confirmation_payload.get("message") or "")

    _assert_live_criteria("live_complex_quantity_debt_contribution_split", {
        "review turn asks for confirmation": (
            review.status_code == 200 and "confirm" in str(review_payload.get("message") or "").casefold(),
            "a confirmation question",
            review_payload.get("message"),
        ),
        "confirmation turn succeeds": (
            confirmation is not None and confirmation.status_code == 200,
            200,
            confirmation.status_code if confirmation is not None else None,
        ),
        "graph completes after confirmation": (
            confirmation_payload.get("tasks_completed") is True,
            True,
            confirmation_payload.get("tasks_completed"),
        ),
        "only one expense is written across both turns": (len(expenses) == 1, 1, len(expenses)),
        "expense grand total is exact": (
            len(expenses) == 1 and expenses[0]["amount_paise"] == 92_738_300,
            92_738_300,
            expenses[0]["amount_paise"] if expenses else None,
        ),
        "one split is linked to the recorded expense": (len(linked_splits) == 1, 1, len(linked_splits)),
        "priced drinks total is exact": (
            breakdown.get("priced_items_paise") == 14_700_000,
            14_700_000,
            breakdown.get("priced_items_paise"),
        ),
        "equal remainder is exact": (
            breakdown.get("remainder_paise") == 78_038_300,
            78_038_300,
            breakdown.get("remainder_paise"),
        ),
        "owner share is exact": (
            split.get("owner_share_paise") == 9_754_788,
            9_754_788,
            split.get("owner_share_paise"),
        ),
        "participant expense shares are exact": (
            shares == {
                "A": 14_654_788, "B": 14_654_788, "C": 14_654_788,
                "D": 9_754_787, "E": 9_754_787, "F": 9_754_787, "G": 9_754_787,
            },
            {
                "A": 14_654_788, "B": 14_654_788, "C": 14_654_788,
                "D": 9_754_787, "E": 9_754_787, "F": 9_754_787, "G": 9_754_787,
            },
            shares,
        ),
        "expense shares reconcile to the grand total": (
            split.get("owner_share_paise", 0) + sum(shares.values()) == 92_738_300,
            92_738_300,
            split.get("owner_share_paise", 0) + sum(shares.values()),
        ),
        "contribution is preserved": (
            breakdown.get("contributions") == [{"person": "B", "amount_paise": 2_900_000}],
            [{"person": "B", "amount_paise": 2_900_000}],
            breakdown.get("contributions"),
        ),
        "existing debts are preserved": (
            breakdown.get("debts") == [
                {"debtor": "A", "creditor": "C", "amount_paise": 1_700_000},
                {"debtor": "C", "creditor": "B", "amount_paise": 2_000_000},
            ],
            [
                {"debtor": "A", "creditor": "C", "amount_paise": 1_700_000},
                {"debtor": "C", "creditor": "B", "amount_paise": 2_000_000},
            ],
            breakdown.get("debts"),
        ),
        "net settlement transfers are exact": (transfers == expected_transfers, expected_transfers, transfers),
        "settlement transfers equal outstanding from others": (
            sum(item[2] for item in transfers) == 80_083_512,
            80_083_512,
            sum(item[2] for item in transfers),
        ),
        "final response avoids verification fallback": (
            "could not verify" not in final_message.casefold(),
            "no verification fallback",
            final_message,
        ),
    }, debug_context={
        "prompt": prompt,
        "review_chat": {"status_code": review.status_code, "body": review_payload},
        "confirmation_chat": {
            "status_code": confirmation.status_code if confirmation is not None else None,
            "body": confirmation_payload,
        },
        "transactions": {
            "status_code": transactions_response.status_code,
            "body": transactions,
        },
        "splits": {"status_code": splits_response.status_code, "body": splits},
    })


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_DEEPEVAL_LIVE") != "1", reason="Requires an explicitly enabled Azure model run")
async def test_live_followup_split_links_one_expense_without_recreating_it(client: AsyncClient) -> None:
    headers, _account_id = await _live_wallet(client, "deepeval-live-split@example.com")
    first = await client.post("/api/v1/chat", json={
        "message": "Spent 1608 rupees for dinner at Masato from Axis with Sudhansu, Sujal, and Rujul. "
                   "Record only the expense for now; do not split it yet.",
    }, headers=headers)
    assert first.status_code == 200, first.text
    before = await client.get("/api/v1/transactions", headers=headers)
    assert before.status_code == 200, before.text
    expenses = [item for item in before.json() if item["type"] == "expense"]
    if len(expenses) != 1:
        _assert_live_result("live_followup_split", {"initial_expense_count": len(expenses)},
                            {"initial_expense_count": 1})
    second = await client.post("/api/v1/chat", json={
        "thread_id": first.json()["thread_id"], "message": "Create an equal split for them, including me.",
    }, headers=headers)
    transactions = await client.get("/api/v1/transactions", headers=headers)
    splits = await client.get("/api/v1/splits", headers=headers)
    matching = [item for item in splits.json() if str(item["transaction_id"]) == expenses[0]["id"]] \
        if splits.status_code == 200 else []
    actual = {
        "second_chat_ok": second.status_code == 200,
        "expense_count": len([item for item in transactions.json() if item["type"] == "expense"])
        if transactions.status_code == 200 else -1,
        "matching_split_count": len(matching),
        "owner_share_paise": matching[0]["owner_share_paise"] if matching else None,
        "participant_shares": {item["name"].casefold(): item["share_paise"] for item in matching[0]["participants"]}
        if matching else {},
    }
    _assert_live_result("live_followup_split", actual, {
        "second_chat_ok": True, "expense_count": 1, "matching_split_count": 1,
        "owner_share_paise": 40200,
        "participant_shares": {"sudhansu": 40200, "sujal": 40200, "rujul": 40200},
    })


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_DEEPEVAL_LIVE") != "1", reason="Requires an explicitly enabled Azure model run")
async def test_live_receipt_records_one_grand_total_and_no_split(client: AsyncClient) -> None:
    headers, _account_id = await _live_wallet(client, "deepeval-live-receipt@example.com")

    class ReceiptOcr:
        async def analyze(self, _image: bytes, *, content_type: str) -> str:
            assert content_type == "image/png"
            return (
                "Brickhaus Tansabrews\nClassic Mac N Cheese 399.00\nSpaghetti Bolognese 489.00\n"
                "Very Berry 1249.00\nHefeweizen 1249.00\nPeri Peri Fries 349.00\n"
                "Subtotal 3735.00\nTaxes and round-off 312.00\nGrand Total INR 4047.00"
            )

    analysis = await ImageService(ReceiptOcr()).analyze_image(
        b"image", content_type="image/png", filename="bill.png",
    )
    response = await client.post("/api/v1/chat", json={"message": analysis.prompt}, headers=headers)
    transactions = await client.get("/api/v1/transactions", headers=headers)
    splits = await client.get("/api/v1/splits", headers=headers)
    expenses = [item for item in transactions.json() if item["type"] == "expense"] \
        if transactions.status_code == 200 else []
    _assert_live_result("live_receipt_one_grand_total", {
        "chat_ok": response.status_code == 200,
        "expense_amounts_paise": sorted(item["amount_paise"] for item in expenses),
        "split_count": len(splits.json()) if splits.status_code == 200 else -1,
    }, {"chat_ok": True, "expense_amounts_paise": [404700], "split_count": 0})


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_DEEPEVAL_LIVE") != "1", reason="Requires an explicitly enabled Azure model run")
async def test_live_largest_transaction_query_reads_data_without_writing(client: AsyncClient) -> None:
    headers, account_id = await _live_wallet(client, "deepeval-live-query@example.com")
    categories = await client.get("/api/v1/categories", headers=headers)
    assert categories.status_code == 200, categories.text
    food_id = next(item["id"] for item in categories.json() if item["name"] == "Food")
    for merchant, amount in (("Cafe", 50_000), ("Masato", 90_000)):
        created = await client.post("/api/v1/transactions", json={
            "account_id": account_id, "type": "expense", "amount_paise": amount,
            "occurred_at": datetime.now(UTC).isoformat(), "category_id": food_id,
            "merchant": merchant,
        }, headers=headers)
        assert created.status_code == 201, created.text
    response = await client.post("/api/v1/chat", json={
        "message": "Which transaction did I spend the most on this week?",
        "timezone": "Asia/Kolkata",
    }, headers=headers)
    transactions = await client.get("/api/v1/transactions", headers=headers)
    message = response.json().get("message", "") if response.status_code == 200 else ""
    _assert_live_result("live_largest_transaction_query", {
        "chat_ok": response.status_code == 200,
        "names_masato": "masato" in message.casefold(),
        "mentions_nine_hundred": "900" in message.replace(",", ""),
        "transaction_count": len(transactions.json()) if transactions.status_code == 200 else -1,
    }, {"chat_ok": True, "names_masato": True, "mentions_nine_hundred": True, "transaction_count": 2})
