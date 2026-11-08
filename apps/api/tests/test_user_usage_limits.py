from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto import CreateTransactionInput
from app.application.services.chat_service import ChatResponseOutput
from app.application.services.transaction_service import TransactionService
from app.application.services.user_usage_service import UserUsageService
from app.core.dependencies import get_chat_service, get_user_usage_service
from app.domain.entities import TransactionType
from app.infrastructure.database.models import UserModel
from app.infrastructure.database.repositories.sqlalchemy_account_repository import SqlAlchemyAccountRepository
from app.infrastructure.database.repositories.sqlalchemy_category_repository import SqlAlchemyCategoryRepository
from app.infrastructure.database.repositories.sqlalchemy_transaction_repository import SqlAlchemyTransactionRepository
from app.infrastructure.database.repositories.sqlalchemy_user_usage_repository import SqlAlchemyUserUsageRepository
from tests.helpers import auth_headers, register_and_get_token


def _usage_service(
    db_session: AsyncSession, *, free_chat: int = 2, free_ai: int = 1,
) -> UserUsageService:
    return UserUsageService(
        SqlAlchemyUserUsageRepository(db_session),
        free_chat_turns=free_chat,
        free_ai_transactions=free_ai,
        subscribed_chat_turns=5,
        subscribed_ai_transactions=4,
    )


class _FakeChatService:
    async def send_message(self, **values) -> ChatResponseOutput:
        return ChatResponseOutput(thread_id=values.get('thread_id') or str(uuid.uuid4()), message='Done')


async def test_profile_exposes_free_tier_and_usage(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'usage-profile@example.com')
    headers = auth_headers(token)
    profile = await client.get('/api/v1/auth/me', headers=headers)
    usage = await client.get('/api/v1/auth/me/usage', headers=headers)

    assert profile.status_code == 200
    assert profile.json()['account_tier'] == 'free'
    assert usage.status_code == 200
    assert usage.json()['chat_turns'] == {
        'used': 0, 'limit': 50, 'remaining': 50, 'unlimited': False,
    }
    assert usage.json()['ai_transactions'] == {
        'used': 0, 'limit': 20, 'remaining': 20, 'unlimited': False,
    }


async def test_durable_chat_limit_is_idempotent_and_returns_retry_metadata(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'usage-chat@example.com')
    headers = auth_headers(token)
    app.dependency_overrides[get_user_usage_service] = lambda: _usage_service(db_session)
    try:
        first_id = str(uuid.uuid4())
        first_payload = {'turn_id': first_id, 'thread_id': 'thread-1', 'message': 'Hello', 'timezone': 'UTC'}
        first = await client.post('/api/v1/chat/turns', json=first_payload, headers=headers)
        repeated = await client.post('/api/v1/chat/turns', json=first_payload, headers=headers)
        second = await client.post('/api/v1/chat/turns', json={
            'turn_id': str(uuid.uuid4()), 'thread_id': 'thread-2', 'message': 'Second', 'timezone': 'UTC',
        }, headers=headers)
        blocked = await client.post('/api/v1/chat/turns', json={
            'turn_id': str(uuid.uuid4()), 'thread_id': 'thread-3', 'message': 'Third', 'timezone': 'UTC',
        }, headers=headers)

        assert first.status_code == repeated.status_code == second.status_code == 202
        assert blocked.status_code == 429
        assert blocked.json()['detail']['code'] == 'chat_turn_daily_limit_reached'
        assert blocked.json()['detail']['used'] == 2
        assert int(blocked.headers['Retry-After']) >= 0
    finally:
        app.dependency_overrides.pop(get_user_usage_service, None)


async def test_legacy_chat_endpoint_uses_the_same_daily_limit(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'usage-legacy-chat@example.com')
    headers = auth_headers(token)
    app.dependency_overrides[get_user_usage_service] = lambda: _usage_service(db_session, free_chat=1)
    app.dependency_overrides[get_chat_service] = lambda: _FakeChatService()
    try:
        first = await client.post('/api/v1/chat', json={'message': 'First'}, headers=headers)
        blocked = await client.post('/api/v1/chat', json={'message': 'Second'}, headers=headers)
        assert first.status_code == 200
        assert blocked.status_code == 429
        assert blocked.json()['detail']['code'] == 'chat_turn_daily_limit_reached'
    finally:
        app.dependency_overrides.pop(get_user_usage_service, None)
        app.dependency_overrides.pop(get_chat_service, None)


async def test_test_tier_records_usage_without_enforcing_limits(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'usage-test-tier@example.com')
    headers = auth_headers(token)
    profile = await client.get('/api/v1/auth/me', headers=headers)
    user = await db_session.get(UserModel, uuid.UUID(profile.json()['id']))
    assert user is not None
    user.account_tier = 'test'
    await db_session.commit()
    app.dependency_overrides[get_user_usage_service] = lambda: _usage_service(db_session, free_chat=1)
    try:
        for index in range(3):
            response = await client.post('/api/v1/chat/turns', json={
                'turn_id': str(uuid.uuid4()), 'thread_id': f'thread-{index}',
                'message': f'Message {index}', 'timezone': 'UTC',
            }, headers=headers)
            assert response.status_code == 202, response.text
        usage = await client.get('/api/v1/auth/me/usage', headers=headers)
        assert usage.json()['account_tier'] == 'test'
        assert usage.json()['chat_turns']['used'] == 3
        assert usage.json()['chat_turns']['limit'] is None
        assert usage.json()['notification_limits_bypassed'] is True
    finally:
        app.dependency_overrides.pop(get_user_usage_service, None)


