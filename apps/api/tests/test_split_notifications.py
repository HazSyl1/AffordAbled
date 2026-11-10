from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.services.split_notification_service import (
    SplitNotificationService,
    build_email_message,
    build_email_subject,
    build_sms_message,
    build_upi_link,
)
from app.infrastructure.database.models import UserModel
from app.infrastructure.database.repositories.sqlalchemy_split_notification_repository import (
    SqlAlchemySplitNotificationRepository,
)
from app.infrastructure.email.message import (
    LOGO_CONTENT_ID,
    render_payment_request_email,
)
from app.infrastructure.email.provider import AzureAcsEmailProvider
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
    max_per_split: int = 3, max_per_user_daily: int = 10, channel: str = 'sms',
) -> SplitNotificationService:
    return SplitNotificationService(
        repository=SqlAlchemySplitNotificationRepository(db_session),
        enabled=True,
        provider_name='azure_acs',
        cooldown_hours=cooldown_hours,
        max_per_split=max_per_split,
        max_per_user_daily=max_per_user_daily,
        channel=channel,
    )


class _FakeSmsProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(self, **values) -> SmsSendResult:
        self.calls.append(values)
        return SmsSendResult(successful=True, message_id='fake-sms-1')


class _FakeEmailPoller:
    def result(self) -> dict:
        return {'status': 'Succeeded', 'id': 'fake-email-1'}


class _FakeEmailClient:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def begin_send(self, message: dict) -> _FakeEmailPoller:
        self.messages.append(message)
        return _FakeEmailPoller()


async def test_split_contact_details_can_be_added_renamed_searched_client_side_and_removed(
    client: AsyncClient,
) -> None:
    token = await register_and_get_token(client, 'contact-manager@example.com')
    headers = auth_headers(token)
    created = await client.put('/api/v1/splits/contacts/details', json={
        'name': 'Isha', 'email': 'ISHA@example.com', 'phone_e164': '+919876543210',
    }, headers=headers)
    assert created.status_code == 200, created.text
    contact_id = created.json()['id']
    assert created.json()['email'] == 'isha@example.com'

    renamed = await client.put('/api/v1/splits/contacts/details', json={
        'contact_id': contact_id, 'name': 'Isha Sharma', 'email': 'isha.sharma@example.com',
        'phone_e164': None,
    }, headers=headers)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()['name'] == 'Isha Sharma'
    assert renamed.json()['email'] == 'isha.sharma@example.com'
    assert renamed.json()['phone_e164'] is None

    contacts = await client.get('/api/v1/splits/contacts/details', headers=headers)
    assert contacts.status_code == 200, contacts.text
    assert [(item['id'], item['name']) for item in contacts.json()] == [(contact_id, 'Isha Sharma')]

    transaction_id = await _expense(client, token)
    split = await client.post('/api/v1/splits', json={
        'transaction_id': transaction_id, 'title': 'Contact link test', 'amount_paise': 10000,
        'mode': 'equal', 'participants': [{'name': 'Isha Sharma', 'contact_id': contact_id}],
    }, headers=headers)
    assert split.status_code == 201, split.text
    blocked = await client.delete(f'/api/v1/splits/contacts/details/{contact_id}', headers=headers)
    assert blocked.status_code == 409, blocked.text
    assert 'associated with one or more splits' in blocked.json()['detail']
    deleted_split = await client.delete(f"/api/v1/splits/{split.json()['id']}", headers=headers)
    assert deleted_split.status_code == 204, deleted_split.text
    removed = await client.delete(f'/api/v1/splits/contacts/details/{contact_id}', headers=headers)
    assert removed.status_code == 204, removed.text
    contacts_after = await client.get('/api/v1/splits/contacts/details', headers=headers)
    assert contacts_after.json() == []


async def test_balance_statement_queues_only_for_saved_person_with_an_outstanding_balance(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'balance-statement@example.com')
    headers = auth_headers(token)
    app.dependency_overrides[get_split_notification_service] = lambda: _service(db_session, channel='email')
    try:
        contact = await client.put('/api/v1/splits/contacts/details', json={
            'name': 'Isha', 'email': 'isha@example.com',
        }, headers=headers)
        assert contact.status_code == 200
        transaction_id = await _expense(client, token)
        split = await client.post('/api/v1/splits', json={
            'transaction_id': transaction_id, 'title': 'Dinner', 'amount_paise': 10000,
            'mode': 'custom', 'owner_share_paise': 4000,
            'participants': [{'name': 'Isha', 'share_paise': 6000, 'contact_id': contact.json()['id']}],
        }, headers=headers)
        assert split.status_code == 201, split.text
        queued = await client.post(
            f"/api/v1/splits/balances/{contact.json()['id']}/email",
            headers={**headers, 'Idempotency-Key': str(uuid.uuid4())},
        )
        assert queued.status_code == 202, queued.text
        assert queued.json()['status'] == 'queued'
    finally:
        app.dependency_overrides.pop(get_split_notification_service, None)


