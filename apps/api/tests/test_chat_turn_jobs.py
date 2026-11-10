from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.database.repositories.sqlalchemy_chat_turn_job_repository import (
    SqlAlchemyChatTurnJobRepository,
)
from app.infrastructure.jobs.chat_turn_jobs import run_chat_turn_once
from tests.helpers import auth_headers, register_and_get_token


@pytest.mark.asyncio
async def test_chat_turn_submission_is_idempotent(client: AsyncClient, app: FastAPI) -> None:
    del app
    token = await register_and_get_token(client, 'durable-chat@example.com')
    headers = auth_headers(token)
    turn_id = str(uuid.uuid4())
    payload = {
        'turn_id': turn_id,
        'thread_id': str(uuid.uuid4()),
        'message': 'Record 500 rupees spent at Reliance',
        'timezone': 'Asia/Calcutta',
    }

    created = await client.post('/api/v1/chat/turns', json=payload, headers=headers)
    repeated = await client.post('/api/v1/chat/turns', json=payload, headers=headers)
    status_response = await client.get(f'/api/v1/chat/turns/{turn_id}', headers=headers)

    assert created.status_code == 202
    assert repeated.status_code == 202
    assert created.json()['turn_id'] == turn_id
    assert repeated.json()['turn_id'] == turn_id
    assert status_response.status_code == 200
    assert status_response.json()['status'] == 'queued'


@pytest.mark.asyncio
async def test_chat_turn_rejects_conflicting_idempotency_input(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'durable-conflict@example.com')
    headers = auth_headers(token)
    turn_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())

    first = await client.post('/api/v1/chat/turns', json={
        'turn_id': turn_id,
        'thread_id': thread_id,
        'message': 'Record 500 rupees spent at Reliance',
        'timezone': 'Asia/Calcutta',
    }, headers=headers)
    conflicting = await client.post('/api/v1/chat/turns', json={
        'turn_id': turn_id,
        'thread_id': thread_id,
        'message': 'Record 900 rupees spent at Reliance',
        'timezone': 'Asia/Calcutta',
    }, headers=headers)

    assert first.status_code == 202
    assert conflicting.status_code == 409


@pytest.mark.asyncio
async def test_chat_turn_status_is_user_scoped(client: AsyncClient) -> None:
    owner_token = await register_and_get_token(client, 'durable-owner@example.com')
    other_token = await register_and_get_token(client, 'durable-other@example.com')
    turn_id = str(uuid.uuid4())

    created = await client.post('/api/v1/chat/turns', json={
        'turn_id': turn_id,
        'thread_id': str(uuid.uuid4()),
        'message': 'Record 500 rupees spent at Reliance',
        'timezone': 'Asia/Calcutta',
    }, headers=auth_headers(owner_token))
    hidden = await client.get(
        f'/api/v1/chat/turns/{turn_id}', headers=auth_headers(other_token),
    )

    assert created.status_code == 202
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_chat_turn_worker_persists_the_normal_chat_response(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'durable-worker@example.com')
    headers = auth_headers(token)
    turn_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    created = await client.post('/api/v1/chat/turns', json={
        'turn_id': turn_id,
        'thread_id': thread_id,
        'message': 'Record 500 rupees spent at Reliance',
        'timezone': 'Asia/Calcutta',
    }, headers=headers)
    assert created.status_code == 202

    async def processor(_job):
        return {
            'thread_id': thread_id,
            'message': 'Recorded ₹500 spent at Reliance.',
            'tasks_completed': True,
            'show_completion_popup': True,
            'transaction_logged': True,
            'created_transaction_id': str(uuid.uuid4()),
            'manual_transaction_input_required': False,
        }

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    processed = await run_chat_turn_once(processor, session_factory=session_factory)
    completed = await client.get(f'/api/v1/chat/turns/{turn_id}', headers=headers)

    assert processed is True
    assert completed.status_code == 200
    assert completed.json()['status'] == 'succeeded'
    assert completed.json()['result']['message'] == 'Recorded ₹500 spent at Reliance.'
    assert completed.json()['claimed_at'] is not None
    assert completed.json()['completed_at'] is not None
    stream = await client.get(f'/api/v1/chat/turns/{turn_id}/events', headers=headers)
    assert stream.status_code == 200
    assert 'event: status' in stream.text
    assert '"status":"succeeded"' in stream.text


@pytest.mark.asyncio
async def test_only_one_turn_per_thread_can_be_processing(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'durable-thread-order@example.com')
    headers = auth_headers(token)
    thread_id = str(uuid.uuid4())
    turn_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    for index, turn_id in enumerate(turn_ids):
        response = await client.post('/api/v1/chat/turns', json={
            'turn_id': turn_id,
            'thread_id': thread_id,
            'message': f'Message {index + 1}',
            'timezone': 'Asia/Calcutta',
        }, headers=headers)
        assert response.status_code == 202

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    async with session_factory() as first_session:
        first_repository = SqlAlchemyChatTurnJobRepository(first_session)
        first = await first_repository.claim_next(stale_after_seconds=120, max_attempts=3)
        assert first is not None

    async with session_factory() as blocked_session:
        blocked = await SqlAlchemyChatTurnJobRepository(blocked_session).claim_next(
            stale_after_seconds=120, max_attempts=3,
        )
        assert blocked is None

    async with session_factory() as completion_session:
        await SqlAlchemyChatTurnJobRepository(completion_session).mark_succeeded(first.id, {
            'thread_id': thread_id,
            'message': 'First complete.',
            'tasks_completed': False,
            'show_completion_popup': False,
        })
    async with session_factory() as second_session:
        second = await SqlAlchemyChatTurnJobRepository(second_session).claim_next(
            stale_after_seconds=120, max_attempts=3,
        )
        assert second is not None
        assert second.id != first.id


async def test_fresh_turn_lookup_observes_completion_from_another_session(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'durable-fresh-status@example.com')
    headers = auth_headers(token)
    user_id = uuid.UUID((await client.get('/api/v1/auth/me', headers=headers)).json()['id'])
    turn_id = uuid.uuid4()
    created = await client.post('/api/v1/chat/turns', json={
        'turn_id': str(turn_id), 'thread_id': str(uuid.uuid4()), 'message': 'Check my accounts', 'timezone': 'UTC',
    }, headers=headers)
    assert created.status_code == 202
    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    async with session_factory() as stream_session:
        stream_repository = SqlAlchemyChatTurnJobRepository(stream_session)
        initial = await stream_repository.get_for_user(user_id, turn_id)
        assert initial is not None and initial.status == 'queued'
        async with session_factory() as worker_session:
            await SqlAlchemyChatTurnJobRepository(worker_session).mark_succeeded(turn_id, {
                'thread_id': created.json()['thread_id'], 'message': 'Done.',
                'tasks_completed': False, 'show_completion_popup': False,
            })
        fresh = await stream_repository.get_for_user_fresh(user_id, turn_id)
        assert fresh is not None and fresh.status == 'succeeded'