async def test_subscribed_limits_and_utc_daily_reset(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'usage-subscribed@example.com')
    profile = await client.get('/api/v1/auth/me', headers=auth_headers(token))
    user_id = uuid.UUID(profile.json()['id'])
    user = await db_session.get(UserModel, user_id)
    assert user is not None
    user.account_tier = 'subscribed'
    await db_session.commit()
    service = _usage_service(db_session)
    first_day = datetime(2026, 11, 8, 23, 59, tzinfo=UTC)
    for index in range(5):
        await service.consume(user_id, 'chat_turn', f'day-one-{index}', now=first_day)
    try:
        await service.consume(user_id, 'chat_turn', 'day-one-blocked', now=first_day)
    except ValueError as error:
        assert 'limit of 5 chat messages' in str(error)
    else:
        raise AssertionError('Expected the subscribed chat limit to be enforced.')

    next_day = first_day + timedelta(minutes=2)
    snapshot = await service.summary(user_id, now=next_day)
    assert snapshot['chat_turns']['used'] == 0
    assert snapshot['chat_turns']['limit'] == 5


async def test_ai_transaction_limit_counts_only_chat_attributed_records(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'usage-ai-transactions@example.com')
    headers = auth_headers(token)
    profile = await client.get('/api/v1/auth/me', headers=headers)
    user_id = uuid.UUID(profile.json()['id'])
    account = await client.post('/api/v1/accounts', json={
        'name': 'Quota wallet', 'type': 'wallet', 'balance_paise': 100000, 'currency': 'INR',
    }, headers=headers)
    category = await client.post('/api/v1/categories', json={
        'name': 'Quota expense', 'type': 'expense',
    }, headers=headers)
    service = TransactionService(
        SqlAlchemyTransactionRepository(db_session),
        SqlAlchemyAccountRepository(db_session),
        SqlAlchemyCategoryRepository(db_session),
        usage_service=_usage_service(db_session, free_ai=1),
    )

    base = dict(
        user_id=user_id, account_id=uuid.UUID(account.json()['id']),
        category_id=uuid.UUID(category.json()['id']), type=TransactionType.EXPENSE,
        amount_paise=100, occurred_at=datetime.now(UTC),
    )
    await service.create_transaction(CreateTransactionInput(**base, merchant='Manual'))
    turn_id = uuid.uuid4()
    await service.create_transaction(CreateTransactionInput(
        **base, merchant='Chat one', source_turn_id=turn_id,
        source_task_id='task-1', source_item_index=0,
    ))

    try:
        await service.create_transaction(CreateTransactionInput(
            **base, merchant='Chat two', source_turn_id=uuid.uuid4(),
            source_task_id='task-2', source_item_index=0,
        ))
    except ValueError as error:
        assert 'limit of 1 AI-created transactions' in str(error)
    else:
        raise AssertionError('Expected the second AI-created transaction to be blocked.')

    transactions = await SqlAlchemyTransactionRepository(db_session).list_for_user(user_id)
    assert {item.merchant for item in transactions} == {'Chat one', 'Manual'}


async def test_retried_batch_does_not_need_capacity_for_rows_already_counted(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'usage-batch-retry@example.com')
    profile = await client.get('/api/v1/auth/me', headers=auth_headers(token))
    user_id = uuid.UUID(profile.json()['id'])
    service = _usage_service(db_session, free_ai=3)
    keys = ['turn:task:0', 'turn:task:1', 'turn:task:2']
    for key in keys:
        await service.consume(user_id, 'ai_transaction', key)

    await service.ensure_capacity(user_id, 'ai_transaction', 3, keys=keys)
    try:
        await service.ensure_capacity(user_id, 'ai_transaction', 1, keys=['turn:task:3'])
    except ValueError as error:
        assert 'limit of 3 AI-created transactions' in str(error)
    else:
        raise AssertionError('A new row beyond the cap must be rejected.')


async def test_failed_chat_turn_is_refunded_and_media_requests_are_capped(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'usage-media@example.com')
    headers = auth_headers(token)
    profile = await client.get('/api/v1/auth/me', headers=headers)
    user_id = uuid.UUID(profile.json()['id'])
    service = _usage_service(db_session, free_chat=1)
    await service.consume(user_id, 'chat_turn', 'turn:abc')
    await service.refund(user_id, 'chat_turn', 'turn:abc')
    assert (await service.summary(user_id))['chat_turns']['used'] == 0

    limited = _usage_service(db_session)
    limited.free_media_requests = 1
    app.dependency_overrides[get_user_usage_service] = lambda: limited
    try:
        files = {'image': ('x.png', b'not-an-image', 'image/png')}
        first = await client.post('/api/v1/chat/image', files=files, headers=headers)
        blocked = await client.post('/api/v1/chat/image', files=files, headers=headers)
        assert first.status_code != 429
        assert blocked.status_code == 429
        assert blocked.json()['detail']['code'] == 'media_request_daily_limit_reached'
    finally:
        app.dependency_overrides.pop(get_user_usage_service, None)


