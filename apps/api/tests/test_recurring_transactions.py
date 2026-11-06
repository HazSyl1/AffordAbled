from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.application.services.recurring_transaction_service import next_occurrence
from app.domain.entities import RecurrenceUnit, RecurringRuleStatus, RecurringTransactionRule, TransactionType
from app.infrastructure.jobs.recurring_transaction_jobs import (
    seconds_until_next_due,
    wait_for_schedule_change_or_timeout,
)
from app.infrastructure.recurring_scheduler_signal import (
    clear_recurring_scheduler_wakeup,
    install_recurring_scheduler_wakeup,
)
from tests.helpers import auth_headers, register_and_get_token


async def _setup(client: AsyncClient, email: str, *, category_type: str = 'expense'):
    token = await register_and_get_token(client, email)
    headers = auth_headers(token)
    account = await client.post('/api/v1/accounts', headers=headers, json={
        'name': 'Recurring Account', 'type': 'bank', 'balance_paise': 100000, 'currency': 'INR',
    })
    category = await client.post('/api/v1/categories', headers=headers, json={
        'name': 'Recurring Category', 'type': category_type,
    })
    assert account.status_code == category.status_code == 201
    return headers, account.json(), category.json()


def _rule(anchor: datetime, unit: RecurrenceUnit) -> RecurringTransactionRule:
    import uuid

    now = datetime.now(UTC)
    return RecurringTransactionRule(
        id=uuid.uuid4(), user_id=uuid.uuid4(), account_id=uuid.uuid4(), category_id=uuid.uuid4(),
        type=TransactionType.EXPENSE, amount_paise=100, merchant='Test', note=None,
        recurrence_unit=unit, interval_count=1, anchor_at=anchor, timezone='UTC', end_at=None,
        max_occurrences=None, next_occurrence_at=anchor, generated_count=0,
        status=RecurringRuleStatus.ACTIVE, source='manual', source_memory_id=None, source_turn_id=None,
        source_task_id=None, attempts=0, claimed_at=None, last_error=None, created_at=now, updated_at=now,
    )


def test_month_end_recurrence_clamps_and_returns_to_anchor_day() -> None:
    rule = _rule(datetime(2027, 1, 31, 9, tzinfo=UTC), RecurrenceUnit.MONTHLY)
    february = next_occurrence(rule.anchor_at, rule)
    march = next_occurrence(february, rule)
    assert february == datetime(2027, 2, 28, 9, tzinfo=UTC)
    assert march == datetime(2027, 3, 31, 9, tzinfo=UTC)


def test_scheduler_sleeps_until_nearest_due_rule_but_caps_idle_wait() -> None:
    now = datetime.now(UTC)
    assert seconds_until_next_due(now + timedelta(seconds=20), max_sleep_seconds=300) <= 20
    assert seconds_until_next_due(now + timedelta(hours=2), max_sleep_seconds=300) == 300
    assert seconds_until_next_due(None, max_sleep_seconds=300) == 300


async def test_scheduler_wait_is_interrupted_when_a_rule_change_is_signalled() -> None:
    event = asyncio.Event()
    waiting = asyncio.create_task(wait_for_schedule_change_or_timeout(event, 60))
    await asyncio.sleep(0)
    event.set()
    assert await waiting is True


