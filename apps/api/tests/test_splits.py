from __future__ import annotations

from httpx import AsyncClient

from tests.helpers import auth_headers, register_and_get_token


async def _expense(client: AsyncClient, token: str, amount: int = 1001) -> tuple[str, str]:
    headers = auth_headers(token)
    account = await client.post(
        '/api/v1/accounts',
        json={'name': 'Split Wallet', 'type': 'wallet', 'balance_paise': 20000, 'currency': 'INR'},
        headers=headers,
    )
    category = await client.post(
        '/api/v1/categories', json={'name': 'Shared Food', 'type': 'expense'}, headers=headers,
    )
    assert account.status_code == category.status_code == 201
    transaction = await client.post('/api/v1/transactions', json={
        'account_id': account.json()['id'], 'category_id': category.json()['id'],
        'type': 'expense', 'amount_paise': amount, 'occurred_at': '2026-10-16T12:00:00+00:00',
    }, headers=headers)
    assert transaction.status_code == 201
    return account.json()['id'], transaction.json()['id']


async def test_equal_split_remainder_settlement_and_balance(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'split-owner@example.com')
    headers = auth_headers(token)
    account_id, transaction_id = await _expense(client, token)
    response = await client.post('/api/v1/splits', json={
        'transaction_id': transaction_id, 'title': 'Lunch', 'amount_paise': 1001,
        'mode': 'equal', 'participants': [{'name': 'A'}, {'name': 'B'}],
    }, headers=headers)
    assert response.status_code == 201, response.text
    split = response.json()
    assert split['owner_share_paise'] == 335
    assert [person['share_paise'] for person in split['participants']] == [333, 333]
    assert split['outstanding_paise'] == 666

    duplicate = await client.post('/api/v1/splits', json={
        'transaction_id': transaction_id, 'title': 'Lunch again', 'amount_paise': 1001,
        'mode': 'equal', 'participants': [{'name': 'A'}],
    }, headers=headers)
    assert duplicate.status_code == 422
    changed = await client.patch(
        f'/api/v1/transactions/{transaction_id}', json={'amount_paise': 1200}, headers=headers,
    )
    assert changed.status_code == 400
    deleted_expense = await client.delete(f'/api/v1/transactions/{transaction_id}', headers=headers)
    assert deleted_expense.status_code == 400
    income_category = await client.post(
        '/api/v1/categories', json={'name': 'Repayments', 'type': 'income'}, headers=headers,
    )
    assert income_category.status_code == 201
    repayment = await client.post('/api/v1/transactions', json={
        'account_id': account_id, 'category_id': income_category.json()['id'],
        'type': 'income', 'amount_paise': 333, 'occurred_at': '2026-10-17T12:00:00+00:00',
    }, headers=headers)
    assert repayment.status_code == 201
    repayment_id = repayment.json()['id']
    wrong_type = await client.post(
        f"/api/v1/splits/{split['id']}/participants/{split['participants'][0]['id']}/settle",
        json={'repayment_transaction_id': transaction_id}, headers=headers,
    )
    assert wrong_type.status_code == 404
    settled = await client.post(
        f"/api/v1/splits/{split['id']}/participants/{split['participants'][0]['id']}/settle",
        json={'repayment_transaction_id': repayment_id}, headers=headers,
    )
    assert settled.status_code == 200
    assert settled.json()['outstanding_paise'] == 333
    assert settled.json()['participants'][0]['repayment_transaction_id'] == repayment_id
    reused = await client.post(
        f"/api/v1/splits/{split['id']}/participants/{split['participants'][1]['id']}/settle",
        json={'repayment_transaction_id': repayment_id}, headers=headers,
    )
    assert reused.status_code == 422
    blocked_repayment_delete = await client.delete(f'/api/v1/transactions/{repayment_id}', headers=headers)
    assert blocked_repayment_delete.status_code == 400
    balance = await client.get(f'/api/v1/accounts/{account_id}', headers=headers)
    assert balance.json()['balance_paise'] == 19332  # Only the recorded repayment credits the account.
    removed = await client.delete(f"/api/v1/splits/{split['id']}", headers=headers)
    assert removed.status_code == 204
    assert (await client.get(f'/api/v1/transactions/{transaction_id}', headers=headers)).status_code == 200


