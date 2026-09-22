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
