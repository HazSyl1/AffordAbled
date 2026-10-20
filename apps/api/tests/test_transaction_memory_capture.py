from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto import CreateTransactionInput
from app.application.services.transaction_service import TransactionService
from app.domain.entities import TransactionType
from app.infrastructure.ai.agents.contracts import HandoffContext
from app.infrastructure.ai.agents.transaction import TransactionToolset
from app.infrastructure.database.models import (
    MemoryAnalysisOutboxModel,
    MemoryModel,
    MemoryOutboxModel,
    MemoryReviewEventModel,
    TransactionModel,
    UserModel,
)
from app.infrastructure.database.repositories.sqlalchemy_account_repository import SqlAlchemyAccountRepository
from app.infrastructure.database.repositories.sqlalchemy_category_repository import SqlAlchemyCategoryRepository
from app.infrastructure.database.repositories.sqlalchemy_memory_repository import SqlAlchemyMemoryRepository
from app.infrastructure.database.repositories.sqlalchemy_transaction_repository import SqlAlchemyTransactionRepository
from tests.helpers import auth_headers, register_and_get_token


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
async def test_chat_analysis_job_commits_atomically_with_created_transaction(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'chat-analysis-outbox@example.com')
    user_id = await db_session.scalar(select(UserModel.id).where(UserModel.email == 'chat-analysis-outbox@example.com'))
    account = (await client.post('/api/v1/accounts', headers=auth_headers(token), json={
        'name': 'Axis', 'type': 'bank', 'balance_paise': 10_000,
    })).json()
    category = (await client.post('/api/v1/categories', headers=auth_headers(token), json={
        'name': 'Medicines', 'type': 'expense',
    })).json()
    service = TransactionService(
        transaction_repository=SqlAlchemyTransactionRepository(db_session),
        account_repository=SqlAlchemyAccountRepository(db_session),
        category_repository=SqlAlchemyCategoryRepository(db_session),
        memory_event_writer=SqlAlchemyMemoryRepository(db_session),
    )
    created = await service.create_transaction(CreateTransactionInput(
        user_id=user_id,
        account_id=uuid.UUID(account['id']),
        category_id=uuid.UUID(category['id']),
        type=TransactionType.EXPENSE,
        amount_paise=9_900,
        occurred_at=datetime.now(UTC),
        merchant='PCM',
        memory_review_context={
            'signal_type': 'category_mapping',
            'payload': {'history': [{'role': 'user', 'content': 'Medicines'}]},
        },
    ))

    stored_transaction = await db_session.get(TransactionModel, created.id)
    queued_job = await db_session.scalar(select(MemoryAnalysisOutboxModel).where(
        MemoryAnalysisOutboxModel.transaction_id == created.id,
    ))
    assert stored_transaction is not None
    assert queued_job is not None
    assert queued_job.user_id == user_id
    assert queued_job.signal_type == 'category_mapping'

    memory_repository = SqlAlchemyMemoryRepository(db_session)
    await memory_repository.complete_chat_analysis(queued_job.id, [{
        'scope': 'merchant', 'subject_key': 'pcm', 'memory_type': 'category_mapping',
        'value_json': {'category_id': category['id']},
    }])
    assert queued_job.payload_json == {}
    evidence_rows = await memory_repository.claim_batch(limit=10)
    assert len(evidence_rows) == 1
    await memory_repository.process_event(evidence_rows[0].id)
    memory = await db_session.scalar(select(MemoryModel).where(MemoryModel.user_id == user_id))
    assert memory is not None
    assert memory.memory_type == 'category_mapping'
    assert memory.evidence_count == 1
    assert memory.status == 'pending'


