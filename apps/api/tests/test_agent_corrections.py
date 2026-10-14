from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AgentCorrectionModel
from tests.helpers import auth_headers, register_and_get_token


async def test_chat_edit_persists_agent_correction(client: AsyncClient, db_session: AsyncSession) -> None:
    token = await register_and_get_token(client, 'chat-agent-correction@example.com')

    account_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Main Wallet', 'type': 'wallet', 'balance_paise': 200000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert account_response.status_code == 201

    category_response = await client.post(
        '/api/v1/categories',
        json={'name': 'Food', 'type': 'expense'},
        headers=auth_headers(token),
    )
    assert category_response.status_code == 201

    proposal_response = await client.post(
        '/api/v1/chat',
        json={'message': 'I spent INR 450 on Food at Cafe Roma today'},
        headers=auth_headers(token),
    )
    assert proposal_response.status_code == 200
    proposal_payload = proposal_response.json()
    assert proposal_payload['pending_transaction_proposal'] is not None

    edit_response = await client.post(
        '/api/v1/chat',
        json={'message': 'make it INR 500', 'thread_id': proposal_payload['thread_id']},
        headers=auth_headers(token),
    )
    assert edit_response.status_code == 200
    edit_payload = edit_response.json()
    assert edit_payload['pending_transaction_proposal'] is not None
    assert edit_payload['pending_transaction_proposal']['amount_paise'] == 50000

    result = await db_session.execute(select(AgentCorrectionModel))
    corrections = result.scalars().all()

    assert len(corrections) == 1
    correction = corrections[0]
    assert correction.thread_id == proposal_payload['thread_id']
    assert correction.user_message == 'make it INR 500'
    assert correction.original_proposal['amount_paise'] == 45000
    assert correction.corrected_proposal['amount_paise'] == 50000
