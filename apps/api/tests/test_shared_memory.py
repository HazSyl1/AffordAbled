from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.application.services.memory_service import candidates_for_event, fingerprint
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
