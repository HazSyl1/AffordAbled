from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import SplitModel
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


async def test_settle_balance_offsets_open_split_and_records_net_cash(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'balance-settlement@example.com')
    headers = auth_headers(token)
    account_id, transaction_id = await _expense(client, token, amount=10000)
    split_response = await client.post('/api/v1/splits', json={
        'transaction_id': transaction_id, 'title': 'Dinner', 'amount_paise': 10000,
        'mode': 'equal', 'participants': [{'name': 'A'}],
    }, headers=headers)
    assert split_response.status_code == 201, split_response.text
    expense_split = split_response.json()
    owed_response = await client.post('/api/v1/splits/owed', json={
        'title': 'Tickets', 'name': 'A', 'amount_paise': 1000, 'direction': 'by_you',
    }, headers=headers)
    assert owed_response.status_code == 201, owed_response.text
    owed_split = owed_response.json()

    partial = await client.post(
        f"/api/v1/splits/{expense_split['id']}/participants/{expense_split['participants'][0]['id']}/payments",
        json={'account_id': account_id, 'amount_paise': 2000}, headers=headers,
    )
    assert partial.status_code == 200, partial.text
    preview = await client.get('/api/v1/splits/balances', headers=headers)
    assert preview.status_code == 200, preview.text
    person = next(row for row in preview.json() if row['person'] == 'A')
    assert person['owed_to_you_paise'] == 3000
    assert person['you_owe_paise'] == 1000
    assert person['net_paise'] == 2000

    settled = await client.post('/api/v1/splits/balances/settle', json={
        'person_name': 'A', 'account_id': account_id,
        'expected_owed_to_you_paise': 3000, 'expected_you_owe_paise': 1000,
    }, headers=headers)
    assert settled.status_code == 200, settled.text
    result = settled.json()
    assert result['offset_paise'] == 1000
    assert result['cash_direction'] == 'to_you'
    assert result['cash_paise'] == 2000
    assert result['net_after_paise'] == 0
    assert sum(transaction['amount_paise'] for transaction in result['transactions']) == 2000

    updated_expense = await client.get(f"/api/v1/splits/{expense_split['id']}", headers=headers)
    updated_owed = await client.get(f"/api/v1/splits/{owed_split['id']}", headers=headers)
    assert updated_expense.json()['participants'][0]['settled_paise'] == 5000
    assert updated_owed.json()['participants'][0]['settled_paise'] == 1000
    assert any(payment['transaction_id'] is None for payment in updated_owed.json()['participants'][0]['payments'])
    assert (await client.get('/api/v1/splits/balances', headers=headers)).json() == []


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


async def test_standalone_money_owed_is_distinct_and_user_scoped(client: AsyncClient) -> None:
    owner = await register_and_get_token(client, 'standalone-owed@example.com')
    other = await register_and_get_token(client, 'standalone-owed-other@example.com')
    created = await client.post('/api/v1/splits/owed', headers=auth_headers(owner), json={
        'title': 'Concert tickets', 'name': 'isha', 'amount_paise': 12500,
    })
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry['kind'] == 'money_owed'
    assert entry['transaction_id'] is None
    assert entry['title'] == 'Concert tickets'
    assert entry['total_paise'] == entry['outstanding_paise'] == 12500
    assert entry['owner_share_paise'] == 0
    assert entry['participants'][0]['name'] == 'Isha'
    assert (await client.get('/api/v1/splits', headers=auth_headers(other))).json() == []
    assert (await client.get(f"/api/v1/splits/{entry['id']}", headers=auth_headers(other))).status_code == 404