async def test_split_scoped_campaign_queues_one_email_per_unpaid_participant_and_counts_once(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'split-campaign@example.com')
    headers = auth_headers(token)
    app.dependency_overrides[get_split_notification_service] = lambda: _service(db_session, channel='email')
    try:
        profile = await client.patch('/api/v1/auth/me', json={
            'name': 'Campaign Owner', 'date_of_birth': '1998-01-01', 'upi_id': 'owner@bank',
        }, headers=headers)
        assert profile.status_code == 200, profile.text
        contacts = []
        for name, email in [('Isha', 'isha@example.com'), ('Ravi', 'ravi@example.com')]:
            response = await client.put('/api/v1/splits/contacts/details', json={
                'name': name, 'email': email,
            }, headers=headers)
            assert response.status_code == 200, response.text
            contacts.append(response.json())
        transaction_id = await _expense(client, token)
        split_response = await client.post('/api/v1/splits', json={
            'transaction_id': transaction_id, 'title': 'Team dinner', 'amount_paise': 10000,
            'mode': 'custom', 'owner_share_paise': 2000,
            'participants': [
                {'name': 'Isha', 'share_paise': 5000, 'contact_id': contacts[0]['id']},
                {'name': 'Ravi', 'share_paise': 3000, 'contact_id': contacts[1]['id']},
            ],
        }, headers=headers)
        assert split_response.status_code == 201, split_response.text
        split = split_response.json()

        before = await client.get(f"/api/v1/splits/{split['id']}/notifications", headers=headers)
        assert before.status_code == 200, before.text
        assert before.json()['can_notify'] is True
        assert len(before.json()['recipients']) == 2

        campaign_key = str(uuid.uuid4())
        queued = await client.post(
            f"/api/v1/splits/{split['id']}/notifications",
            headers={**headers, 'Idempotency-Key': campaign_key},
        )
        assert queued.status_code == 202, queued.text
        assert queued.json()['campaign_id'] == campaign_key
        assert len(queued.json()['notification_ids']) == 2

        repeated = await client.post(
            f"/api/v1/splits/{split['id']}/notifications",
            headers={**headers, 'Idempotency-Key': campaign_key},
        )
        assert repeated.status_code == 202, repeated.text
        assert repeated.json()['notification_ids'] == queued.json()['notification_ids']

        after = await client.get(f"/api/v1/splits/{split['id']}/notifications", headers=headers)
        assert after.status_code == 200, after.text
        assert after.json()['notification_count'] == 1
        assert after.json()['request_in_progress'] is True

        repository = SqlAlchemySplitNotificationRepository(db_session)
        for notification_id in queued.json()['notification_ids']:
            await repository.complete(uuid.UUID(notification_id), status='sent', message_id='test-message')
        profile = await client.get('/api/v1/auth/me', headers=headers)
        user = await db_session.get(UserModel, uuid.UUID(profile.json()['id']))
        assert user is not None
        user.account_tier = 'test'
        await db_session.commit()
        app.dependency_overrides[get_split_notification_service] = lambda: _service(
            db_session, channel='email', max_per_split=1, max_per_user_daily=1,
        )
        bypassed = await client.post(
            f"/api/v1/splits/{split['id']}/notifications",
            headers={**headers, 'Idempotency-Key': str(uuid.uuid4())},
        )
        assert bypassed.status_code == 202, bypassed.text
        test_status = await client.get(f"/api/v1/splits/{split['id']}/notifications", headers=headers)
        assert test_status.json()['limits_bypassed'] is True

        provider = _FakeSmsProvider()
        session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
        processed = await run_split_notification_batch_once(
            provider, batch_size=10, stale_after_seconds=120, channel='email', session_factory=session_factory,
            pay_base_url='https://api.example.com/', app_url='https://app.example.com',
        )
        assert processed == 2
        assert len(provider.calls) == 2
        assert {call['recipient_email'] for call in provider.calls} == {'isha@example.com', 'ravi@example.com'}
        rendered = provider.calls[0]['email']
        assert rendered.subject.startswith('AffordAbled: Campaign Owner requested ₹')
        assert 'Pay with UPI' in rendered.html
        assert 'QR code' in rendered.html  # mentions QR is on the pay page
        assert len(rendered.inline_attachments) == 1  # logo only; QR is on pay page
        assert 'href="https://api.example.com/api/v1/pay/' in rendered.html
        assert 'Meet AffordAbled' in rendered.html
    finally:
        app.dependency_overrides.pop(get_split_notification_service, None)


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

        status_url = f"/api/v1/splits/{split['id']}/notifications"
        before = await client.get(status_url, headers=headers)
        assert before.status_code == 200, before.text
        assert before.json()['can_notify'] is True
        assert before.json()['recipients'][0]['recipient'].endswith('3210')

        key = str(uuid.uuid4())
        queued = await client.post(status_url, headers={**headers, 'Idempotency-Key': key})
        assert queued.status_code == 202, queued.text
        repeated = await client.post(status_url, headers={**headers, 'Idempotency-Key': key})
        assert repeated.status_code == 202, repeated.text
        assert repeated.json()['notification_ids'] == queued.json()['notification_ids']

        concurrent = await client.post(status_url, headers={**headers, 'Idempotency-Key': str(uuid.uuid4())})
        assert concurrent.status_code == 409, concurrent.text
        assert concurrent.json()['detail']['code'] == 'request_in_progress'

        repository = SqlAlchemySplitNotificationRepository(db_session)
        await repository.complete(uuid.UUID(queued.json()['notification_ids'][0]), status='sent', message_id='acs-1')
        cooldown = await client.post(status_url, headers={**headers, 'Idempotency-Key': str(uuid.uuid4())})
        assert cooldown.status_code == 429, cooldown.text
        assert cooldown.json()['detail']['code'] == 'cooldown_active'

        app.dependency_overrides[get_split_notification_service] = lambda: _service(
            db_session, cooldown_hours=0, max_per_split=1,
        )
        split_limit = await client.post(
            status_url, headers={**headers, 'Idempotency-Key': str(uuid.uuid4())},
        )
        assert split_limit.status_code == 429, split_limit.text
        assert split_limit.json()['detail']['code'] == 'split_limit_reached'

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
    url = f"/api/v1/splits/{split['id']}/notifications"
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