async def test_custom_split_validation_and_owner_isolation(client: AsyncClient) -> None:
    owner = await register_and_get_token(client, 'split-private@example.com')
    other = await register_and_get_token(client, 'split-outsider@example.com')
    _, transaction_id = await _expense(client, owner, amount=1000)
    payload = {
        'transaction_id': transaction_id, 'title': 'Shared', 'amount_paise': 1000,
        'mode': 'custom', 'owner_share_paise': 250,
        'participants': [{'name': 'Sam', 'share_paise': 750}],
    }
    forbidden = await client.post('/api/v1/splits', json=payload, headers=auth_headers(other))
    assert forbidden.status_code == 404
    mismatch = await client.post('/api/v1/splits', json={**payload, 'owner_share_paise': 251},
                                 headers=auth_headers(owner))
    assert mismatch.status_code == 422
    created = await client.post('/api/v1/splits', json=payload, headers=auth_headers(owner))
    assert created.status_code == 201
    split_id = created.json()['id']
    participant_id = created.json()['participants'][0]['id']
    assert (await client.get('/api/v1/splits', headers=auth_headers(other))).json() == []
    assert (await client.get('/api/v1/splits/contacts', headers=auth_headers(other))).json() == []
    assert (await client.get(f'/api/v1/splits/{split_id}', headers=auth_headers(other))).status_code == 404
    assert (await client.patch(f'/api/v1/splits/{split_id}', json={
        'title': 'Changed', 'owner_share_paise': 250,
        'participants': [{'id': participant_id, 'name': 'Sam', 'share_paise': 750}],
    }, headers=auth_headers(other))).status_code == 404
    assert (await client.post(f'/api/v1/splits/{split_id}/participants/{participant_id}/settle',
                              json={'repayment_transaction_id': transaction_id},
                              headers=auth_headers(other))).status_code == 404
    assert (await client.delete(f'/api/v1/splits/{split_id}', headers=auth_headers(other))).status_code == 404
    assert (await client.get('/api/v1/splits/contacts', headers=auth_headers(owner))).json() == ['Sam']


async def test_edit_split_preserves_linked_repayments_and_participant_ids(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'split-edit@example.com')
    headers = auth_headers(token)
    account_id, transaction_id = await _expense(client, token, amount=1000)
    created = await client.post('/api/v1/splits', json={
        'transaction_id': transaction_id, 'title': 'Dinner', 'amount_paise': 1000,
        'mode': 'custom', 'owner_share_paise': 200,
        'participants': [{'name': 'A', 'share_paise': 400}, {'name': 'B', 'share_paise': 400}],
    }, headers=headers)
    assert created.status_code == 201, created.text
    split = created.json()
    people = {person['name']: person['id'] for person in split['participants']}
    path = f"/api/v1/splits/{split['id']}"

    edited = await client.patch(path, json={
        'title': 'Updated dinner', 'owner_share_paise': 100,
        'participants': [
            {'id': people['A'], 'name': 'B', 'share_paise': 500},
            {'name': 'C', 'share_paise': 400},
        ],
    }, headers=headers)
    assert edited.status_code == 200, edited.text
    assert edited.json()['title'] == 'Updated dinner'
    assert edited.json()['owner_share_paise'] == 100
    assert {person['name'] for person in edited.json()['participants']} == {'B', 'C'}
    assert next(person for person in edited.json()['participants'] if person['name'] == 'B')['id'] == people['A']
    assert (await client.patch(path, json={
        'title': 'Bad total', 'owner_share_paise': 101,
        'participants': [{'id': person['id'], 'name': person['name'], 'share_paise': person['share_paise']}
                         for person in edited.json()['participants']],
    }, headers=headers)).status_code == 422

    income_category = await client.post(
        '/api/v1/categories', json={'name': 'Repayments', 'type': 'income'}, headers=headers,
    )
    repayment = await client.post('/api/v1/transactions', json={
        'account_id': account_id, 'category_id': income_category.json()['id'],
        'type': 'income', 'amount_paise': 500, 'occurred_at': '2026-10-17T12:00:00+00:00',
    }, headers=headers)
    assert income_category.status_code == repayment.status_code == 201
    settled = await client.post(f"{path}/participants/{people['A']}/settle", json={
        'repayment_transaction_id': repayment.json()['id'],
    }, headers=headers)
    assert settled.status_code == 200, settled.text
    assert (await client.patch(path, json={
        'title': 'Cannot change paid share', 'owner_share_paise': 200,
        'participants': [
            {'id': people['A'], 'name': 'B', 'share_paise': 400},
            {'id': next(person['id'] for person in edited.json()['participants'] if person['name'] == 'C'),
             'name': 'C', 'share_paise': 400},
        ],
    }, headers=headers)).status_code == 422
    assert (await client.patch(path, json={
        'title': 'Cannot remove paid person', 'owner_share_paise': 600,
        'participants': [{'name': 'C', 'share_paise': 400}],
    }, headers=headers)).status_code == 422
    current = (await client.get(path, headers=headers)).json()
    paid = next(person for person in current['participants'] if person['id'] == people['A'])
    assert paid['share_paise'] == paid['settled_paise'] == 500
    assert paid['repayment_transaction_id'] == repayment.json()['id']