@pytest.mark.asyncio
@pytest.mark.parametrize('include_review_event', [True, False])
async def test_completion_popup_category_edit_creates_review_event_and_outbox(
    client: AsyncClient, db_session: AsyncSession, include_review_event: bool,
) -> None:
    email = f'completion-edit-memory-{include_review_event}@example.com'
    token = await register_and_get_token(client, email)
    headers = auth_headers(token)
    account = (await client.post('/api/v1/accounts', headers=headers, json={
        'name': 'Axis', 'type': 'bank', 'balance_paise': 100_000,
    })).json()
    food = (await client.post('/api/v1/categories', headers=headers, json={
        'name': 'Food', 'type': 'expense',
    })).json()
    medicines = (await client.post('/api/v1/categories', headers=headers, json={
        'name': 'Medicines', 'type': 'expense',
    })).json()
    created = await client.post('/api/v1/transactions', headers=headers, json={
        'account_id': account['id'], 'category_id': food['id'], 'type': 'expense',
        'amount_paise': 9900, 'occurred_at': datetime.now(UTC).isoformat(), 'merchant': 'ibu',
    })
    assert created.status_code == 201, created.text

    update_body: dict[str, Any] = {'category_id': medicines['id']}
    if include_review_event:
        update_body['review_event'] = {
            'action': 'edited', 'source': 'completion_popup_edit',
            'before': {'merchant': 'ibu', 'category_id': food['id']},
            'after': {'merchant': 'ibu', 'category_id': medicines['id']},
        }
    updated = await client.patch(f"/api/v1/transactions/{created.json()['id']}", headers=headers, json=update_body)
    assert updated.status_code == 200, updated.text

    event = await db_session.scalar(select(MemoryReviewEventModel).where(
        MemoryReviewEventModel.transaction_id == uuid.UUID(created.json()['id']),
        MemoryReviewEventModel.source == ('completion_popup_edit' if include_review_event else 'transaction_edit'),
    ))
    assert event is not None
    outbox = await db_session.scalar(select(MemoryOutboxModel).where(MemoryOutboxModel.event_id == event.id))
    assert outbox is not None


@pytest.mark.asyncio
async def test_typed_category_clarification_is_queued_with_bounded_conversation() -> None:
    service = CapturingTransactionService()
    toolset = TransactionToolset(service)  # type: ignore[arg-type]
    context = _context([{"role": "user", "content": "spent 99 on pcm"}, {"role": "user", "content": "Medicines"}])
    context.constraints.update({
        "memory_review_signal": {"signal_type": "category_mapping", "subject_hint": "pcm"},
        "available_categories": [{"id": str(uuid.uuid4()), "name": "Medicines"}],
        "available_accounts": [],
    })

    await toolset.create_transaction(context, {
        "account_id": str(uuid.uuid4()),
        "category_id": context.constraints["available_categories"][0]["id"],
        "type": "expense",
        "amount_rupees": 99,
        "merchant": "pcm",
    })

    assert service.input.review_event is None
    queued = service.input.memory_review_context
    assert queued["signal_type"] == "category_mapping"
    assert queued["payload"]["signal"]["subject_hint"] == "pcm"
    assert queued["payload"]["transaction"]["amount_paise"] == 9900
    assert queued["payload"]["history"][-1]["content"] == "Medicines"


@pytest.mark.asyncio
async def test_category_clarification_transcript_recovers_signal_when_handoff_metadata_is_missing() -> None:
    service = CapturingTransactionService()
    toolset = TransactionToolset(service)  # type: ignore[arg-type]
    context = _context([
        {"role": "user", "content": "spent 90 on ppl"},
        {"role": "assistant", "content": "Which category should be used for this expense?"},
        {"role": "user", "content": "Health"},
    ])
    category_id = str(uuid.uuid4())
    context.constraints.update({
        "available_categories": [{"id": category_id, "name": "Health"}],
        "available_accounts": [],
    })

    await toolset.create_transaction(context, {
        "account_id": str(uuid.uuid4()),
        "category_id": category_id,
        "type": "expense",
        "amount_rupees": 90,
        "merchant": "ppl",
    })

    assert service.input.memory_review_context["signal_type"] == "category_mapping"
    assert service.input.memory_review_context["payload"]["transaction"]["merchant"] == "ppl"


@pytest.mark.asyncio
async def test_unmarked_conversation_does_not_queue_memory_analysis() -> None:
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
    assert service.input.memory_review_context is None


@pytest.mark.asyncio
async def test_typed_signal_does_not_depend_on_assistant_question_wording() -> None:
    service = CapturingTransactionService()
    toolset = TransactionToolset(service)  # type: ignore[arg-type]
    context = _context([
        {"role": "user", "content": "spent 99 on pcm"},
        {"role": "assistant", "content": "For this expense, what category would you like to use?"},
        {"role": "user", "content": "Medicines"},
    ])
    context.constraints["memory_review_signal"] = {"signal_type": "category_mapping", "subject_hint": "pcm"}
    category_id = uuid.uuid4()

    await toolset.create_transaction(context, {
        "account_id": str(uuid.uuid4()),
        "category_id": str(category_id),
        "type": "expense",
        "amount_rupees": 99,
        "merchant": "pcm",
    })

    assert service.input.memory_review_context["signal_type"] == "category_mapping"
