from fastapi import FastAPI
from httpx import AsyncClient

from app.core.dependencies import get_speech_service
from tests.helpers import auth_headers, register_and_get_token


class StubSpeechService:
    async def transcribe_voice(self, audio_bytes: bytes, *, content_type: str, locale: str) -> str:
        del audio_bytes
        del content_type
        return f'Mocked transcript ({locale})'


async def test_chat_router_round_trip_persists_thread_state(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-thread-persistence@example.com')

    first_response = await client.post(
        '/api/v1/chat',
        json={'message': 'I want to review my monthly budget today'},
        headers=auth_headers(token),
    )

    assert first_response.status_code == 200
    first_payload = first_response.json()
    thread_id = first_payload['thread_id']
    assert thread_id

    second_response = await client.post(
        '/api/v1/chat',
        json={'message': 'What did I just tell you?', 'thread_id': thread_id},
        headers=auth_headers(token),
    )

    assert second_response.status_code == 200
    second_payload = second_response.json()
    assert second_payload['thread_id'] == thread_id
    assert 'I want to review my monthly budget today' in second_payload['message']


async def test_chat_router_isolates_thread_state_per_user(client: AsyncClient) -> None:
    first_user_token = await register_and_get_token(client, 'chat-isolation-a@example.com')
    second_user_token = await register_and_get_token(client, 'chat-isolation-b@example.com')

    first_user_response = await client.post(
        '/api/v1/chat',
        json={'message': 'Remember this secret phrase'},
        headers=auth_headers(first_user_token),
    )

    assert first_user_response.status_code == 200
    shared_thread_id = first_user_response.json()['thread_id']

    second_user_response = await client.post(
        '/api/v1/chat',
        json={'message': 'Do you remember anything?', 'thread_id': shared_thread_id},
        headers=auth_headers(second_user_token),
    )

    assert second_user_response.status_code == 200
    assert 'Earlier you mentioned' not in second_user_response.json()['message']


async def test_chat_router_blocks_off_topic_prompt(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-guardrail-block@example.com')

    response = await client.post(
        '/api/v1/chat',
        json={'message': 'Write a poem about my expenses'},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()['message'].startswith("I'm your finance assistant")


async def test_chat_router_allows_borderline_finance_prompt(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-guardrail-borderline@example.com')

    response = await client.post(
        '/api/v1/chat',
        json={'message': 'Can you check my budget?'},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()['message'].startswith('Got it.')


async def test_chat_voice_router_smoke(client: AsyncClient, app: FastAPI) -> None:
    token = await register_and_get_token(client, 'chat-voice-smoke@example.com')

    app.dependency_overrides[get_speech_service] = lambda: StubSpeechService()

    try:
        response = await client.post(
            '/api/v1/chat/voice',
            data={'locale': 'en-IN'},
            files={'audio': ('note.wav', b'audio-content', 'audio/wav')},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json() == {
            'transcript': 'Mocked transcript (en-IN)',
            'locale': 'en-IN',
        }
    finally:
        app.dependency_overrides.pop(get_speech_service, None)


async def test_chat_voice_rejects_non_audio_upload(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-voice-invalid-upload@example.com')

    response = await client.post(
        '/api/v1/chat/voice',
        files={'audio': ('note.txt', b'not-audio', 'text/plain')},
        headers=auth_headers(token),
    )

    assert response.status_code == 400
    assert response.json()['detail'] == 'Only audio uploads are supported'


async def test_chat_voice_rejects_unsupported_audio_format(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-voice-unsupported-format@example.com')

    response = await client.post(
        '/api/v1/chat/voice',
        files={'audio': ('recording.m4a', b'audio-content', 'audio/x-m4a')},
        headers=auth_headers(token),
    )

    assert response.status_code == 400
    assert response.json()['detail'] == 'Unsupported audio format. Use WAV (audio/wav) or OGG/Opus (audio/ogg).'


async def test_chat_transaction_proposal_confirm_flow(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-transaction-proposal@example.com')

    account_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Main Wallet', 'type': 'wallet', 'balance_paise': 100000, 'currency': 'INR'},
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
        json={'message': 'I spent INR 199.50 at Cafe Roma today'},
        headers=auth_headers(token),
    )

    assert proposal_response.status_code == 200
    proposal_payload = proposal_response.json()
    thread_id = proposal_payload['thread_id']
    assert "Reply 'confirm' to log" in proposal_payload['message']
    assert proposal_payload['pending_transaction_proposal'] is not None
    assert proposal_payload['pending_transaction_proposal']['confidence_score'] >= 0

    before_confirm = await client.get('/api/v1/transactions', headers=auth_headers(token))
    assert before_confirm.status_code == 200
    assert len(before_confirm.json()) == 0

    confirm_response = await client.post(
        '/api/v1/chat',
        json={'message': 'confirm', 'thread_id': thread_id},
        headers=auth_headers(token),
    )

    assert confirm_response.status_code == 200
    assert 'Logged transaction: expense INR 199.50' in confirm_response.json()['message']

    after_confirm = await client.get('/api/v1/transactions', headers=auth_headers(token))
    assert after_confirm.status_code == 200
    payload = after_confirm.json()
    assert len(payload) == 1
    assert payload[0]['amount_paise'] == 19950
    assert payload[0]['merchant'] == 'Cafe Roma'


async def test_chat_transaction_proposal_requires_account(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-transaction-needs-account@example.com')

    response = await client.post(
        '/api/v1/chat',
        json={'message': 'I spent INR 120 at Coffee House today'},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()['message'] == 'I can log this transaction, but please create an account first.'


async def test_chat_transaction_hitl_clarification_until_confident(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-transaction-hitl@example.com')

    account_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Main Wallet', 'type': 'wallet', 'balance_paise': 100000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert account_response.status_code == 201

    category_response = await client.post(
        '/api/v1/categories',
        json={'name': 'Food', 'type': 'expense'},
        headers=auth_headers(token),
    )
    assert category_response.status_code == 201

    first_turn = await client.post(
        '/api/v1/chat',
        json={'message': 'paid 1229'},
        headers=auth_headers(token),
    )

    assert first_turn.status_code == 200
    first_payload = first_turn.json()
    assert '(1/5)' in first_payload['message']
    assert first_payload['pending_transaction_proposal'] is None

    second_turn = await client.post(
        '/api/v1/chat',
        json={'message': 'at Axis yesterday', 'thread_id': first_payload['thread_id']},
        headers=auth_headers(token),
    )

    assert second_turn.status_code == 200
    second_payload = second_turn.json()
    assert second_payload['pending_transaction_proposal'] is not None
    assert second_payload['pending_transaction_proposal']['confidence_score'] >= 80


async def test_chat_transaction_hitl_falls_back_to_manual_after_max_turns(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-transaction-hitl-fallback@example.com')

    account_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Main Wallet', 'type': 'wallet', 'balance_paise': 100000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert account_response.status_code == 201

    category_response = await client.post(
        '/api/v1/categories',
        json={'name': 'Food', 'type': 'expense'},
        headers=auth_headers(token),
    )
    assert category_response.status_code == 201

    response = await client.post(
        '/api/v1/chat',
        json={'message': 'paid 1229'},
        headers=auth_headers(token),
    )
    assert response.status_code == 200

    payload = response.json()
    thread_id = payload['thread_id']

    for _ in range(5):
        response = await client.post(
            '/api/v1/chat',
            json={'message': 'not sure', 'thread_id': thread_id},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        payload = response.json()

    assert payload['manual_transaction_input_required'] is True
    assert payload['pending_transaction_proposal'] is not None
    assert payload['pending_transaction_proposal']['type'] == 'expense'
    assert payload['pending_transaction_proposal']['amount_paise'] == 122900



