import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.core.dependencies import (
    get_image_service,
    get_intent_classifier,
    get_semantic_guardrail,
    get_speech_service,
)
from app.domain.ports import DetectedIntent, GuardrailAssessment, GuardrailDecision
from app.infrastructure.ai.langgraph_chat_orchestrator import FinanceQueryPlan, LangGraphChatOrchestrator
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


class AllowGuardrail:
    async def assess(self, message: str) -> GuardrailAssessment:
        del message
        return GuardrailAssessment(decision=GuardrailDecision.ALLOW, confidence=1.0, layer='test')


class OffTopicIntentClassifier:
    async def classify(self, message: str) -> DetectedIntent:
        del message
        return DetectedIntent.OFF_TOPIC


class StubAsyncChain:
    def __init__(self, result):
        self.result = result
        self.last_input = None

    async def ainvoke(self, value):
        self.last_input = value
        return self.result


async def test_llm_selected_category_matches_catalog_without_literal_user_mention() -> None:
    orchestrator = object.__new__(LangGraphChatOrchestrator)
    orchestrator._llm_hitl_category_resolution_chain = None
    food_category = {'id': 'food-id', 'name': 'Food', 'type': 'expense'}
    categories = [
        food_category,
        {'id': 'games-id', 'name': 'Games', 'type': 'expense'},
        {'id': 'hotel-id', 'name': 'Hotel', 'type': 'expense'},
    ]

    resolved_category, suggested_name, refreshed_categories = await orchestrator._resolve_candidate_category(
        user_id=uuid.uuid4(),
        latest_user_message='Today I spent ₹500 on biryani dinner.',
        candidate={
            'type': 'expense',
            'selected_category': 'Food',
            'category': 'Food',
        },
        categories=categories,
    )

    assert resolved_category == food_category
    assert suggested_name == 'Food'
    assert refreshed_categories == categories

    unresolved_category, _, _ = await orchestrator._resolve_candidate_category(
        user_id=uuid.uuid4(),
        latest_user_message='not sure',
        candidate={
            'type': 'expense',
            'selected_category': 'Food',
            'category': 'Food',
        },
        categories=categories,
        hitl_active=True,
    )

    assert unresolved_category is None


def test_account_resolution_prefers_explicit_account_and_otherwise_uses_saved_default() -> None:
    accounts = [
        {
            'id': 'axis-id',
            'name': 'Axis Savings',
            'type': 'bank',
            'is_active': True,
            'is_default': True,
        },
        {
            'id': 'sbi-id',
            'name': 'SBI Savings',
            'type': 'bank',
            'is_active': True,
            'is_default': False,
        },
    ]

    selected_account, needs_clarification = LangGraphChatOrchestrator._resolve_candidate_account(
        candidate={'selected_account': 'SBI Savings', 'account_hint': 'SBI'},
        accounts=accounts,
        latest_user_message='Spent ₹5,000 on SBI',
        hitl_active=False,
    )
    assert selected_account == accounts[1]
    assert needs_clarification is False

    default_account, needs_clarification = LangGraphChatOrchestrator._resolve_candidate_account(
        candidate={'selected_account': None, 'account_hint': None},
        accounts=accounts,
        latest_user_message='Spent ₹5,000 on groceries',
        hitl_active=False,
    )
    assert default_account == accounts[0]
    assert needs_clarification is False


def test_account_resolution_asks_when_explicit_hint_is_ambiguous() -> None:
    accounts = [
        {
            'id': 'sbi-savings-id',
            'name': 'SBI Savings',
            'type': 'bank',
            'is_active': True,
            'is_default': True,
        },
        {
            'id': 'sbi-card-id',
            'name': 'SBI Card',
            'type': 'card',
            'is_active': True,
            'is_default': False,
        },
    ]

    selected_account, needs_clarification = LangGraphChatOrchestrator._resolve_candidate_account(
        candidate={'selected_account': 'SBI Savings', 'account_hint': 'SBI'},
        accounts=accounts,
        latest_user_message='Spent ₹5,000 on SBI',
        hitl_active=False,
    )
    assert selected_account is None
    assert needs_clarification is True


