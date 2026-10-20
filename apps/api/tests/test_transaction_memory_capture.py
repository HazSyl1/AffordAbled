from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.infrastructure.ai.agents.contracts import HandoffContext
from app.infrastructure.ai.agents.transaction import TransactionToolset


class CapturingTransactionService:
    def __init__(self) -> None:
        self.input: Any = None

    async def create_transaction(self, data: Any) -> SimpleNamespace:
        self.input = data
        return SimpleNamespace(
            id=uuid.uuid4(),
            type=data.type,
            amount_paise=data.amount_paise,
            account_id=data.account_id,
            category_id=data.category_id,
            to_account_id=data.to_account_id,
            occurred_at=data.occurred_at,
            merchant=data.merchant,
            note=data.note,
        )


def _context(history: list[dict[str, str]]) -> HandoffContext:
    return HandoffContext(user_id=uuid.uuid4(), request="spent 99 on pcm", history=history)


@pytest.mark.asyncio
async def test_chat_category_answer_records_memory_evidence() -> None:
    service = CapturingTransactionService()
    toolset = TransactionToolset(service)  # type: ignore[arg-type]
    context = _context([
        {"role": "user", "content": "spent 99 on pcm"},
        {"role": "assistant", "content": "Which category should be used? Available categories are Food and Medicines."},
        {"role": "user", "content": "Medicines"},
    ])
    category_id = uuid.uuid4()

    await toolset.create_transaction(context, {
        "account_id": str(uuid.uuid4()),
        "category_id": str(category_id),
        "type": "expense",
        "amount_rupees": 99,
        "merchant": "pcm",
    })

    assert service.input.review_event == {
        "action": "accepted",
        "source": "chat_category_clarification",
        "before": {},
        "after": {"merchant": "pcm", "category_id": str(category_id)},
    }


@pytest.mark.asyncio
async def test_category_mapping_is_not_learned_from_unasked_ai_choice() -> None:
    service = CapturingTransactionService()
    toolset = TransactionToolset(service)  # type: ignore[arg-type]
    context = _context([
        {"role": "user", "content": "spent 99 on pcm"},
        {"role": "user", "content": "Medicines"},
    ])

    await toolset.create_transaction(context, {
        "account_id": str(uuid.uuid4()),
        "category_id": str(uuid.uuid4()),
        "type": "expense",
        "amount_rupees": 99,
        "merchant": "pcm",
    })

    assert service.input.review_event is None
