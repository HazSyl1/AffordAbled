from __future__ import annotations

import pytest

from app.application.services.speech_service import SpeechService
from app.domain.exceptions import InvalidSpeechInputError


class StubSpeechToTextClient:
    def __init__(self) -> None:
        self.last_audio_bytes: bytes | None = None
        self.last_content_type: str | None = None
        self.last_locale: str | None = None

    async def transcribe(self, audio_bytes: bytes, *, content_type: str, locale: str) -> str:
        self.last_audio_bytes = audio_bytes
        self.last_content_type = content_type
        self.last_locale = locale
        return 'mock transcript'


class StubAudioTranscoder:
    def __init__(self, output_bytes: bytes = b'wav-audio') -> None:
        self.output_bytes = output_bytes
        self.last_source_content_type: str | None = None
        self.last_audio_bytes: bytes | None = None

    async def to_wav(self, audio_bytes: bytes, *, source_content_type: str) -> bytes:
        self.last_audio_bytes = audio_bytes
        self.last_source_content_type = source_content_type
        return self.output_bytes


@pytest.mark.asyncio
async def test_speech_service_passes_wav_directly_to_stt() -> None:
    speech_client = StubSpeechToTextClient()
    transcoder = StubAudioTranscoder()
    service = SpeechService(speech_to_text_client=speech_client, audio_transcoder=transcoder)

    transcript = await service.transcribe_voice(b'wav-bytes', content_type='audio/wav', locale='en-IN')

    assert transcript == 'mock transcript'
    assert speech_client.last_audio_bytes == b'wav-bytes'
    assert speech_client.last_content_type == 'audio/wav'
    assert transcoder.last_audio_bytes is None


@pytest.mark.asyncio
async def test_speech_service_transcodes_webm_to_wav_before_stt() -> None:
    speech_client = StubSpeechToTextClient()
    transcoder = StubAudioTranscoder(output_bytes=b'converted-wav')
    service = SpeechService(speech_to_text_client=speech_client, audio_transcoder=transcoder)

    transcript = await service.transcribe_voice(
        b'webm-bytes',
        content_type='audio/webm;codecs=opus',
        locale='en-IN',
    )

    assert transcript == 'mock transcript'
    assert transcoder.last_audio_bytes == b'webm-bytes'
    assert transcoder.last_source_content_type == 'audio/webm'
    assert speech_client.last_audio_bytes == b'converted-wav'
    assert speech_client.last_content_type == 'audio/wav'


@pytest.mark.asyncio
async def test_speech_service_rejects_unsupported_content_type() -> None:
    speech_client = StubSpeechToTextClient()
    transcoder = StubAudioTranscoder()
    service = SpeechService(speech_to_text_client=speech_client, audio_transcoder=transcoder)

    with pytest.raises(InvalidSpeechInputError, match='Unsupported audio format'):
        await service.transcribe_voice(
            b'flac-bytes',
            content_type='audio/flac',
            locale='en-IN',
        )


@pytest.mark.asyncio
async def test_speech_service_requires_transcoder_for_non_wav_audio() -> None:
    speech_client = StubSpeechToTextClient()
    service = SpeechService(speech_to_text_client=speech_client, audio_transcoder=None)

    with pytest.raises(InvalidSpeechInputError, match='Audio conversion service is unavailable'):
        await service.transcribe_voice(
            b'webm-bytes',
            content_type='audio/webm',
            locale='en-IN',
        )