def test_branded_email_contains_safe_payment_details_and_inline_png_images() -> None:
    link = build_upi_link('owner@bank', 'Sarthak & Co', 12345, 'Dinner <script>alert(1)</script>')
    subject = build_email_subject('Sarthak & Co', 12345)
    plain_text = build_email_message(
        'Isha <Admin>', 'Sarthak & Co', 12345, 'Dinner <script>alert(1)</script>', 'owner@bank', link,
    )
    rendered = render_payment_request_email(
        subject=subject,
        plain_text=plain_text,
        contact_name='Isha <Admin>',
        creator_name='Sarthak & Co',
        amount_paise=12345,
        note='Dinner <script>alert(1)</script>',
        upi_id='owner@bank',
        upi_link=link,
    )

    assert rendered.subject == 'AffordAbled: Sarthak & Co requested ₹123.45 from you'
    assert 'Amount: ₹123.45' in rendered.plain_text
    assert 'Please do not reply to this email.' in rendered.plain_text
    assert 'Isha &lt;Admin&gt;' in rendered.html
    assert 'Dinner &lt;script&gt;alert(1)&lt;/script&gt;' in rendered.html
    assert 'Sarthak &amp; Co' in rendered.html
    assert '<script>' not in rendered.html
    assert 'Pay with UPI' in rendered.html
    assert f'cid:{LOGO_CONTENT_ID}' in rendered.html
    assert 'QR code' in rendered.html  # mentions QR is on the pay page
    assert [attachment.content_id for attachment in rendered.inline_attachments] == [LOGO_CONTENT_ID]
    assert all(attachment.content.startswith(b'\x89PNG\r\n\x1a\n') for attachment in rendered.inline_attachments)


