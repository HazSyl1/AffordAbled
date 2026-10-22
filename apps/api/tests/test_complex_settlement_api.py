from __future__ import annotations

from copy import deepcopy

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import auth_headers, register_and_get_token


async def test_single_payer_preview_and_confirmation_use_final_adjusted_amount(client: AsyncClient) -> None:
    owner = auth_headers(await register_and_get_token(client, 'adjusted-meal@example.com'))
    account = await client.post('/api/v1/accounts', json={
        'name': 'Axis', 'type': 'bank', 'balance_paise': 2000000, 'currency': 'INR',
    }, headers=owner)
    category = await client.post('/api/v1/categories', json={
        'name': 'Food', 'type': 'expense',
    }, headers=owner)
    assert account.status_code == category.status_code == 201
    data = {
        'title': 'Swiggy dinner', 'participants': ['You', 'A'], 'debts': [],
        'bills': [{'id': 'dinner', 'merchant': 'Swiggy',
                   'charges': [{'id': 'meal', 'label': 'Meal', 'amount_paise': 1700000,
                                'shared_by': ['You', 'A']}],
                   'extras': [{'label': 'Card fee', 'kind': 'fee', 'rate_bps': 270,
                               'base_charge_ids': ['meal'], 'shared_by': ['A']}],
                   'discounts': [{'label': 'Swiggy coupon', 'charge_ids': ['meal'],
                                  'rate_bps': 1000, 'include_extras': True}],
                   'payments': [{'person': 'You', 'account_id': account.json()['id'],
                                 'category_id': category.json()['id']}]}],
    }
    response = await client.post('/api/v1/settlement-plans/drafts', json={
        'request_key': 'swiggy-fee-first', 'data': data,
    }, headers=owner)
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft['preview']['total_paise'] == 1571310
    assert (await client.get('/api/v1/transactions', headers=owner)).json() == []
    confirmed = await client.post(f"/api/v1/settlement-plans/drafts/{draft['id']}/confirm",
                                  json={'version': draft['version']}, headers=owner)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['data']['bills'][0]['payments'][0]['amount_paise'] == 1571310
    transactions = (await client.get('/api/v1/transactions', headers=owner)).json()
    assert len(transactions) == 1
    assert transactions[0]['amount_paise'] == 1571310


async def test_partial_friend_payment_is_derived_and_saved_without_wallet_transaction(client: AsyncClient) -> None:
    owner = auth_headers(await register_and_get_token(client, 'cafe-rows@example.com'))
    account = await client.post('/api/v1/accounts', json={
        'name': 'Axis', 'type': 'bank', 'balance_paise': 700000, 'currency': 'INR',
    }, headers=owner)
    category = await client.post('/api/v1/categories', json={'name': 'Food', 'type': 'expense'}, headers=owner)
    assert account.status_code == category.status_code == 201
    data = {'title': 'Cafe XYZ', 'participants': ['You', 'A', 'E'], 'debts': [],
            'bills': [{'id': 'xyz', 'merchant': 'Cafe XYZ',
                       'charges': [
                           {'id': 'vada', 'label': 'Vada pav', 'amount_paise': 100000, 'shared_by': ['A']},
                           {'id': 'other', 'label': 'Other food', 'amount_paise': 600000, 'shared_by': ['You']},
                       ],
                       'extras': [{'id': 'a-tip', 'label': 'A tip', 'kind': 'tip',
                                   'rate_bps': 500, 'base_charge_ids': ['vada'], 'shared_by': ['E']}],
                       'payments': [
                           {'person': 'A', 'covered_charge_ids': ['vada'], 'covered_extra_ids': ['a-tip']},
                           {'person': 'You', 'amount_paise': 600000,
                            'account_id': account.json()['id'], 'category_id': category.json()['id']},
                       ]}]}
    draft_response = await client.post('/api/v1/settlement-plans/drafts', json={
        'request_key': 'cafe-rows', 'data': data,
    }, headers=owner)
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()
    assert draft['preview']['bills'][0]['payment_amounts_paise'] == [105000, 600000]
    confirmed = await client.post(f"/api/v1/settlement-plans/drafts/{draft['id']}/confirm",
                                  json={'version': draft['version']}, headers=owner)
    assert confirmed.status_code == 200, confirmed.text
    plan = confirmed.json()
    assert plan['data']['bills'][0]['payments'][0]['amount_paise'] == 105000
    assert len((await client.get('/api/v1/transactions', headers=owner)).json()) == 1


