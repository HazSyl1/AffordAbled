from httpx import AsyncClient

from tests.helpers import auth_headers, register_and_get_token


async def test_transactions_router_smoke(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'transactions-smoke@example.com')

    account_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Main Wallet', 'type': 'wallet', 'balance_paise': 250000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert account_response.status_code == 201
    account_id = account_response.json()['id']

    category_response = await client.post(
        '/api/v1/categories',
        json={'name': 'Food', 'type': 'expense'},
        headers=auth_headers(token),
    )
    assert category_response.status_code == 201
    category_id = category_response.json()['id']

    create_response = await client.post(
        '/api/v1/transactions',
        json={
            'account_id': account_id,
            'category_id': category_id,
            'type': 'expense',
            'amount_paise': 19900,
            'merchant': 'Cafe Test',
            'note': 'Lunch',
            'occurred_at': '2026-09-22T10:00:00+05:30',
        },
        headers=auth_headers(token),
    )
    assert create_response.status_code == 201
    transaction_id = create_response.json()['id']

    list_response = await client.get('/api/v1/transactions', headers=auth_headers(token))
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = await client.get(f'/api/v1/transactions/{transaction_id}', headers=auth_headers(token))
    assert get_response.status_code == 200
    assert get_response.json()['amount_paise'] == 19900

    patch_response = await client.patch(
        f'/api/v1/transactions/{transaction_id}',
        json={'merchant': 'Cafe Updated', 'note': 'Lunch with team'},
        headers=auth_headers(token),
    )
    assert patch_response.status_code == 200
    assert patch_response.json()['merchant'] == 'Cafe Updated'

    delete_response = await client.delete(f'/api/v1/transactions/{transaction_id}', headers=auth_headers(token))
    assert delete_response.status_code == 204

    get_after_delete_response = await client.get(f'/api/v1/transactions/{transaction_id}', headers=auth_headers(token))
    assert get_after_delete_response.status_code == 404

    restore_response = await client.post(
        f'/api/v1/transactions/{transaction_id}/restore',
        headers=auth_headers(token),
    )
    assert restore_response.status_code == 204

    get_after_restore_response = await client.get(
        f'/api/v1/transactions/{transaction_id}',
        headers=auth_headers(token),
    )
    assert get_after_restore_response.status_code == 200


async def test_transfer_requires_sufficient_source_balance(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'transfer-rule@example.com')

    source_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Source', 'type': 'bank', 'balance_paise': 5000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert source_response.status_code == 201

    destination_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Destination', 'type': 'bank', 'balance_paise': 1000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert destination_response.status_code == 201

    source_id = source_response.json()['id']
    destination_id = destination_response.json()['id']

    transfer_response = await client.post(
        '/api/v1/transactions',
        json={
            'account_id': source_id,
            'to_account_id': destination_id,
            'type': 'transfer',
            'amount_paise': 9000,
            'occurred_at': '2026-09-22T12:00:00+05:30',
        },
        headers=auth_headers(token),
    )
    assert transfer_response.status_code == 400