async def test_worker_refunds_only_permanently_failed_turns(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.infrastructure.jobs.chat_turn_jobs import run_chat_turn_once

    token = await register_and_get_token(client, 'usage-refund@example.com')
    headers = auth_headers(token)
    submitted = await client.post('/api/v1/chat/turns', json={
        'turn_id': str(uuid.uuid4()), 'thread_id': 'refund-thread', 'message': 'Hello', 'timezone': 'UTC',
    }, headers=headers)
    assert submitted.status_code == 202

    async def failing(_job):
        raise RuntimeError('model unavailable')

    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    # First of two attempts: the turn is retried, so the allowance stays reserved.
    await run_chat_turn_once(failing, max_attempts=2, session_factory=factory)
    mid = await client.get('/api/v1/auth/me/usage', headers=headers)
    assert mid.json()['chat_turns']['used'] == 1
    # Second attempt exhausts retries: the turn fails for good and the allowance is released.
    await run_chat_turn_once(failing, max_attempts=2, session_factory=factory)
    final = await client.get('/api/v1/auth/me/usage', headers=headers)
    assert final.json()['chat_turns']['used'] == 0


async def test_batch_tool_is_all_or_nothing_and_safe_to_retry(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    from app.infrastructure.ai.agents.contracts import HandoffContext
    from app.infrastructure.ai.agents.transaction import TransactionToolset

    token = await register_and_get_token(client, 'usage-batch-tool@example.com')
    headers = auth_headers(token)
    user_id = uuid.UUID((await client.get('/api/v1/auth/me', headers=headers)).json()['id'])
    account = await client.post('/api/v1/accounts', json={
        'name': 'Batch wallet', 'type': 'wallet', 'balance_paise': 100000, 'currency': 'INR',
    }, headers=headers)
    category = await client.post('/api/v1/categories', json={'name': 'Batch expense', 'type': 'expense'},
                                 headers=headers)
    service = TransactionService(
        SqlAlchemyTransactionRepository(db_session),
        SqlAlchemyAccountRepository(db_session),
        SqlAlchemyCategoryRepository(db_session),
        usage_service=_usage_service(db_session, free_ai=2),
    )
    tools = TransactionToolset(service)
    context = HandoffContext(
        user_id=user_id, request='batch', constraints={'turn_id': str(uuid.uuid4()), 'task_id': 'task-1'},
    )
    row = {
        'type': 'expense', 'amount_rupees': 10, 'account_id': account.json()['id'],
        'category_id': category.json()['id'],
    }

    try:
        await tools.create_transaction_batch(context, {'transactions': [row, row, row]})
    except ValueError as error:
        assert 'limit of 2 AI-created transactions' in str(error)
    else:
        raise AssertionError('A batch larger than the remaining allowance must be rejected up front.')
    assert await SqlAlchemyTransactionRepository(db_session).list_for_user(user_id) == []

    first = await tools.create_transaction_batch(context, {'transactions': [row, row]})
    retried = await tools.create_transaction_batch(context, {'transactions': [row, row]})
    assert [item['id'] for item in first['transactions']] == [item['id'] for item in retried['transactions']]
    assert len(await SqlAlchemyTransactionRepository(db_session).list_for_user(user_id)) == 2


async def test_operator_cli_changes_tier_and_rejects_unknown_users(
    client: AsyncClient, db_session: AsyncSession, monkeypatch,
) -> None:
    import importlib.util
    from pathlib import Path

    from sqlalchemy.ext.asyncio import async_sessionmaker

    path = Path(__file__).resolve().parents[1] / 'scripts' / 'set_user_tier.py'
    spec = importlib.util.spec_from_file_location('set_user_tier_script', path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, 'SessionLocal', async_sessionmaker(bind=db_session.bind, expire_on_commit=False))

    token = await register_and_get_token(client, 'usage-cli@example.com')
    headers = auth_headers(token)
    user_id = uuid.UUID((await client.get('/api/v1/auth/me', headers=headers)).json()['id'])

    from app.domain.entities import UserTier

    assert await script.set_user_tier(user_id, UserTier.SUBSCRIBED) == 0
    assert (await client.get('/api/v1/auth/me', headers=headers)).json()['account_tier'] == 'subscribed'
    assert await script.set_user_tier(uuid.uuid4(), UserTier.TEST) == 1
    # The public profile endpoint must never accept a tier.
    patched = await client.patch('/api/v1/auth/me', json={
        'name': 'Usage Cli', 'date_of_birth': None, 'upi_id': None, 'account_tier': 'test',
    }, headers=headers)
    assert patched.json()['account_tier'] == 'subscribed'