async def test_draft_confirm_friend_settlement_and_revision(client: AsyncClient, db_session: AsyncSession) -> None:
    await db_session.execute(text('PRAGMA foreign_keys=ON'))
    assert await db_session.scalar(text('PRAGMA foreign_keys')) == 1
    owner = auth_headers(await register_and_get_token(client, 'complex-owner@example.com'))
    outsider = auth_headers(await register_and_get_token(client, 'complex-outsider@example.com'))
    account = await client.post('/api/v1/accounts', json={
        'name': 'Axis', 'type': 'bank', 'balance_paise': 20000, 'currency': 'INR',
    }, headers=owner)
    category = await client.post('/api/v1/categories', json={
        'name': 'Food', 'type': 'expense',
    }, headers=owner)
    assert account.status_code == category.status_code == 201
    account_id = account.json()['id']
    category_id = category.json()['id']
    data = {
        'title': 'Dinner and cafe', 'participants': ['You', 'A', 'E'], 'debts': [],
        'bills': [
            {'id': 'dinner', 'merchant': 'Dinner',
             'charges': [{'id': 'owner-meal', 'label': 'My meal', 'amount_paise': 10000,
                          'shared_by': ['You']}],
             'discounts': [], 'extras': [],
             'payments': [{'person': 'You', 'amount_paise': 10000,
                           'account_id': account_id, 'category_id': category_id}]},
            {'id': 'cafe', 'merchant': 'Cafe',
             'charges': [{'id': 'tea', 'label': 'Tea', 'amount_paise': 2000, 'shared_by': ['E']}],
             'discounts': [],
             'extras': [{'kind': 'tip', 'label': 'Tip', 'amount_paise': 100, 'shared_by': ['E']}],
             'payments': [{'person': 'A', 'amount_paise': 2100}]},
        ],
    }
    draft_response = await client.post('/api/v1/settlement-plans/drafts', json={
        'request_key': 'dinner-and-cafe', 'data': data,
    }, headers=owner)
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()
    assert draft['preview']['transfers'] == [
        {'debtor': 'E', 'creditor': 'A', 'amount_paise': 2100},
    ]
    assert (await client.get('/api/v1/transactions', headers=owner)).json() == []
    assert (await client.get(f"/api/v1/settlement-plans/drafts/{draft['id']}", headers=outsider)).status_code == 404

    confirmed = await client.post(f"/api/v1/settlement-plans/drafts/{draft['id']}/confirm",
                                  json={'version': draft['version']}, headers=owner)
    assert confirmed.status_code == 200, confirmed.text
    plan = confirmed.json()
    assert len(plan['transaction_ids']) == 1
    assert plan['data']['bills'][0]['payments'][0]['transaction_id'] == plan['transaction_ids'][0]
    repeated = await client.post(f"/api/v1/settlement-plans/drafts/{draft['id']}/confirm",
                                 json={'version': draft['version']}, headers=owner)
    assert repeated.status_code == 200
    assert repeated.json()['id'] == plan['id']
    transactions = (await client.get('/api/v1/transactions', headers=owner)).json()
    assert len(transactions) == 1
    assert (await client.get(f'/api/v1/accounts/{account_id}', headers=owner)).json()['balance_paise'] == 10000
    assert (await client.patch(f"/api/v1/transactions/{plan['transaction_ids'][0]}",
                               json={'amount_paise': 8000}, headers=owner)).status_code == 400
    assert (await client.delete(f"/api/v1/transactions/{plan['transaction_ids'][0]}",
                                headers=owner)).status_code == 400

    settled = await client.post(
        f"/api/v1/settlement-plans/{plan['id']}/transfers/{plan['transfers'][0]['id']}/settle",
        json={}, headers=owner,
    )
    assert settled.status_code == 200, settled.text
    assert settled.json()['transfers'][0]['settled_at']
    assert len((await client.get('/api/v1/transactions', headers=owner)).json()) == 1

    revised_data = deepcopy(plan['data'])
    revised_data['bills'][0]['charges'][0]['shared_by'] = ['You', 'E']
    revision = await client.post('/api/v1/settlement-plans/drafts', json={
        'request_key': 'dinner-and-cafe-revision', 'data': revised_data, 'revision_plan_id': plan['id'],
    }, headers=owner)
    assert revision.status_code == 200, revision.text
    assert revision.json()['preview']['transfers'] == [
        {'debtor': 'E', 'creditor': 'You', 'amount_paise': 5000},
    ]
    revised = await client.post(f"/api/v1/settlement-plans/drafts/{revision.json()['id']}/confirm",
                                json={'version': revision.json()['version']}, headers=owner)
    assert revised.status_code == 200, revised.text
    assert revised.json()['id'] == plan['id']
    assert len(revised.json()['transfers']) == 2
    assert len([row for row in revised.json()['transfers'] if row['settled_at']]) == 1
    assert len((await client.get('/api/v1/transactions', headers=owner)).json()) == 1
    pending = next(row for row in revised.json()['transfers'] if not row['settled_at'])
    repayment = await client.post(
        f"/api/v1/settlement-plans/{plan['id']}/transfers/{pending['id']}/settle",
        json={'account_id': account_id}, headers=owner,
    )
    assert repayment.status_code == 200, repayment.text
    assert len((await client.get('/api/v1/transactions', headers=owner)).json()) == 2
    assert (await client.get(f'/api/v1/accounts/{account_id}', headers=owner)).json()['balance_paise'] == 15000
    repeated_repayment = await client.post(
        f"/api/v1/settlement-plans/{plan['id']}/transfers/{pending['id']}/settle",
        json={'account_id': account_id}, headers=owner,
    )
    assert repeated_repayment.status_code == 200
    assert len((await client.get('/api/v1/transactions', headers=owner)).json()) == 2