async def test_manual_recurring_transaction_creates_initial_and_can_pause_resume_cancel(
    client: AsyncClient,
) -> None:
    headers, account, category = await _setup(client, 'recurring-api@example.com')
    response = await client.post('/api/v1/recurring-transactions', headers=headers, json={
        'account_id': account['id'], 'category_id': category['id'], 'type': 'expense',
        'amount_paise': 15000, 'merchant': 'Rent', 'recurrence_unit': 'monthly',
        'interval_count': 1, 'anchor_at': '2026-11-01T09:00:00+05:30', 'timezone': 'Asia/Calcutta',
        'create_initial_transaction': True,
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['rule']['status'] == 'active'
    assert body['rule']['generated_count'] == 1
    assert body['initial_transaction']['recurring_rule_id'] == body['rule']['id']

    transactions = await client.get('/api/v1/transactions', headers=headers)
    assert len(transactions.json()) == 1
    assert account['balance_paise'] - transactions.json()[0]['amount_paise'] == 85000

    rule_id = body['rule']['id']
    paused = await client.post(f'/api/v1/recurring-transactions/{rule_id}/pause', headers=headers)
    assert paused.status_code == 200 and paused.json()['status'] == 'paused'
    resumed = await client.post(f'/api/v1/recurring-transactions/{rule_id}/resume', headers=headers)
    assert resumed.status_code == 200 and resumed.json()['status'] == 'active'
    cancelled = await client.delete(f'/api/v1/recurring-transactions/{rule_id}', headers=headers)
    assert cancelled.status_code == 200 and cancelled.json()['status'] == 'cancelled'
    assert len((await client.get('/api/v1/transactions', headers=headers)).json()) == 1


async def test_creating_a_rule_signals_the_sleeping_scheduler(client: AsyncClient) -> None:
    headers, account, category = await _setup(client, 'recurring-signal@example.com')
    event = asyncio.Event()
    install_recurring_scheduler_wakeup(event)
    try:
        response = await client.post('/api/v1/recurring-transactions', headers=headers, json={
            'account_id': account['id'], 'category_id': category['id'], 'type': 'expense',
            'amount_paise': 5000, 'merchant': 'Signal test', 'recurrence_unit': 'monthly',
            'anchor_at': (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            'timezone': 'UTC', 'create_initial_transaction': False,
        })
        assert response.status_code == 201, response.text
        assert event.is_set()
    finally:
        clear_recurring_scheduler_wakeup(event)


async def test_backdated_initial_recurring_entry_does_not_backfill_old_cycles(client: AsyncClient) -> None:
    headers, account, category = await _setup(client, 'recurring-backdated@example.com')
    anchor = datetime.now(UTC) - timedelta(days=120)
    response = await client.post('/api/v1/recurring-transactions', headers=headers, json={
        'account_id': account['id'], 'category_id': category['id'], 'type': 'expense',
        'amount_paise': 10000, 'merchant': 'Backdated rent', 'recurrence_unit': 'monthly',
        'anchor_at': anchor.isoformat(), 'timezone': 'UTC', 'create_initial_transaction': True,
    })
    assert response.status_code == 201, response.text
    next_occurrence = datetime.fromisoformat(response.json()['rule']['next_occurrence_at'])
    if next_occurrence.tzinfo is None:
        next_occurrence = next_occurrence.replace(tzinfo=UTC)
    assert next_occurrence > datetime.now(UTC)
    # Only the transaction deliberately entered by the user is recorded.
    assert len((await client.get('/api/v1/transactions', headers=headers)).json()) == 1


async def test_three_exact_monthly_transactions_create_reviewable_suggestion(client: AsyncClient) -> None:
    headers, account, category = await _setup(client, 'recurring-memory@example.com')
    for occurred_at in ('2026-08-31T09:00:00+05:30', '2026-09-30T09:00:00+05:30',
                        '2026-10-31T09:00:00+05:30'):
        response = await client.post('/api/v1/transactions', headers=headers, json={
            'account_id': account['id'], 'category_id': category['id'], 'type': 'expense',
            'amount_paise': 99900, 'merchant': 'Internet Provider', 'occurred_at': occurred_at,
            'timezone': 'Asia/Calcutta',
        })
        assert response.status_code == 201, response.text
    suggestions = await client.get('/api/v1/memories/suggestions', headers=headers)
    assert suggestions.status_code == 200
    recurring = [item for item in suggestions.json() if item['memory_type'] == 'recurring_transaction']
    assert len(recurring) == 1
    assert recurring[0]['value']['recurrence_unit'] == 'monthly'
    assert recurring[0]['evidence_count'] == 3
    value = recurring[0]['value']
    activated = await client.post('/api/v1/recurring-transactions', headers=headers, json={
        'account_id': value['account_id'], 'category_id': value['category_id'], 'type': value['type'],
        'amount_paise': value['amount_paise'], 'merchant': value['merchant'],
        'recurrence_unit': value['recurrence_unit'], 'interval_count': value['interval_count'],
        'anchor_at': value['anchor_at'], 'timezone': value['timezone'],
        'create_initial_transaction': False, 'source_memory_id': recurring[0]['id'],
    })
    assert activated.status_code == 201, activated.text
    assert activated.json()['rule']['source'] == 'memory'
    assert activated.json()['initial_transaction'] is None
    assert (await client.get('/api/v1/memories/suggestions', headers=headers)).json() == []


async def test_variable_amounts_do_not_create_recurring_suggestion(client: AsyncClient) -> None:
    headers, account, category = await _setup(client, 'recurring-variable@example.com')
    for amount, occurred_at in zip(
        (10000, 10001, 10002),
        ('2026-08-01T09:00:00+00:00', '2026-09-01T09:00:00+00:00', '2026-10-01T09:00:00+00:00'),
        strict=True,
    ):
        response = await client.post('/api/v1/transactions', headers=headers, json={
            'account_id': account['id'], 'category_id': category['id'], 'type': 'expense',
            'amount_paise': amount, 'merchant': 'Variable Merchant', 'occurred_at': occurred_at,
        })
        assert response.status_code == 201
    assert (await client.get('/api/v1/memories/suggestions', headers=headers)).json() == []
