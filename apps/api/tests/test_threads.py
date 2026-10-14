from httpx import AsyncClient

from tests.helpers import auth_headers, register_and_get_token


async def test_threads_router_crud_and_ownership(client: AsyncClient) -> None:
    owner_token = await register_and_get_token(client, 'threads-owner@example.com')
    other_token = await register_and_get_token(client, 'threads-other@example.com')

    create_response = await client.post(
        '/api/v1/threads',
        json={'thread_id': 'budget-thread', 'title': 'Budget Discussion'},
        headers=auth_headers(owner_token),
    )
    assert create_response.status_code == 201
    assert create_response.json()['thread_id'] == 'budget-thread'

    duplicate_response = await client.post(
        '/api/v1/threads',
        json={'thread_id': 'budget-thread'},
        headers=auth_headers(owner_token),
    )
    assert duplicate_response.status_code == 409

    list_owner_response = await client.get('/api/v1/threads', headers=auth_headers(owner_token))
    assert list_owner_response.status_code == 200
    assert len(list_owner_response.json()) == 1

    detail_owner_response = await client.get('/api/v1/threads/budget-thread', headers=auth_headers(owner_token))
    assert detail_owner_response.status_code == 200
    assert detail_owner_response.json()['thread']['thread_id'] == 'budget-thread'
    assert detail_owner_response.json()['messages'] == []

    detail_other_response = await client.get('/api/v1/threads/budget-thread', headers=auth_headers(other_token))
    assert detail_other_response.status_code == 404

    delete_other_response = await client.delete('/api/v1/threads/budget-thread', headers=auth_headers(other_token))
    assert delete_other_response.status_code == 404

    delete_owner_response = await client.delete('/api/v1/threads/budget-thread', headers=auth_headers(owner_token))
    assert delete_owner_response.status_code == 204

    final_list_response = await client.get('/api/v1/threads', headers=auth_headers(owner_token))
    assert final_list_response.status_code == 200
    assert final_list_response.json() == []


async def test_chat_messages_are_persisted_in_thread_history(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'threads-chat-persistence@example.com')

    chat_response = await client.post(
        '/api/v1/chat',
        json={'message': 'show my transactions this week'},
        headers=auth_headers(token),
    )
    assert chat_response.status_code == 200

    thread_id = chat_response.json()['thread_id']
    detail_response = await client.get(f'/api/v1/threads/{thread_id}', headers=auth_headers(token))
    assert detail_response.status_code == 200

    payload = detail_response.json()
    assert payload['thread']['thread_id'] == thread_id
    assert payload['thread']['message_count'] >= 2
    roles = [message['role'] for message in payload['messages']]
    assert roles[0] == 'user'
    assert 'assistant' in roles