async def test_azure_email_provider_sends_html_plain_text_and_cid_attachments() -> None:
    rendered = render_payment_request_email(
        subject='AffordAbled: Sarthak requested ₹150.00 from you',
        plain_text='Plain payment request',
        contact_name='Isha',
        creator_name='Sarthak',
        amount_paise=15000,
        note='Dinner',
        upi_id='owner@bank',
        upi_link=build_upi_link('owner@bank', 'Sarthak', 15000, 'Dinner'),
    )
    client = _FakeEmailClient()
    provider = AzureAcsEmailProvider.__new__(AzureAcsEmailProvider)
    provider._client = client
    provider._sender_address = 'DoNotReply@example.azurecomm.net'
    provider._timeout_seconds = 5

    result = await provider.send(
        recipient_email='isha@example.com', email=rendered, notification_id=uuid.uuid4(),
    )

    assert result.successful is True
    assert result.message_id == 'fake-email-1'
    assert len(client.messages) == 1
    payload = client.messages[0]
    assert payload['content']['subject'] == rendered.subject
    assert payload['content']['plainText'] == rendered.plain_text
    assert payload['content']['html'] == rendered.html
    assert payload['userEngagementTrackingDisabled'] is True
    assert [attachment['contentId'] for attachment in payload['attachments']] == [LOGO_CONTENT_ID]
    assert all(
        base64.b64decode(attachment['contentInBase64']).startswith(b'\x89PNG\r\n\x1a\n')
        for attachment in payload['attachments']
    )


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
        url = f"/api/v1/splits/{split['id']}/notifications"
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


def test_email_button_links_to_https_pay_page_and_includes_about_footer() -> None:
    link = 'upi://pay?pa=sarthak@upi&pn=Sarthak&am=500.00&cu=INR'
    email = render_payment_request_email(
        subject='s', plain_text='p', contact_name='Isha', creator_name='Sarthak', amount_paise=50000,
        note='Dinner', upi_id='sarthak@upi', upi_link=link,
        pay_url='https://api.example.com/api/v1/pay/abc', app_url='https://app.example.com',
    )
    assert 'href="https://api.example.com/api/v1/pay/abc"' in email.html
    assert 'href="upi://' not in email.html
    assert 'Meet AffordAbled' in email.html
    assert 'href="https://app.example.com"' in email.html and 'Try AffordAbled free' in email.html
    fallback = render_payment_request_email(
        subject='s', plain_text='p', contact_name='Isha', creator_name='Sarthak', amount_paise=50000,
        note='Dinner', upi_id='sarthak@upi', upi_link=link,
    )
    assert 'Try AffordAbled' not in fallback.html


async def test_public_pay_page_serves_upi_handoff_and_hides_unavailable_requests(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession,
) -> None:
    from app.infrastructure.database.models import SplitNotificationModel

    token = await register_and_get_token(client, 'pay-page@example.com')
    user_id = uuid.UUID((await client.get('/api/v1/auth/me', headers=auth_headers(token))).json()['id'])
    link = 'upi://pay?pa=sarthak%40upi&pn=Sar%3Cb%3E&am=500.00&cu=INR'

    def make(status: str) -> SplitNotificationModel:
        return SplitNotificationModel(
            id=uuid.uuid4(), sent_by_user_id=user_id, idempotency_key=uuid.uuid4(), channel='email',
            provider='azure_acs', recipient_name='Isha', amount_paise=50000, message_body='m', upi_link=link,
            status=status,
        )

    sent, cancelled = make('sent'), make('cancelled')
    db_session.add_all([sent, cancelled])
    await db_session.commit()
    app.dependency_overrides[get_split_notification_service] = lambda: _service(db_session, channel='email')
    try:
        page = await client.get(f'/api/v1/pay/{sent.id}')
        assert page.status_code == 200
        assert 'href="upi://pay?' in page.text and '₹500.00' in page.text
        assert 'Sar<b>' not in page.text  # payee name is escaped
        assert page.headers['cache-control'] == 'private, no-store'
        assert (await client.get(f'/api/v1/pay/{cancelled.id}')).status_code == 404
        assert (await client.get(f'/api/v1/pay/{uuid.uuid4()}')).status_code == 404
    finally:
        app.dependency_overrides.pop(get_split_notification_service, None)


async def test_split_description_can_be_edited_by_its_owner_only(client: AsyncClient) -> None:
    owner = await register_and_get_token(client, 'rename-owner@example.com')
    other = await register_and_get_token(client, 'rename-other@example.com')
    headers = auth_headers(owner)
    created = await client.post('/api/v1/splits/owed', json={
        'title': 'Old', 'name': 'Isha', 'amount_paise': 10000, 'direction': 'to_you',
    }, headers=headers)
    assert created.status_code == 201, created.text
    split_id = created.json()['id']

    renamed = await client.patch(f'/api/v1/splits/{split_id}/title', json={'title': '  Goa   trip  dinner '},
                                 headers=headers)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()['title'] == 'Goa trip dinner'
    assert (await client.patch(f'/api/v1/splits/{split_id}/title', json={'title': 'x'},
                               headers=auth_headers(other))).status_code == 404
    assert (await client.patch(f'/api/v1/splits/{split_id}/title', json={'title': '   '},
                               headers=headers)).status_code == 422
