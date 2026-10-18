from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.ai.agents.analytics import AnalyticsToolset
from app.infrastructure.ai.agents.contracts import HandoffContext
from app.infrastructure.ai.tools.transaction_query_tools import TransactionQueryTools
from app.infrastructure.database.repositories.sqlalchemy_account_repository import SqlAlchemyAccountRepository
from app.infrastructure.database.repositories.sqlalchemy_category_repository import SqlAlchemyCategoryRepository
from app.infrastructure.database.repositories.sqlalchemy_transaction_repository import SqlAlchemyTransactionRepository
from app.infrastructure.database.repositories.sqlalchemy_user_repository import SqlAlchemyUserRepository
from tests.helpers import auth_headers, register_and_get_token


async def _get_account_balance(client: AsyncClient, token: str, account_id: str) -> int:
    response = await client.get(f'/api/v1/accounts/{account_id}', headers=auth_headers(token))
    assert response.status_code == 200
    return response.json()['balance_paise']


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
    assert create_response.json()['occurred_at'].startswith('2026-09-22')

    assert await _get_account_balance(client, token, account_id) == 230100

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
    assert await _get_account_balance(client, token, account_id) == 230100

    delete_response = await client.delete(f'/api/v1/transactions/{transaction_id}', headers=auth_headers(token))
    assert delete_response.status_code == 204
    assert await _get_account_balance(client, token, account_id) == 250000

    get_after_delete_response = await client.get(f'/api/v1/transactions/{transaction_id}', headers=auth_headers(token))
    assert get_after_delete_response.status_code == 404

    restore_response = await client.post(
        f'/api/v1/transactions/{transaction_id}/restore',
        headers=auth_headers(token),
    )
    assert restore_response.status_code == 204
    assert await _get_account_balance(client, token, account_id) == 230100

    get_after_restore_response = await client.get(
        f'/api/v1/transactions/{transaction_id}',
        headers=auth_headers(token),
    )
    assert get_after_restore_response.status_code == 200


async def test_transactions_and_account_ids_are_scoped_to_the_authenticated_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await register_and_get_token(client, 'transactions-owner-isolation@example.com')
    other = await register_and_get_token(client, 'transactions-other-isolation@example.com')
    owner_headers = auth_headers(owner)
    other_headers = auth_headers(other)
    account = await client.post(
        '/api/v1/accounts',
        json={'name': 'Private Bank', 'type': 'bank', 'balance_paise': 100000, 'currency': 'INR'},
        headers=owner_headers,
    )
    category = await client.post(
        '/api/v1/categories', json={'name': 'Private Food', 'type': 'expense'}, headers=owner_headers
    )
    assert account.status_code == 201 and category.status_code == 201
    transaction = await client.post(
        '/api/v1/transactions',
        json={
            'account_id': account.json()['id'],
            'category_id': category.json()['id'],
            'type': 'expense',
            'amount_paise': 1234,
            'occurred_at': '2026-10-10T12:00:00+00:00',
        },
        headers=owner_headers,
    )
    assert transaction.status_code == 201

    other_list = await client.get('/api/v1/transactions', headers=other_headers)
    other_get = await client.get(f"/api/v1/transactions/{transaction.json()['id']}", headers=other_headers)
    other_create = await client.post(
        '/api/v1/transactions',
        json={
            'account_id': account.json()['id'],
            'category_id': category.json()['id'],
            'type': 'expense',
            'amount_paise': 100,
            'occurred_at': '2026-10-10T12:00:00+00:00',
        },
        headers=other_headers,
    )
    assert other_list.status_code == 200 and other_list.json() == []
    assert other_get.status_code == 404
    assert other_create.status_code == 404

    users = SqlAlchemyUserRepository(db_session)
    owner_user = await users.get_by_email('transactions-owner-isolation@example.com')
    other_user = await users.get_by_email('transactions-other-isolation@example.com')
    assert owner_user is not None and other_user is not None
    analytics = AnalyticsToolset(
        TransactionQueryTools(
            transaction_repository=SqlAlchemyTransactionRepository(db_session),
            account_repository=SqlAlchemyAccountRepository(db_session),
            category_repository=SqlAlchemyCategoryRepository(db_session),
        )
    )
    query_args = {
        'date_from': datetime(2026, 10, 1, tzinfo=UTC).isoformat(),
        'date_to': datetime(2026, 10, 31, tzinfo=UTC).isoformat(),
        'user_id': str(owner_user.id),
    }
    owner_result = await analytics.get_transactions(
        HandoffContext(user_id=owner_user.id, request='transactions in October'), query_args
    )
    other_result = await analytics.get_transactions(
        HandoffContext(user_id=other_user.id, request='transactions in October'), query_args
    )
    assert len(owner_result['transactions']) == 1
    assert other_result['transactions'] == []


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


async def test_transfer_updates_balances_and_reapplies_on_update(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'transfer-balance-flow@example.com')

    source_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Source', 'type': 'bank', 'balance_paise': 10000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert source_response.status_code == 201

    destination_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Destination', 'type': 'bank', 'balance_paise': 3000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert destination_response.status_code == 201

    source_id = source_response.json()['id']
    destination_id = destination_response.json()['id']

    create_transfer_response = await client.post(
        '/api/v1/transactions',
        json={
            'account_id': source_id,
            'to_account_id': destination_id,
            'type': 'transfer',
            'amount_paise': 4000,
            'occurred_at': '2026-09-22T12:30:00+05:30',
        },
        headers=auth_headers(token),
    )
    assert create_transfer_response.status_code == 201
    transfer_id = create_transfer_response.json()['id']

    assert await _get_account_balance(client, token, source_id) == 6000
    assert await _get_account_balance(client, token, destination_id) == 7000

    update_transfer_response = await client.patch(
        f'/api/v1/transactions/{transfer_id}',
        json={'amount_paise': 2500},
        headers=auth_headers(token),
    )
    assert update_transfer_response.status_code == 200

    assert await _get_account_balance(client, token, source_id) == 7500
    assert await _get_account_balance(client, token, destination_id) == 5500
