from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.services.split_notification_service import (
    SplitNotificationService,
    build_sms_message,
    build_upi_link,
)
from app.infrastructure.database.repositories.sqlalchemy_split_notification_repository import (
    SqlAlchemySplitNotificationRepository,
)
from app.infrastructure.jobs.split_notification_jobs import run_split_notification_batch_once
from app.infrastructure.sms.provider import SmsSendResult
from app.presentation.routers.splits_router import get_split_notification_service
from tests.helpers import auth_headers, register_and_get_token


async def _expense(client: AsyncClient, token: str) -> str:
    headers = auth_headers(token)
    account = await client.post('/api/v1/accounts', json={
        'name': 'Reminder Wallet', 'type': 'wallet', 'balance_paise': 50000, 'currency': 'INR',
    }, headers=headers)
    category = await client.post('/api/v1/categories', json={
        'name': 'Reminder Expense', 'type': 'expense',
    }, headers=headers)
    transaction = await client.post('/api/v1/transactions', json={
        'account_id': account.json()['id'], 'category_id': category.json()['id'],
        'type': 'expense', 'amount_paise': 10000, 'occurred_at': '2026-11-07T12:00:00+00:00',
    }, headers=headers)
    assert transaction.status_code == 201, transaction.text
    return transaction.json()['id']


def _service(
    db_session: AsyncSession, *, cooldown_hours: int = 6,
    max_per_participant: int = 3, max_per_user_daily: int = 10,
) -> SplitNotificationService:
    return SplitNotificationService(
        repository=SqlAlchemySplitNotificationRepository(db_session),
        enabled=True,
        provider_name='azure_acs',
        cooldown_hours=cooldown_hours,
        max_per_participant=max_per_participant,
        max_per_user_daily=max_per_user_daily,
    )


class _FakeSmsProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(self, **values) -> SmsSendResult:
        self.calls.append(values)
        return SmsSendResult(successful=True, message_id='fake-sms-1')


async def test_notification_requires_profile_and_contact_then_queues_idempotently(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'reminder-owner@example.com')
    headers = auth_headers(token)
    app.dependency_overrides[get_split_notification_service] = lambda: _service(db_session)
    try:
        profile = await client.patch('/api/v1/auth/me', json={
            'name': 'Reminder Owner', 'date_of_birth': '1998-01-01', 'upi_id': 'owner@bank',
        }, headers=headers)
        assert profile.status_code == 200, profile.text
        assert profile.json()['upi_id'] == 'owner@bank'

        contact = await client.put('/api/v1/splits/contacts/details', json={
            'name': 'Isha', 'phone_e164': '+919876543210',
        }, headers=headers)
        assert contact.status_code == 200, contact.text
        transaction_id = await _expense(client, token)
        split_response = await client.post('/api/v1/splits', json={
            'transaction_id': transaction_id, 'title': 'Dinner & movie', 'amount_paise': 10000,
            'mode': 'equal', 'participants': [{
                'name': 'Isha', 'contact_id': contact.json()['id'],
            }],
        }, headers=headers)
        assert split_response.status_code == 201, split_response.text
        split = split_response.json()
        participant = split['participants'][0]
        assert participant['contact_id'] == contact.json()['id']

        status_url = f"/api/v1/splits/{split['id']}/participants/{participant['id']}/notifications"
        before = await client.get(status_url, headers=headers)
        assert before.status_code == 200, before.text
        assert before.json()['can_notify'] is True
        assert 'owner%40bank' in before.json()['message_preview']
        assert before.json()['recipient_phone_masked'].endswith('3210')

        key = str(uuid.uuid4())
        queued = await client.post(status_url, headers={**headers, 'Idempotency-Key': key})
        assert queued.status_code == 202, queued.text
        repeated = await client.post(status_url, headers={**headers, 'Idempotency-Key': key})
        assert repeated.status_code == 202, repeated.text
        assert repeated.json()['notification_id'] == queued.json()['notification_id']

        concurrent = await client.post(status_url, headers={**headers, 'Idempotency-Key': str(uuid.uuid4())})
        assert concurrent.status_code == 409, concurrent.text
        assert concurrent.json()['detail']['code'] == 'request_in_progress'

        repository = SqlAlchemySplitNotificationRepository(db_session)
        await repository.complete(uuid.UUID(queued.json()['notification_id']), status='sent', message_id='acs-1')
        cooldown = await client.post(status_url, headers={**headers, 'Idempotency-Key': str(uuid.uuid4())})
        assert cooldown.status_code == 429, cooldown.text
        assert cooldown.json()['detail']['code'] == 'cooldown_active'

        app.dependency_overrides[get_split_notification_service] = lambda: _service(
            db_session, cooldown_hours=0, max_per_participant=1,
        )
        participant_limit = await client.post(
            status_url, headers={**headers, 'Idempotency-Key': str(uuid.uuid4())},
        )
        assert participant_limit.status_code == 429, participant_limit.text
        assert participant_limit.json()['detail']['code'] == 'participant_limit_reached'

        app.dependency_overrides[get_split_notification_service] = lambda: _service(
            db_session, cooldown_hours=0, max_per_user_daily=1,
        )
        daily_limit = await client.post(
            status_url, headers={**headers, 'Idempotency-Key': str(uuid.uuid4())},
        )
        assert daily_limit.status_code == 429, daily_limit.text
        assert daily_limit.json()['detail']['code'] == 'daily_limit_reached'
    finally:
        app.dependency_overrides.pop(get_split_notification_service, None)


