from fastapi import FastAPI
from httpx import AsyncClient

from app.core.dependencies import get_speech_service
from tests.helpers import auth_headers, register_and_get_token


class StubSpeechService:
    async def transcribe_voice(self, audio_bytes: bytes, *, content_type: str, locale: str) -> str:
        del audio_bytes
        del content_type
        return f'Mocked transcript ({locale})'


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


async def test_chat_router_round_trip_persists_thread_state(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'chat-thread-persistence@example.com')

    first_response = await client.post(
        '/api/v1/chat',
        json={'message': 'I paid rent today'},
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
    assert 'I paid rent today' in second_payload['message']


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
