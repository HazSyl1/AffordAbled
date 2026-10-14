from httpx import AsyncClient

from tests.helpers import auth_headers, register_and_get_token


async def test_auth_router_smoke(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'auth-smoke@example.com')

    me_response = await client.get('/api/v1/auth/me', headers=auth_headers(token))
    assert me_response.status_code == 200
    assert me_response.json()['email'] == 'auth-smoke@example.com'
    assert me_response.json()['name'] == 'Auth Smoke'
    assert me_response.json()['date_of_birth'] == '1998-01-01'


async def test_accounts_router_smoke(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'accounts-smoke@example.com')

    create_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Everyday Wallet', 'type': 'wallet', 'balance_paise': 10000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert create_response.status_code == 201
    account_id = create_response.json()['id']
    assert create_response.json()['is_default'] is True

    second_account_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'SBI Savings', 'type': 'bank', 'balance_paise': 20000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert second_account_response.status_code == 201
    assert second_account_response.json()['is_default'] is False

    list_response = await client.get('/api/v1/accounts', headers=auth_headers(token))
    assert list_response.status_code == 200
    assert len(list_response.json()) == 2

    make_default_response = await client.patch(
        f"/api/v1/accounts/{second_account_response.json()['id']}/default",
        headers=auth_headers(token),
    )
    assert make_default_response.status_code == 200
    assert make_default_response.json()['is_default'] is True

    refreshed_accounts = await client.get('/api/v1/accounts', headers=auth_headers(token))
    assert refreshed_accounts.status_code == 200
    assert sum(account['is_default'] for account in refreshed_accounts.json()) == 1
    assert next(account for account in refreshed_accounts.json() if account['id'] == account_id)['is_default'] is False

    get_response = await client.get(f'/api/v1/accounts/{account_id}', headers=auth_headers(token))
    assert get_response.status_code == 200
    assert get_response.json()['balance_paise'] == 10000