async def test_money_user_owes_is_payable_and_payment_creates_expense(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'standalone-payable@example.com')
    headers = auth_headers(token)
    account_id, _ = await _expense(client, token, amount=1000)
    created = await client.post('/api/v1/splits/owed', headers=headers, json={
        'title': 'Movie tickets', 'name': 'isha', 'amount_paise': 12500, 'direction': 'by_you',
    })
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry['kind'] == 'money_owed' and entry['direction'] == 'by_you'
    assert entry['transaction_id'] is None
    assert entry['outstanding_paise'] == 12500
    participant_id = entry['participants'][0]['id']

    paid = await client.post(
        f"/api/v1/splits/{entry['id']}/participants/{participant_id}/pay",
        headers=headers, json={'account_id': account_id},
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()['outstanding_paise'] == 0
    participant = paid.json()['participants'][0]
    assert participant['settled_paise'] == 12500
    repayment_id = participant['repayment_transaction_id']
    transaction = await client.get(f'/api/v1/transactions/{repayment_id}', headers=headers)
    assert transaction.status_code == 200
    assert transaction.json()['type'] == 'expense'
    assert transaction.json()['amount_paise'] == 12500
    categories = await client.get('/api/v1/categories', headers=headers)
    assert categories.status_code == 200
    category = next(item for item in categories.json() if item['id'] == transaction.json()['category_id'])
    assert category['name'] == 'Split'
    assert category['type'] == 'expense'
    balance = await client.get(f'/api/v1/accounts/{account_id}', headers=headers)
    assert balance.json()['balance_paise'] == 6500
    duplicate = await client.post(
        f"/api/v1/splits/{entry['id']}/participants/{participant_id}/pay",
        headers=headers, json={'account_id': account_id},
    )
    assert duplicate.status_code == 422


async def test_partial_iou_payments_update_balance_and_keep_linked_history(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'partial-iou@example.com')
    headers = auth_headers(token)
    account_id, _ = await _expense(client, token, amount=5000)
    created = await client.post('/api/v1/splits/owed', headers=headers, json={
        'title': 'Shared hotel', 'name': 'Isha', 'amount_paise': 10000, 'direction': 'by_you',
    })
    assert created.status_code == 201, created.text
    split = created.json()
    person = split['participants'][0]
    payment_path = f"/api/v1/splits/{split['id']}/participants/{person['id']}/payments"

    too_small = await client.post(payment_path, headers=headers, json={
        'account_id': account_id, 'amount_paise': 100,
    })
    assert too_small.status_code == 422
    too_large = await client.post(payment_path, headers=headers, json={
        'account_id': account_id, 'amount_paise': 10001,
    })
    assert too_large.status_code == 422

    partial = await client.post(payment_path, headers=headers, json={
        'account_id': account_id, 'amount_paise': 4000,
    })
    assert partial.status_code == 200, partial.text
    partial_person = partial.json()['participants'][0]
    assert partial.json()['outstanding_paise'] == 6000
    assert partial_person['settled_paise'] == 4000
    assert partial_person['repayment_transaction_id'] is None
    assert len(partial_person['payments']) == 1
    expense_id = partial_person['payments'][0]['transaction_id']
    expense = await client.get(f'/api/v1/transactions/{expense_id}', headers=headers)
    assert expense.json()['type'] == 'expense'
    assert expense.json()['amount_paise'] == 4000

    completed = await client.post(payment_path, headers=headers, json={'account_id': account_id})
    assert completed.status_code == 200, completed.text
    completed_person = completed.json()['participants'][0]
    assert completed.json()['outstanding_paise'] == 0
    assert completed_person['settled_paise'] == 10000
    assert completed_person['repayment_transaction_id'] == completed_person['payments'][-1]['transaction_id']
    assert len(completed_person['payments']) == 2
    account = await client.get(f'/api/v1/accounts/{account_id}', headers=headers)
    assert account.json()['balance_paise'] == 5000


async def test_partial_repayment_income_is_recorded_for_money_owed_to_user(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'partial-receivable@example.com')
    headers = auth_headers(token)
    account_id, _ = await _expense(client, token, amount=5000)
    created = await client.post('/api/v1/splits/owed', headers=headers, json={
        'title': 'Borrowed cash', 'name': 'A', 'amount_paise': 15000, 'direction': 'to_you',
    })
    assert created.status_code == 201, created.text
    split = created.json()
    person = split['participants'][0]
    partial = await client.post(
        f"/api/v1/splits/{split['id']}/participants/{person['id']}/payments",
        headers=headers, json={'account_id': account_id, 'amount_paise': 7500},
    )
    assert partial.status_code == 200, partial.text
    assert partial.json()['outstanding_paise'] == 7500
    payment = partial.json()['participants'][0]['payments'][0]
    transaction = await client.get(f"/api/v1/transactions/{payment['transaction_id']}", headers=headers)
    assert transaction.json()['type'] == 'income'
    assert transaction.json()['amount_paise'] == 7500
    account = await client.get(f'/api/v1/accounts/{account_id}', headers=headers)
    assert account.json()['balance_paise'] == 22500


async def test_standalone_money_owed_rejects_owner_as_debtor(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'standalone-owed-owner-alias@example.com')
    response = await client.post('/api/v1/splits/owed', headers=auth_headers(token), json={
        'title': 'Cash', 'name': 'myself', 'amount_paise': 1000,
    })
    assert response.status_code == 422


async def test_owner_alias_is_rejected_as_split_contact(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'split-no-owner-contact@example.com')
    _, transaction_id = await _expense(client, token, amount=1000)
    response = await client.post('/api/v1/splits', headers=auth_headers(token), json={
        'transaction_id': transaction_id, 'title': 'Dinner', 'amount_paise': 1000,
        'mode': 'equal', 'participants': [{'name': 'me'}],
    })
    assert response.status_code == 422
    assert 'tracked separately' in response.json()['detail']


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


async def test_mark_repaid_creates_and_links_a_single_categorized_transaction(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    await db_session.execute(text('PRAGMA foreign_keys=ON'))
    assert (await db_session.execute(text('PRAGMA foreign_keys'))).scalar_one() == 1
    owner = await register_and_get_token(client, 'split-repaid@example.com')
    other = await register_and_get_token(client, 'split-repaid-other@example.com')
    headers = auth_headers(owner)
    account_id, transaction_id = await _expense(client, owner, amount=1000)
    other_account_id, _ = await _expense(client, other)
    created = await client.post('/api/v1/splits', json={
        'transaction_id': transaction_id, 'title': 'Shared taxi', 'amount_paise': 1000,
        'mode': 'custom', 'owner_share_paise': 200,
        'participants': [{'name': 'Isha', 'share_paise': 800}],
    }, headers=headers)
    assert created.status_code == 201, created.text
    split = created.json()
    path = f"/api/v1/splits/{split['id']}/participants/{split['participants'][0]['id']}/repay"
    initial_balance = (await client.get(f'/api/v1/accounts/{account_id}', headers=headers)).json()['balance_paise']

    assert (await client.post(path, json={'account_id': other_account_id}, headers=headers)).status_code == 404
    assert (await client.post(path, json={'account_id': account_id},
                              headers=auth_headers(other))).status_code == 404
    assert len((await client.get('/api/v1/transactions', headers=headers)).json()) == 1

    repaid = await client.post(path, json={'account_id': account_id}, headers=headers)
    assert repaid.status_code == 200, repaid.text
    assert repaid.json()['outstanding_paise'] == 0
    person = repaid.json()['participants'][0]
    assert person['settled_paise'] == 800
    repayment_id = person['repayment_transaction_id']
    transactions = (await client.get('/api/v1/transactions', headers=headers)).json()
    repayment = next(transaction for transaction in transactions if transaction['id'] == repayment_id)
    assert len(transactions) == 2
    assert repayment['type'] == 'income'
    assert repayment['amount_paise'] == 800
    assert repayment['account_id'] == account_id
    categories = (await client.get('/api/v1/categories', headers=headers)).json()
    repayment_category = next(category for category in categories if category['id'] == repayment['category_id'])
    assert repayment_category['name'] == 'Split'
    assert repayment_category['type'] == 'income'
    assert (await client.get(f'/api/v1/accounts/{account_id}', headers=headers)).json()['balance_paise'] == (
        initial_balance + 800
    )
    assert (await client.patch(f'/api/v1/transactions/{repayment_id}',
                               json={'amount_paise': 900}, headers=headers)).status_code == 400
    assert (await client.delete(f'/api/v1/transactions/{repayment_id}', headers=headers)).status_code == 400
    assert (await client.post(path, json={'account_id': account_id}, headers=headers)).status_code == 422
    assert len((await client.get('/api/v1/transactions', headers=headers)).json()) == 2


async def test_mark_settlement_transfer_repaid_records_exact_plan_amount(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    owner = await register_and_get_token(client, 'settlement-transfer-repaid@example.com')
    headers = auth_headers(owner)
    account_id, transaction_id = await _expense(client, owner, amount=1000)
    created = await client.post('/api/v1/splits', json={
        'transaction_id': transaction_id, 'title': 'Adjusted dinner', 'amount_paise': 1000,
        'mode': 'custom', 'owner_share_paise': 200,
        'participants': [{'name': 'A', 'share_paise': 800}],
    }, headers=headers)
    assert created.status_code == 201, created.text
    split_id = created.json()['id']
    split_model = await db_session.scalar(select(SplitModel).where(SplitModel.id == uuid.UUID(split_id)))
    assert split_model is not None
    split_model.settlement_breakdown = {'transfers': [
        {'debtor': 'A', 'creditor': 'You', 'amount_paise': 1250},
        {'debtor': 'B', 'creditor': 'C', 'amount_paise': 500},
    ]}
    await db_session.commit()

    listed = (await client.get('/api/v1/splits', headers=headers)).json()[0]
    assert listed['outstanding_paise'] == 1250
    path = f'/api/v1/splits/{split_id}/settlement-transfers/repay'
    not_payable_to_owner = await client.post(path, headers=headers, json={
        'debtor': 'B', 'account_id': account_id,
    })
    assert not_payable_to_owner.status_code == 404

    repaid = await client.post(path, headers=headers, json={'debtor': 'A', 'account_id': account_id})
    assert repaid.status_code == 200, repaid.text
    assert repaid.json()['outstanding_paise'] == 0
    transfer = repaid.json()['settlement_breakdown']['transfers'][0]
    repayment_id = transfer['repayment_transaction_id']
    assert repaid.json()['participants'][0]['settled_paise'] == 1250
    assert repaid.json()['participants'][0]['repayment_transaction_id'] == repayment_id
    transactions = (await client.get('/api/v1/transactions', headers=headers)).json()
    repayment = next(item for item in transactions if item['id'] == repayment_id)
    assert repayment['type'] == 'income'
    assert repayment['amount_paise'] == 1250
    categories = (await client.get('/api/v1/categories', headers=headers)).json()
    repayment_category = next(category for category in categories if category['id'] == repayment['category_id'])
    assert repayment_category['name'] == 'Split'
    assert (await client.get(f'/api/v1/accounts/{account_id}', headers=headers)).json()['balance_paise'] == 20250
    duplicate = await client.post(path, headers=headers, json={'debtor': 'A', 'account_id': account_id})
    assert duplicate.status_code == 422
    assert (await client.delete(f'/api/v1/transactions/{repayment_id}', headers=headers)).status_code == 400
    assert len((await client.get('/api/v1/transactions', headers=headers)).json()) == 2


async def test_settle_balance_updates_partial_group_transfer_and_older_ioU_atomically(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    token = await register_and_get_token(client, 'settle-partial-group@example.com')
    headers = auth_headers(token)
    account_id, transaction_id = await _expense(client, token, amount=1000)
    created = await client.post('/api/v1/splits', headers=headers, json={
        'transaction_id': transaction_id, 'title': 'Group dinner', 'amount_paise': 1000,
        'mode': 'custom', 'owner_share_paise': 200,
        'participants': [{'name': 'A', 'share_paise': 800}],
    })
    assert created.status_code == 201, created.text
    group_split = await db_session.scalar(select(SplitModel).where(
        SplitModel.id == uuid.UUID(created.json()['id']),
    ))
    assert group_split is not None
    group_split.settlement_breakdown = {'transfers': [
        {'debtor': 'A', 'creditor': 'You', 'amount_paise': 800, 'settled_paise': 100},
    ]}
    owed = await client.post('/api/v1/splits/owed', headers=headers, json={
        'title': 'Old loan', 'name': 'A', 'amount_paise': 300, 'direction': 'by_you',
    })
    assert owed.status_code == 201, owed.text
    await db_session.commit()

    preview = (await client.get('/api/v1/splits/balances', headers=headers)).json()
    a_balance = next(item for item in preview if item['person'] == 'A')
    assert a_balance['owed_to_you_paise'] == 700
    assert a_balance['you_owe_paise'] == 300
    assert a_balance['net_paise'] == 400

    settled = await client.post('/api/v1/splits/balances/settle', headers=headers, json={
        'person_name': 'A', 'account_id': account_id, 'amount_paise': 200,
        'expected_owed_to_you_paise': 700, 'expected_you_owe_paise': 300,
    })
    assert settled.status_code == 200, settled.text
    assert settled.json()['offset_paise'] == 300
    assert settled.json()['cash_paise'] == 200
    assert settled.json()['net_after_paise'] == 200
    stale_confirmation = await client.post('/api/v1/splits/balances/settle', headers=headers, json={
        'person_name': 'A', 'account_id': account_id, 'amount_paise': 200,
        'expected_owed_to_you_paise': 700, 'expected_you_owe_paise': 300,
    })
    assert stale_confirmation.status_code == 422
    assert 'out of date' in stale_confirmation.json()['detail']

    refreshed = (await client.get('/api/v1/splits/balances', headers=headers)).json()
    a_balance = next(item for item in refreshed if item['person'] == 'A')
    assert a_balance['owed_to_you_paise'] == 200
    assert a_balance['you_owe_paise'] == 0
    group_after = (await client.get('/api/v1/splits', headers=headers)).json()
    group_after = next(item for item in group_after if item['id'] == created.json()['id'])
    assert group_after['outstanding_paise'] == 200
    transfer = group_after['settlement_breakdown']['transfers'][0]
    assert transfer['settled_paise'] == 600
    transactions = (await client.get('/api/v1/transactions', headers=headers)).json()
    settlement_transactions = [item for item in transactions if item['note'] == 'Balance settlement: Group dinner']
    assert len(settlement_transactions) == 1
    assert settlement_transactions[0]['type'] == 'income'
    assert settlement_transactions[0]['amount_paise'] == 200

    remaining_transfer = await client.post(
        f"/api/v1/splits/{created.json()['id']}/settlement-transfers/repay",
        headers=headers, json={'debtor': 'A', 'account_id': account_id},
    )
    assert remaining_transfer.status_code == 200, remaining_transfer.text
    assert remaining_transfer.json()['outstanding_paise'] == 0
    assert remaining_transfer.json()['settlement_breakdown']['transfers'][0]['settled_paise'] == 800
