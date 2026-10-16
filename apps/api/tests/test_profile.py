from __future__ import annotations

from httpx import AsyncClient

from tests.helpers import auth_headers, register_and_get_token


async def test_profile_details_can_be_updated_without_changing_login_email(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'profile-update@example.com')
    headers = auth_headers(token)

    response = await client.patch(
        '/api/v1/auth/me',
        json={'name': '  New   Display Name  ', 'date_of_birth': '1996-04-12'},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()['name'] == 'New Display Name'
    assert response.json()['date_of_birth'] == '1996-04-12'
    assert response.json()['email'] == 'profile-update@example.com'

    reloaded = await client.get('/api/v1/auth/me', headers=headers)
    assert reloaded.status_code == 200
    assert reloaded.json()['name'] == 'New Display Name'

    future_date = await client.patch(
        '/api/v1/auth/me', json={'name': 'Valid Name', 'date_of_birth': '2999-01-01'}, headers=headers
    )
    assert future_date.status_code == 422


async def test_profile_summary_uses_only_latest_five_owned_transactions(client: AsyncClient) -> None:
    owner = await register_and_get_token(client, 'profile-summary-owner@example.com')
    other = await register_and_get_token(client, 'profile-summary-other@example.com')
    owner_headers = auth_headers(owner)
    other_headers = auth_headers(other)

    empty = await client.get('/api/v1/auth/me/transaction-summary', headers=other_headers)
    assert empty.status_code == 200
    assert empty.json()['transaction_count'] == 0

    account = await client.post(
        '/api/v1/accounts',
        json={'name': 'Wallet', 'type': 'wallet', 'balance_paise': 100000, 'currency': 'INR'},
        headers=owner_headers,
    )
    food = await client.post(
        '/api/v1/categories', json={'name': 'Food', 'type': 'expense'}, headers=owner_headers
    )
    travel = await client.post(
        '/api/v1/categories', json={'name': 'Travel', 'type': 'expense'}, headers=owner_headers
    )
    assert account.status_code == food.status_code == travel.status_code == 201

    category_ids = [travel.json()['id'], food.json()['id']] * 3
    for day, category_id in enumerate(category_ids, start=1):
        created = await client.post(
            '/api/v1/transactions',
            json={
                'account_id': account.json()['id'],
                'category_id': category_id,
                'type': 'expense',
                'amount_paise': 100,
                'occurred_at': f'2026-10-{day:02d}T12:00:00+00:00',
            },
            headers=owner_headers,
        )
        assert created.status_code == 201

    summary = await client.get('/api/v1/auth/me/transaction-summary', headers=owner_headers)
    assert summary.status_code == 200
    assert summary.headers['cache-control'] == 'private, no-store'
    assert summary.json()['transaction_count'] == 5
    assert 'Food' in summary.json()['message']
    assert '3 of your latest 5' in summary.json()['message']

    other_summary = await client.get('/api/v1/auth/me/transaction-summary', headers=other_headers)
    assert other_summary.json()['transaction_count'] == 0
