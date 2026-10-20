from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.application.services.memory_service import candidates_for_event, fingerprint
from app.infrastructure.database.models import MemoryModel, MemoryReviewEventModel, UserModel
from app.infrastructure.database.repositories.sqlalchemy_memory_repository import SqlAlchemyMemoryRepository
from tests.helpers import auth_headers, register_and_get_token


def test_memory_fingerprint_is_stable_and_candidate_is_structured() -> None:
    assert fingerprint({'b': 2, 'a': 1}) == fingerprint({'a': 1, 'b': 2})
    candidates = candidates_for_event(
        action='edited',
        before={'merchant': 'Apollo Pharmacy', 'category_id': 'misc'},
        after={'merchant': 'Apollo Pharmacy', 'category_id': 'medicine'},
    )
    assert candidates[0].scope == 'merchant'
    assert candidates[0].subject_key == 'apollo pharmacy'
    assert candidates[0].memory_type == 'category_mapping'


def test_split_memory_candidates_never_treat_the_owner_as_a_contact() -> None:
    candidates = candidates_for_event(
        action='accepted', before={}, after={
            'mode': 'equal',
            'participants': [
                {'name': 'Me', 'share_ratio': 0.25},
                {'name': 'Piyush', 'share_ratio': 0.25},
            ],
        },
    )

    assert [(candidate.subject_key, candidate.value_json['share_ratio']) for candidate in candidates] == [
        ('piyush', 0.25),
    ]


@pytest.mark.asyncio
async def test_legacy_self_split_memory_is_hidden_from_memory_lists(client: AsyncClient, db_session) -> None:
    token = await register_and_get_token(client, 'memory-self@example.com')
    user_id = await db_session.scalar(select(UserModel.id).where(UserModel.email == 'memory-self@example.com'))
    assert user_id is not None
    db_session.add(MemoryModel(
        id=uuid.uuid4(), user_id=user_id, scope='person', subject_key='Me', memory_type='split_method',
        value_json={'mode': 'equal', 'share_ratio': 0.25}, fingerprint=str(uuid.uuid4()),
        status='suggested', confidence=1.0, evidence_count=3, source_event_ids=[],
    ))
    await db_session.commit()

    suggestions = await client.get('/api/v1/memories/suggestions', headers=auth_headers(token))
    all_memories = await client.get('/api/v1/memories', headers=auth_headers(token))
    assert suggestions.status_code == 200 and suggestions.json() == []
    assert all_memories.status_code == 200 and all_memories.json() == []


