from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from httpx import AsyncClient

from app.core.dependencies import get_image_service, get_speech_service
from tests.helpers import auth_headers, register_and_get_token


class StubSpeechService:
    async def transcribe_voice(self, audio_bytes: bytes, *, content_type: str, locale: str) -> str:
        del audio_bytes
        del content_type
        return f'Mocked transcript ({locale})'


class StubImageService:
    async def analyze_image(self, image_bytes: bytes, *, content_type: str, filename: str | None):
        del image_bytes
        del content_type
        safe_filename = filename or 'upload'
        return type(
            'ImageAnalysis',
            (),
            {
                'extracted_text': f'Mocked OCR from {safe_filename}',
                'prompt': f'Prompt built from {safe_filename}',
            },
        )()


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
        files={'audio': ('recording.flac', b'audio-content', 'audio/flac')},
        headers=auth_headers(token),
    )

    assert response.status_code == 400
    assert (
        response.json()['detail']
        == 'Unsupported audio format. Use WAV (audio/wav), WEBM/Opus (audio/webm), or OGG/Opus (audio/ogg).'
    )


async def test_chat_image_router_smoke(client: AsyncClient, app: FastAPI) -> None:
    token = await register_and_get_token(client, 'chat-image-smoke@example.com')

    app.dependency_overrides[get_image_service] = lambda: StubImageService()

    try:
        response = await client.post(
            '/api/v1/chat/image',
            files={'image': ('bill.png', b'image-content', 'image/png')},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json() == {
            'extracted_text': 'Mocked OCR from bill.png',
            'prompt': 'Prompt built from bill.png',
        }
    finally:
        app.dependency_overrides.pop(get_image_service, None)


async def test_chat_image_rejects_non_image_upload(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-image-invalid-upload@example.com')

    response = await client.post(
        '/api/v1/chat/image',
        files={'image': ('note.txt', b'not-image', 'text/plain')},
        headers=auth_headers(token),
    )

    assert response.status_code == 400
    assert response.json()['detail'] == 'Only image uploads are supported'


async def test_chat_image_rejects_unsupported_image_format(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-image-unsupported-format@example.com')

    response = await client.post(
        '/api/v1/chat/image',
        files={'image': ('receipt.gif', b'image-content', 'image/gif')},
        headers=auth_headers(token),
    )

    assert response.status_code == 400
    assert response.json()['detail'] == 'Unsupported image format. Use JPG, PNG, or WEBP.'


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


async def test_chat_transaction_hitl_interrupt_message_wins_over_previous_ai_message(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-hitl-interrupt-message@example.com')

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
        json={'message': 'hi'},
        headers=auth_headers(token),
    )
    assert first_turn.status_code == 200
    thread_id = first_turn.json()['thread_id']

    second_turn = await client.post(
        '/api/v1/chat',
        json={'message': 'spent 5003 on dinner', 'thread_id': thread_id},
        headers=auth_headers(token),
    )

    assert second_turn.status_code == 200
    second_payload = second_turn.json()
    assert '(1/5)' in second_payload['message']
    assert second_payload['pending_transaction_proposal'] is None


async def test_chat_transaction_flow_handles_spend_verb(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-spend-verb@example.com')

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
        json={'message': 'Spend 1000'},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    payload = response.json()
    assert '(1/5)' in payload['message']
    assert payload['pending_transaction_proposal'] is None


async def test_chat_transaction_flow_allows_creating_category_via_hitl(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-create-category-hitl@example.com')

    account_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Main Wallet', 'type': 'wallet', 'balance_paise': 100000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert account_response.status_code == 201

    proposal_response = await client.post(
        '/api/v1/chat',
        json={'message': 'I spent INR 500 yesterday at Cafe Roma'},
        headers=auth_headers(token),
    )

    assert proposal_response.status_code == 200
    proposal_payload = proposal_response.json()
    assert proposal_payload['pending_transaction_proposal'] is None
    assert 'category' in proposal_payload['message'].lower()

    create_category_response = await client.post(
        '/api/v1/chat',
        json={'message': 'create Food', 'thread_id': proposal_payload['thread_id']},
        headers=auth_headers(token),
    )

    assert create_category_response.status_code == 200
    create_category_payload = create_category_response.json()
    assert create_category_payload['pending_transaction_proposal'] is not None
    assert create_category_payload['pending_transaction_proposal']['category_name'] == 'Food'

    categories_response = await client.get('/api/v1/categories', headers=auth_headers(token))
    assert categories_response.status_code == 200
    categories = categories_response.json()
    assert any(item['name'] == 'Food' and item['type'] == 'expense' for item in categories)


async def test_chat_transaction_flow_accepts_yes_plus_suggested_category_in_hitl(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-hitl-yes-suggested-category@example.com')

    account_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Main Wallet', 'type': 'wallet', 'balance_paise': 100000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert account_response.status_code == 201

    first_category_response = await client.post(
        '/api/v1/categories',
        json={'name': 'Food', 'type': 'expense'},
        headers=auth_headers(token),
    )
    assert first_category_response.status_code == 201

    second_category_response = await client.post(
        '/api/v1/categories',
        json={'name': 'Games', 'type': 'expense'},
        headers=auth_headers(token),
    )
    assert second_category_response.status_code == 201

    first_turn = await client.post(
        '/api/v1/chat',
        json={'message': 'I spent INR 256 yesterday at Uber under Transport'},
        headers=auth_headers(token),
    )
    assert first_turn.status_code == 200
    first_payload = first_turn.json()
    assert first_payload['pending_transaction_proposal'] is None
    assert 'create transport' in first_payload['message'].lower()

    second_turn = await client.post(
        '/api/v1/chat',
        json={'message': 'yes transport', 'thread_id': first_payload['thread_id']},
        headers=auth_headers(token),
    )
    assert second_turn.status_code == 200

    second_payload = second_turn.json()
    assert second_payload['pending_transaction_proposal'] is not None
    assert second_payload['pending_transaction_proposal']['category_name'] == 'Transport'

    categories_response = await client.get('/api/v1/categories', headers=auth_headers(token))
    assert categories_response.status_code == 200
    categories = categories_response.json()
    assert any(item['name'] == 'Transport' and item['type'] == 'expense' for item in categories)


async def test_chat_spend_query_routes_to_deterministic_query_tools_flow(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-spend-query@example.com')

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

    create_transaction_response = await client.post(
        '/api/v1/transactions',
        json={
            'account_id': account_response.json()['id'],
            'type': 'expense',
            'amount_paise': 8500,
            'occurred_at': '2026-09-28T10:00:00+00:00',
            'category_id': category_response.json()['id'],
            'merchant': 'Zomato',
            'note': 'Lunch',
        },
        headers=auth_headers(token),
    )
    assert create_transaction_response.status_code == 201

    response = await client.post(
        '/api/v1/chat',
        json={'message': 'What did I spend this week?'},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['pending_transaction_proposal'] is None
    assert '(1/5)' not in payload['message']
    assert 'you spent inr' in payload['message'].lower()
    assert isinstance(payload.get('insights'), list)
    assert len(payload['insights']) >= 1
    assert payload['insights'][0]['title']


async def test_chat_query_transactions_for_last_two_weeks(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-query-last-two-weeks@example.com')
    recent_occurred_at = (datetime.now(UTC) - timedelta(days=3)).replace(microsecond=0).isoformat()

    account_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Travel Wallet', 'type': 'wallet', 'balance_paise': 150000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert account_response.status_code == 201

    category_response = await client.post(
        '/api/v1/categories',
        json={'name': 'Travel', 'type': 'expense'},
        headers=auth_headers(token),
    )
    assert category_response.status_code == 201

    transaction_response = await client.post(
        '/api/v1/transactions',
        json={
            'account_id': account_response.json()['id'],
            'type': 'expense',
            'amount_paise': 25600,
            'occurred_at': recent_occurred_at,
            'category_id': category_response.json()['id'],
            'merchant': 'Uber',
            'note': 'Ride',
        },
        headers=auth_headers(token),
    )
    assert transaction_response.status_code == 201

    response = await client.post(
        '/api/v1/chat',
        json={'message': 'show my transactions from 2 weeks ago'},
        headers=auth_headers(token),
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload['pending_transaction_proposal'] is None
    assert 'i found' in payload['message'].lower()
    assert 'uber' in payload['message'].lower()


async def test_chat_transaction_flow_uses_category_hint_from_message(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-category-hint@example.com')

    account_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Main Wallet', 'type': 'wallet', 'balance_paise': 100000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert account_response.status_code == 201

    travel_category_response = await client.post(
        '/api/v1/categories',
        json={'name': 'Travel', 'type': 'expense'},
        headers=auth_headers(token),
    )
    assert travel_category_response.status_code == 201

    food_category_response = await client.post(
        '/api/v1/categories',
        json={'name': 'Food', 'type': 'expense'},
        headers=auth_headers(token),
    )
    assert food_category_response.status_code == 201

    response = await client.post(
        '/api/v1/chat',
        json={'message': 'I spent INR 450 under Food at Cafe Roma today'},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['pending_transaction_proposal'] is not None
    assert payload['pending_transaction_proposal']['category_name'] == 'Food'


async def test_chat_transaction_yes_confirms_pending_proposal(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-yes-confirm@example.com')

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
    assert proposal_payload['pending_transaction_proposal'] is not None

    confirm_response = await client.post(
        '/api/v1/chat',
        json={'message': 'yes', 'thread_id': proposal_payload['thread_id']},
        headers=auth_headers(token),
    )

    assert confirm_response.status_code == 200
    assert 'Logged transaction: expense INR 199.50' in confirm_response.json()['message']


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