async def test_notification_rejects_missing_setup_and_cross_user_access(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession,
) -> None:
    owner = await register_and_get_token(client, 'reminder-missing@example.com')
    outsider = await register_and_get_token(client, 'reminder-outsider@example.com')
    transaction_id = await _expense(client, owner)
    split_response = await client.post('/api/v1/splits', json={
        'transaction_id': transaction_id, 'title': 'Tickets', 'amount_paise': 10000,
        'mode': 'equal', 'participants': [{'name': 'Piyush'}],
    }, headers=auth_headers(owner))
    split = split_response.json()
    participant = split['participants'][0]
    url = f"/api/v1/splits/{split['id']}/participants/{participant['id']}/notifications"
    app.dependency_overrides[get_split_notification_service] = lambda: _service(db_session)
    try:
        missing_upi = await client.post(
            url, headers={**auth_headers(owner), 'Idempotency-Key': str(uuid.uuid4())},
        )
        assert missing_upi.status_code == 422
        assert missing_upi.json()['detail']['code'] == 'upi_id_required'
        hidden = await client.get(url, headers=auth_headers(outsider))
        assert hidden.status_code == 404
    finally:
        app.dependency_overrides.pop(get_split_notification_service, None)


def test_upi_link_and_message_use_exact_paise_and_encoding() -> None:
    link = build_upi_link('owner@bank', 'Sarthak R', 12345, 'Dinner & movie')
    assert 'pa=owner%40bank' in link
    assert 'pn=Sarthak+R' in link
    assert 'am=123.45' in link
    assert 'tn=Dinner+%26+movie' in link
    message = build_sms_message('Isha', 'Sarthak R', 12345, 'Dinner & movie', link)
    assert 'Rs.123.45' in message
    assert datetime.now(UTC).tzinfo is not None


async def test_worker_claims_queued_reminder_and_uses_injected_provider(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'reminder-worker@example.com')
    headers = auth_headers(token)
    app.dependency_overrides[get_split_notification_service] = lambda: _service(db_session)
    try:
        await client.patch('/api/v1/auth/me', json={
            'name': 'Worker Owner', 'date_of_birth': '1998-01-01', 'upi_id': 'worker@bank',
        }, headers=headers)
        contact = await client.put('/api/v1/splits/contacts/details', json={
            'name': 'Aarav', 'phone_e164': '+919111111111',
        }, headers=headers)
        assert contact.status_code == 200
        transaction_id = await _expense(client, token)
        split_response = await client.post('/api/v1/splits', json={
            'transaction_id': transaction_id, 'title': 'Cab', 'amount_paise': 10000,
            'mode': 'equal', 'participants': [{'name': 'Aarav'}],
        }, headers=headers)
        split = split_response.json()
        participant = split['participants'][0]
        assert participant['contact_id'] == contact.json()['id']
        url = f"/api/v1/splits/{split['id']}/participants/{participant['id']}/notifications"
        queued = await client.post(url, headers={**headers, 'Idempotency-Key': str(uuid.uuid4())})
        assert queued.status_code == 202, queued.text

        provider = _FakeSmsProvider()
        session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
        processed = await run_split_notification_batch_once(
            provider, batch_size=10, stale_after_seconds=120, session_factory=session_factory,
        )
        assert processed == 1
        assert len(provider.calls) == 1
        assert provider.calls[0]['recipient_phone'] == '+919111111111'

        status = await client.get(url, headers=headers)
        assert status.status_code == 200
        assert status.json()['history'][0]['status'] == 'sent'
    finally:
        app.dependency_overrides.pop(get_split_notification_service, None)