@pytest.mark.asyncio
async def test_review_events_promote_once_and_are_user_scoped(client: AsyncClient, db_session) -> None:
    owner = await register_and_get_token(client, 'memory-owner@example.com')
    other = await register_and_get_token(client, 'memory-other@example.com')
    headers = auth_headers(owner)

    for _ in range(3):
        response = await client.post('/api/v1/memories/review-events', headers=headers, json={
            'action': 'edited',
            'source': 'review_popup',
            'transaction_id': str(uuid.uuid4()),
            'before': {'merchant': 'Apollo Pharmacy', 'category_id': 'misc'},
            'after': {'merchant': 'Apollo Pharmacy', 'category_id': 'medicine'},
        })
        assert response.status_code == 201, response.text

    repository = SqlAlchemyMemoryRepository(db_session)
    rows = await repository.claim_batch(limit=20)
    assert len(rows) == 3
    for row in rows:
        await repository.process_event(row.id)

    suggestions = await client.get('/api/v1/memories/suggestions', headers=headers)
    assert suggestions.status_code == 200
    assert len(suggestions.json()) == 1
    suggestion = suggestions.json()[0]
    assert suggestion['evidence_count'] == 3
    assert suggestion['status'] == 'suggested'
    edited = await client.patch(
        f"/api/v1/memories/{suggestion['id']}", headers=headers,
        json={'value': {'category_id': 'corrected-category'}},
    )
    assert edited.status_code == 200
    assert edited.json()['value']['category_id'] == 'corrected-category'
    assert edited.json()['status'] == 'suggested'

    confirmed = await client.post(
        f"/api/v1/memories/{suggestion['id']}/confirm", headers=headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()['status'] == 'confirmed'
    assert (await client.get('/api/v1/memories/suggestions', headers=headers)).json() == []
    assert (await client.get('/api/v1/memories', headers=auth_headers(other))).json() == []


@pytest.mark.asyncio
async def test_chat_category_choices_create_events_and_promote_after_three_transactions(
    client: AsyncClient, db_session,
) -> None:
    token = await register_and_get_token(client, 'memory-chat-category@example.com')
    headers = auth_headers(token)
    account = await client.post(
        '/api/v1/accounts',
        headers=headers,
        json={'name': 'Main', 'type': 'bank', 'balance_paise': 100000, 'currency': 'INR'},
    )
    category = await client.post(
        '/api/v1/categories', headers=headers, json={'name': 'Medicines', 'type': 'expense'},
    )
    assert account.status_code == category.status_code == 201

    for amount_paise in (9900, 9000, 5500):
        response = await client.post('/api/v1/transactions', headers=headers, json={
            'account_id': account.json()['id'],
            'category_id': category.json()['id'],
            'type': 'expense',
            'amount_paise': amount_paise,
            'occurred_at': '2026-10-20T10:00:00+00:00',
            'merchant': 'pcm',
            'review_event': {
                'action': 'accepted',
                'source': 'chat_category_clarification',
                'before': {},
                'after': {'merchant': 'pcm', 'category_id': category.json()['id']},
            },
        })
        assert response.status_code == 201, response.text

    user_id = await db_session.scalar(select(UserModel.id).where(UserModel.email == 'memory-chat-category@example.com'))
    events = await db_session.scalars(select(MemoryReviewEventModel).where(MemoryReviewEventModel.user_id == user_id))
    assert len(events.all()) == 3

    repository = SqlAlchemyMemoryRepository(db_session)
    rows = await repository.claim_batch(limit=20)
    assert len(rows) == 3
    for row in rows:
        await repository.process_event(row.id)

    suggestions = await client.get('/api/v1/memories/suggestions', headers=headers)
    assert suggestions.status_code == 200
    assert len(suggestions.json()) == 1
    assert suggestions.json()[0]['subject_key'] == 'pcm'
    assert suggestions.json()[0]['value']['category_id'] == category.json()['id']
    assert suggestions.json()[0]['evidence_count'] == 3


@pytest.mark.asyncio
async def test_split_pattern_is_not_suggested_until_three_reviewed_examples(client: AsyncClient, db_session) -> None:
    token = await register_and_get_token(client, 'memory-split-pattern@example.com')
    user_id = await db_session.scalar(
        select(UserModel.id).where(UserModel.email == 'memory-split-pattern@example.com')
    )
    assert user_id is not None
    repository = SqlAlchemyMemoryRepository(db_session)

    for reviewed_split_count in range(1, 4):
        await repository.add_review_event(
            user_id=user_id,
            action='accepted',
            source='split_review',
            before={},
            after={
                'review_number': reviewed_split_count,
                'mode': 'equal',
                'participants': [{'name': 'Piyush', 'share_ratio': 0.25}],
            },
        )
        await db_session.commit()
        for row in await repository.claim_batch(limit=10):
            await repository.process_event(row.id)

        response = await client.get('/api/v1/memories/suggestions', headers=auth_headers(token))
        assert response.status_code == 200
        if reviewed_split_count < 3:
            assert response.json() == []
        else:
            assert len(response.json()) == 1
            assert response.json()[0]['subject_key'] == 'piyush'
            assert response.json()[0]['evidence_count'] == 3


@pytest.mark.asyncio
async def test_duplicate_review_submission_does_not_duplicate_event(client: AsyncClient, db_session) -> None:
    token = await register_and_get_token(client, 'memory-dedupe@example.com')
    transaction_id = str(uuid.uuid4())
    payload = {
        'action': 'edited', 'source': 'review_popup', 'transaction_id': transaction_id,
        'before': {'merchant': 'Cafe', 'category_id': 'misc'},
        'after': {'merchant': 'Cafe', 'category_id': 'food'},
    }
    first = await client.post('/api/v1/memories/review-events', headers=auth_headers(token), json=payload)
    second = await client.post('/api/v1/memories/review-events', headers=auth_headers(token), json=payload)
    assert first.status_code == second.status_code == 201
    repository = SqlAlchemyMemoryRepository(db_session)
    rows = await repository.claim_batch(limit=20)
    assert len(rows) == 1