def test_account_catalog_passes_default_and_active_metadata_to_extractor() -> None:
    catalog = LangGraphChatOrchestrator._build_accounts_catalog_for_prompt(
        [
            {
                'id': 'axis-id',
                'name': 'Axis Savings',
                'type': 'bank',
                'is_active': True,
                'is_default': True,
            },
            {
                'id': 'closed-id',
                'name': 'Closed Account',
                'type': 'bank',
                'is_active': False,
                'is_default': False,
            },
        ]
    )

    assert 'Axis Savings' in catalog
    assert 'is_default' in catalog
    assert 'Closed Account' not in catalog


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


async def test_chat_router_restores_prior_messages_for_same_user_thread(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    token = await register_and_get_token(client, 'chat-same-thread-history@example.com')
    app.dependency_overrides[get_semantic_guardrail] = lambda: AllowGuardrail()
    app.dependency_overrides[get_intent_classifier] = lambda: OffTopicIntentClassifier()

    try:
        first_response = await client.post(
            '/api/v1/chat',
            json={'message': 'Remember this secret phrase'},
            headers=auth_headers(token),
        )
        assert first_response.status_code == 200
        thread_id = first_response.json()['thread_id']

        second_response = await client.post(
            '/api/v1/chat',
            json={'message': 'Tell me more', 'thread_id': thread_id},
            headers=auth_headers(token),
        )

        assert second_response.status_code == 200
        assert 'earlier you mentioned' in second_response.json()['message'].lower()
        assert 'remember this secret phrase' in second_response.json()['message'].lower()
    finally:
        app.dependency_overrides.pop(get_semantic_guardrail, None)
        app.dependency_overrides.pop(get_intent_classifier, None)


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
        json={'message': 'I spent INR 199.50 under Food at Cafe Roma today'},
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
        json={'name': 'Axis', 'type': 'bank', 'balance_paise': 100000, 'currency': 'INR'},
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
    assert second_payload['pending_transaction_proposal'] is None
    assert 'category' in second_payload['message'].lower()

    third_turn = await client.post(
        '/api/v1/chat',
        json={'message': 'under Food', 'thread_id': first_payload['thread_id']},
        headers=auth_headers(token),
    )

    assert third_turn.status_code == 200
    third_payload = third_turn.json()
    assert third_payload['pending_transaction_proposal'] is not None
    assert third_payload['pending_transaction_proposal']['confidence_score'] >= 80


async def test_chat_transaction_hitl_interrupt_message_wins_over_previous_ai_message(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-hitl-interrupt-message@example.com')

    account_response = await client.post(
        '/api/v1/accounts',
        json={'name': 'Main Wallet', 'type': 'wallet', 'balance_paise': 100000, 'currency': 'INR'},
        headers=auth_headers(token),
    )
    assert account_response.status_code == 201

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
    assert second_payload['pending_transaction_proposal']['category_name'].lower() == 'transport'

    categories_response = await client.get('/api/v1/categories', headers=auth_headers(token))
    assert categories_response.status_code == 200
    categories = categories_response.json()
    assert any(item['name'].lower() == 'transport' and item['type'] == 'expense' for item in categories)


async def test_chat_spend_query_routes_to_deterministic_query_tools_flow(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-spend-query@example.com')
    now = datetime.now(UTC)
    week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
    occurred_at_this_week = max(week_start, now - timedelta(days=1)).replace(microsecond=0).isoformat()

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
            'occurred_at': occurred_at_this_week,
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
    assert 'you spent' in payload['message'].lower()
    assert '85.00' in payload['message']
    assert '1 transaction' in payload['message'].lower()


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
    assert 'transaction' in payload['message'].lower()
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


async def test_chat_transaction_flow_does_not_default_single_category_without_explicit_hint(
    client: AsyncClient,
) -> None:
    token = await register_and_get_token(client, 'chat-no-default-single-category@example.com')

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
        json={'message': 'I spent INR 15000 at Amazon today on a new phone'},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    payload = response.json()
    pending_proposal = payload['pending_transaction_proposal']
    if pending_proposal is None:
        assert 'category' in payload['message'].lower()
        assert 'merchant' not in payload['message'].lower()
    else:
        assert pending_proposal['category_name'].lower() != 'food'


def test_fallback_query_plan_distinguishes_spending_total_from_bare_yesterday() -> None:
    summary_plan = LangGraphChatOrchestrator._fallback_query_plan('How much did I spend yesterday?')
    list_plan = LangGraphChatOrchestrator._fallback_query_plan('yesterday')

    assert summary_plan.query_kind == 'summary'
    assert summary_plan.date_period == 'yesterday'
    assert list_plan.query_kind == 'transaction_list'
    assert list_plan.date_period == 'yesterday'


def test_fallback_query_plan_extracts_multiple_requested_categories() -> None:
    plan = LangGraphChatOrchestrator._fallback_query_plan(
        'How much did I spend this week on food, travel and games?'
    )

    assert plan.query_kind == 'summary'
    assert plan.date_period == 'this_week'
    assert plan.category_names == ['food', 'travel', 'games']
    assert plan.category_scope == 'selected'


def test_fallback_query_plan_marks_unnamed_category_request_for_clarification() -> None:
    plan = LangGraphChatOrchestrator._fallback_query_plan('Show spending by category this week')

    assert plan.category_names == []
    assert plan.category_scope == 'unspecified'


def test_where_followup_reuses_previous_summary_period_as_expense_list() -> None:
    previous_plan = {
        'query_kind': 'summary',
        'date_period': 'this_month',
        'period_count': None,
        'category_names': [],
        'category_scope': 'all',
        'transaction_type': 'all',
        'confidence': 0.95,
    }

    plan = LangGraphChatOrchestrator._fallback_query_plan('where', previous_plan=previous_plan)

    assert plan.query_kind == 'transaction_list'
    assert plan.date_period == 'this_month'
    assert plan.category_scope == 'all'
    assert plan.transaction_type == 'expense'


def test_fallback_query_plan_selects_prior_result_table_formatting() -> None:
    previous_plan = FinanceQueryPlan(
        query_kind='transaction_list',
        date_period='this_month',
        confidence=0.9,
    ).model_dump()

    plan = LangGraphChatOrchestrator._fallback_query_plan(
        'sort these by date and show me in a table',
        previous_plan=previous_plan,
        previous_result={'query_kind': 'transaction_list', 'transactions': [{'id': 'tx-1'}]},
    )

    assert plan.action == 'format_previous'
    assert plan.result_format == 'table'
    assert plan.sort_order == 'newest_first'


def test_query_plan_router_sends_prior_result_format_to_formatter() -> None:
    plan = FinanceQueryPlan(
        action='format_previous',
        query_kind='transaction_list',
        date_period='this_month',
        result_format='table',
        confidence=0.99,
    ).model_dump()

    assert LangGraphChatOrchestrator._route_after_query_plan(
        {'query_plan': plan, 'last_finance_query_result': {'transactions': []}}
    ) == 'format_previous_result'


async def test_confident_llm_format_action_uses_structured_previous_result() -> None:
    orchestrator = object.__new__(LangGraphChatOrchestrator)
    llm_plan = FinanceQueryPlan(
        action='format_previous',
        query_kind='transaction_list',
        date_period='this_month',
        result_format='table',
        sort_order='newest_first',
        confidence=0.98,
    )
    planner_chain = StubAsyncChain(llm_plan)
    orchestrator._llm_query_plan_chain = planner_chain
    previous_result = {
        'query_kind': 'transaction_list',
        'transactions': [{'id': 'tx-1', 'date': '2026-10-14', 'amount': 'INR 100.00'}],
    }

    plan = await orchestrator._create_query_plan(
        'sort these by date and show me in a table',
        timezone_name='Asia/Kolkata',
        local_now='2026-10-14T12:00:00+05:30',
        conversation_context='Assistant: I found one transaction.',
        previous_result=previous_result,
    )

    assert plan.action == 'format_previous'
    assert plan.result_format == 'table'
    assert planner_chain.last_input['previous_query_result'] == json.dumps(previous_result, ensure_ascii=False)


def test_contextual_routing_message_includes_prior_finance_turn_and_latest_followup() -> None:
    messages = [
        HumanMessage(content='How much did I spend this month?'),
        AIMessage(content='You spent INR 19,675.00 this month across 7 transactions.'),
        HumanMessage(content='where'),
    ]

    contextual_message = LangGraphChatOrchestrator._conversation_aware_message(messages)

    assert 'You spent INR 19,675.00 this month' in contextual_message
    assert 'Current user message: where' in contextual_message


async def test_monthly_summary_where_followup_routes_to_monthly_expense_list() -> None:
    orchestrator = object.__new__(LangGraphChatOrchestrator)
    orchestrator._deterministic_transaction_first = False
    guardrail_chain = StubAsyncChain(
        GuardrailAssessment(decision=GuardrailDecision.ALLOW, confidence=0.9, layer='test')
    )
    intent_chain = StubAsyncChain(DetectedIntent.QUERY_SPENDING)
    orchestrator._guardrail_chain = guardrail_chain
    orchestrator._intent_chain = intent_chain
    orchestrator._llm_query_plan_chain = None
    previous_plan = FinanceQueryPlan(
        query_kind='summary',
        date_period='this_month',
        category_scope='all',
        confidence=0.9,
    ).model_dump()
    state = {
        'messages': [
            HumanMessage(content='How much did I spend this month?'),
            AIMessage(content='You spent INR 19,675.00 this month across 7 transactions.'),
            HumanMessage(content='where'),
        ],
        'runtime_timezone': 'Asia/Kolkata',
        'last_finance_query_plan': previous_plan,
    }

    analysis = await orchestrator._analyze_turn(state)
    plan_update = await orchestrator._query_planner_node(state)
    orchestrated = await orchestrator._query_orchestrator_node({**state, **plan_update})
    tool_call = orchestrated['messages'][0].tool_calls[0]

    assert analysis['workflow_action'] == 'query_transactions'
    assert 'You spent INR 19,675.00 this month' in guardrail_chain.last_input['message']
    assert 'You spent INR 19,675.00 this month' in intent_chain.last_input['message']
    assert tool_call['name'] == 'query_transactions'
    assert tool_call['args']['date_period'] == 'this_month'
    assert tool_call['args']['transaction_type'] == 'expense'
    assert tool_call['args']['timezone_name'] == 'Asia/Kolkata'


async def test_report_intent_with_prior_query_result_routes_to_contextual_planner() -> None:
    orchestrator = object.__new__(LangGraphChatOrchestrator)
    orchestrator._deterministic_transaction_first = False
    orchestrator._guardrail_chain = StubAsyncChain(
        GuardrailAssessment(decision=GuardrailDecision.ALLOW, confidence=0.9, layer='test')
    )
    orchestrator._intent_chain = StubAsyncChain(DetectedIntent.LOG_TRANSACTION)
    state = {
        'messages': [
            HumanMessage(content='Where did I spend this month?'),
            AIMessage(content='I found 2 transactions.'),
            HumanMessage(content='Sort these by date and show me in a table.'),
        ],
        'last_finance_query_result': {'query_kind': 'transaction_list', 'transactions': [{'id': 'tx-1'}]},
    }

    result = await orchestrator._analyze_turn(state)

    assert result['workflow_action'] == 'query_transactions'


async def test_monthly_summary_where_then_sort_table_uses_same_structured_transactions() -> None:
    orchestrator = object.__new__(LangGraphChatOrchestrator)
    orchestrator._deterministic_transaction_first = False
    orchestrator._llm_query_plan_chain = None
    orchestrator._llm_query_reply_chain = None
    orchestrator._guardrail_chain = StubAsyncChain(
        GuardrailAssessment(decision=GuardrailDecision.ALLOW, confidence=0.9, layer='test')
    )
    orchestrator._intent_chain = StubAsyncChain(DetectedIntent.QUERY_SPENDING)

    monthly_plan = FinanceQueryPlan(
        query_kind='summary',
        date_period='this_month',
        category_scope='all',
        confidence=0.95,
    ).model_dump()
    summary_facts = {
        'query_kind': 'spending_summary',
        'total_spent_paise': 30000,
        'total_spent_display': 'INR 300.00',
        'transaction_count': 2,
        'date_from': '2026-10-01',
        'date_to': '2026-10-14',
    }
    summary_state = {
        'messages': [
            ToolMessage(
                content=json.dumps({'reply': 'You spent INR 300.00 across 2 transactions.', 'facts': summary_facts}),
                tool_call_id='summary-call',
            )
        ],
        'query_tool_call_ids': ['summary-call'],
        'query_plan': monthly_plan,
    }
    summary_finalized = await orchestrator._query_tool_finalize(summary_state)
    assert summary_finalized['last_finance_query_result'] == summary_facts

    transaction_rows = [
        {
            'id': 'tx-new',
            'occurred_at': '2026-10-14T10:00:00+00:00',
            'date': '2026-10-14',
            'merchant': 'Shop Two',
            'amount': 'INR 200.00',
            'category': 'Food',
            'type': 'expense',
        },
        {
            'id': 'tx-old',
            'occurred_at': '2026-10-11T10:00:00+00:00',
            'date': '2026-10-11',
            'merchant': 'Cafe One',
            'amount': 'INR 100.00',
            'category': 'Food',
            'type': 'expense',
        },
    ]
    conversation = [
        HumanMessage(content='How much did I spend this month?'),
        summary_finalized['messages'][0],
        HumanMessage(content='where'),
    ]
    drilldown_state = {
        'messages': conversation,
        'runtime_timezone': 'Asia/Kolkata',
        'last_finance_query_plan': monthly_plan,
        'last_finance_query_result': summary_finalized['last_finance_query_result'],
    }
    orchestrator._intent_chain = StubAsyncChain(DetectedIntent.QUERY_SPENDING)
    drilldown_analysis = await orchestrator._analyze_turn(drilldown_state)
    drilldown_plan = await orchestrator._query_planner_node(drilldown_state)
    drilldown_tools = await orchestrator._query_orchestrator_node({**drilldown_state, **drilldown_plan})
    assert drilldown_analysis['workflow_action'] == 'query_transactions'
    assert drilldown_tools['messages'][0].tool_calls[0]['args']['date_period'] == 'this_month'
    assert drilldown_tools['messages'][0].tool_calls[0]['args']['transaction_type'] == 'expense'

    list_plan = drilldown_plan['query_plan']
    list_finalized = await orchestrator._query_tool_finalize(
        {
            'messages': [
                ToolMessage(
                    content=json.dumps(
                        {
                            'reply': 'I found 2 matching transactions.',
                            'facts': {
                                'query_kind': 'transaction_list',
                                'transaction_count': 2,
                                'date_from': '2026-10-01',
                                'date_to': '2026-10-14',
                                'transactions': transaction_rows,
                            },
                        }
                    ),
                    tool_call_id='list-call',
                )
            ],
            'query_tool_call_ids': ['list-call'],
            'query_plan': list_plan,
        }
    )
    assert list_finalized['last_finance_query_result']['transactions'] == transaction_rows

    conversation.extend(
        [list_finalized['messages'][0], HumanMessage(content='sort these by date and show me in a table')]
    )
    format_state = {
        'messages': conversation,
        'runtime_timezone': 'Asia/Kolkata',
        'last_finance_query_plan': list_plan,
        'last_finance_query_result': list_finalized['last_finance_query_result'],
    }
    orchestrator._intent_chain = StubAsyncChain(DetectedIntent.LOG_TRANSACTION)
    format_analysis = await orchestrator._analyze_turn(format_state)
    format_plan = await orchestrator._query_planner_node(format_state)
    assert format_analysis['workflow_action'] == 'query_transactions'
    assert format_plan['query_plan']['action'] == 'format_previous'
    assert (
        LangGraphChatOrchestrator._route_after_query_plan({**format_state, **format_plan}) == 'format_previous_result'
    )

    formatted = await orchestrator._format_previous_result_node({**format_state, **format_plan})
    table = formatted['messages'][0].content
    assert table.index('2026-10-14') < table.index('2026-10-11')
    assert 'Cafe One' in table and 'Shop Two' in table
    assert 'INR 100.00' in table and 'INR 200.00' in table
    assert table.count('\n| 20') == 2
    assert not formatted.get('tool_calls')


async def test_confident_llm_drilldown_plan_inherits_previous_query_scope() -> None:
    orchestrator = object.__new__(LangGraphChatOrchestrator)
    orchestrator._llm_query_plan_chain = StubAsyncChain(
        FinanceQueryPlan(
            action='drill_down',
            query_kind='transaction_list',
            date_period='recent_default',
            category_scope='all',
            confidence=0.98,
        )
    )
    previous_plan = FinanceQueryPlan(
        query_kind='summary',
        date_period='this_month',
        category_names=['Food'],
        category_scope='selected',
        confidence=0.95,
    ).model_dump()

    plan = await orchestrator._create_query_plan(
        'where',
        timezone_name='Asia/Kolkata',
        local_now='2026-10-14T12:00:00+05:30',
        conversation_context='User: How much did I spend this month on Food?',
        previous_plan=previous_plan,
    )

    assert plan.query_kind == 'transaction_list'
    assert plan.date_period == 'this_month'
    assert plan.category_names == ['Food']
    assert plan.category_scope == 'selected'
    assert plan.transaction_type == 'expense'


async def test_format_previous_result_node_sorts_and_preserves_rows() -> None:
    orchestrator = object.__new__(LangGraphChatOrchestrator)
    state = {
        'query_plan': FinanceQueryPlan(
            action='format_previous',
            query_kind='transaction_list',
            date_period='this_month',
            result_format='table',
            sort_order='oldest_first',
            confidence=0.99,
        ).model_dump(),
        'last_finance_query_result': {
            'query_kind': 'transaction_list',
            'transaction_count': 2,
            'transactions': [
                {
                    'id': 'tx-new',
                    'occurred_at': '2026-10-14T10:00:00+00:00',
                    'date': '2026-10-14',
                    'merchant': 'Shop | Two',
                    'amount': 'INR 200.00',
                    'category': 'Food',
                },
                {
                    'id': 'tx-old',
                    'occurred_at': '2026-10-11T10:00:00+00:00',
                    'date': '2026-10-11',
                    'merchant': 'Cafe One',
                    'amount': 'INR 100.00',
                    'category': 'Food',
                },
            ],
        },
    }

    result = await orchestrator._format_previous_result_node(state)
    content = result['messages'][0].content

    assert content.index('2026-10-11') < content.index('2026-10-14')
    assert r'Shop \| Two' in content
    assert 'INR 100.00' in content
    assert 'INR 200.00' in content


async def test_query_finalizer_saves_structured_transaction_result_for_followups() -> None:
    orchestrator = object.__new__(LangGraphChatOrchestrator)
    orchestrator._llm_query_reply_chain = None
    facts = {
        'query_kind': 'transaction_list',
        'transaction_count': 1,
        'transactions': [
            {
                'id': 'tx-1',
                'occurred_at': '2026-10-14T10:00:00+00:00',
                'date': '2026-10-14',
                'merchant': 'Cafe One',
                'amount': 'INR 100.00',
                'category': 'Food',
            }
        ],
    }
    tool_payload = json.dumps({'reply': 'One transaction.', 'facts': facts})
    state = {
        'messages': [ToolMessage(content=tool_payload, tool_call_id='tool-1')],
        'query_tool_call_ids': ['tool-1'],
        'query_plan': {'query_kind': 'transaction_list', 'date_period': 'this_month'},
    }

    result = await orchestrator._query_tool_finalize(state)

    assert result['last_finance_query_result'] == facts
    assert result['last_finance_query_plan'] == state['query_plan']


async def test_query_orchestrator_fans_out_one_tool_call_per_planned_category() -> None:
    orchestrator = object.__new__(LangGraphChatOrchestrator)
    state = {
        'messages': [HumanMessage(content='How much did I spend this week on Food and Travel?')],
        'runtime_timezone': 'Asia/Kolkata',
        'query_plan': FinanceQueryPlan(
            query_kind='summary',
            date_period='this_week',
            category_names=['Food', 'Travel'],
            confidence=0.98,
        ).model_dump(),
    }

    result = await orchestrator._query_orchestrator_node(state)
    tool_calls = result['messages'][0].tool_calls

    assert len(tool_calls) == 2
    assert [call['args']['category_hint'] for call in tool_calls] == ['Food', 'Travel']
    assert all(call['name'] == 'query_spending_summary' for call in tool_calls)
    assert all(call['args']['date_period'] == 'this_week' for call in tool_calls)
    assert all(call['args']['timezone_name'] == 'Asia/Kolkata' for call in tool_calls)
    assert result['query_tool_call_ids'] == [call['id'] for call in tool_calls]


async def test_query_orchestrator_asks_for_category_names_instead_of_querying_all() -> None:
    orchestrator = object.__new__(LangGraphChatOrchestrator)
    state = {
        'messages': [HumanMessage(content='Show spending by category this week')],
        'runtime_timezone': 'UTC',
        'query_plan': FinanceQueryPlan(
            query_kind='summary',
            date_period='this_week',
            category_scope='unspecified',
            confidence=0.98,
        ).model_dump(),
    }

    result = await orchestrator._query_orchestrator_node(state)

    assert result['query_tool_call_ids'] == []
    assert 'which expense categories' in result['messages'][0].content.lower()


def test_multiple_category_query_facts_merge_and_require_every_category_total() -> None:
    facts = LangGraphChatOrchestrator._combine_query_facts(
        [
            {
                'query_kind': 'spending_summary',
                'category': 'Food',
                'date_from': '2026-10-12',
                'date_to': '2026-10-14',
                'total_spent_paise': 20000,
                'total_spent_display': 'INR 200.00',
                'transaction_count': 2,
            },
            {
                'query_kind': 'spending_summary',
                'category': 'Travel',
                'date_from': '2026-10-12',
                'date_to': '2026-10-14',
                'total_spent_paise': 12500,
                'total_spent_display': 'INR 125.00',
                'transaction_count': 1,
            },
        ]
    )

    assert facts is not None
    assert facts['total_spent_display'] == 'INR 325.00'
    assert facts['transaction_count'] == 3
    valid_reply = (
        'Food was INR 200.00 and Travel was INR 125.00, for a total of INR 325.00 '
        'across 3 transactions this week.'
    )
    assert LangGraphChatOrchestrator._query_reply_preserves_facts(valid_reply, facts)
    assert not LangGraphChatOrchestrator._query_reply_preserves_facts(
        'Food was INR 200.00 and total spending was INR 325.00 across 3 transactions.',
        facts,
    )


def test_transaction_list_reply_must_preserve_each_merchant_date_and_amount() -> None:
    facts = {
        'query_kind': 'transaction_list',
        'transaction_count': 2,
        'transactions': [
            {'date': '2026-10-02', 'amount': 'INR 150.00', 'merchant': 'Cafe A'},
            {'date': '2026-10-08', 'amount': 'INR 250.00', 'merchant': 'Shop B'},
        ],
    }

    assert LangGraphChatOrchestrator._query_reply_preserves_facts(
        '2 transactions: Cafe A on 2026-10-02, INR 150.00; Shop B on 2026-10-08, INR 250.00.',
        facts,
    )
    assert LangGraphChatOrchestrator._query_reply_preserves_facts(
        '| Date | Merchant | Amount | Category |\n'
        '| --- | --- | ---: | --- |\n'
        '| 2026-10-02 | Cafe A | INR 150.00 | Food |\n'
        '| 2026-10-08 | Shop B | INR 250.00 | Food |\n'
        'These are 2 transactions.',
        facts,
    )
    assert not LangGraphChatOrchestrator._query_reply_preserves_facts(
        '2 transactions: Cafe A on 2026-10-02, INR 150.00.',
        facts,
    )


def test_generated_query_reply_must_preserve_computed_amount_count_and_category() -> None:
    facts = {
        'query_kind': 'spending_summary',
        'category': 'Food',
        'total_spent_display': 'INR 3,975.00',
        'transaction_count': 2,
    }

    assert LangGraphChatOrchestrator._query_reply_preserves_facts(
        'This week, Food spending was INR 3,975.00 across 2 transactions.',
        facts,
    )
    assert not LangGraphChatOrchestrator._query_reply_preserves_facts(
        'This week, Food spending was about INR 4,000 across 2 transactions.',
        facts,
    )


async def test_chat_transaction_flow_accepts_relative_date_phrase_without_repeating_date_prompt(
    client: AsyncClient,
) -> None:
    token = await register_and_get_token(client, 'chat-relative-date-phrase@example.com')

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
        json={'message': 'Spend INR 4001 at hotel in delhi 2 days ago'},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    payload = response.json()
    assert 'please confirm when this happened' not in payload['message'].lower()
    assert 'category' in payload['message'].lower()


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
        json={'message': 'I spent INR 199.50 under Food at Cafe Roma today'},
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



