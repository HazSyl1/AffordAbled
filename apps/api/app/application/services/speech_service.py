from __future__ import annotations

from dataclasses import dataclass

from app.domain.exceptions import InvalidSpeechInputError
from app.domain.ports import SpeechToTextClient

_MAX_AUDIO_BYTES = 10 * 1024 * 1024
_SUPPORTED_AUDIO_CONTENT_TYPES = {
    'audio/wav',
    'audio/x-wav',
    'audio/wave',
    'audio/ogg',
}


@dataclass
class SpeechService:
    speech_to_text_client: SpeechToTextClient

    async def transcribe_voice(self, audio_bytes: bytes, *, content_type: str, locale: str) -> str:
        if not audio_bytes:
            raise InvalidSpeechInputError('Audio file is empty')

        if len(audio_bytes) > _MAX_AUDIO_BYTES:
            raise InvalidSpeechInputError('Audio file exceeds 10MB limit')

        if not content_type.startswith('audio/'):
            raise InvalidSpeechInputError('Only audio uploads are supported')

        normalized_content_type = content_type.split(';', maxsplit=1)[0].strip().lower()
        if normalized_content_type not in _SUPPORTED_AUDIO_CONTENT_TYPES:
            raise InvalidSpeechInputError(
                'Unsupported audio format. Use WAV (audio/wav) or OGG/Opus (audio/ogg).'
            )

        return await self.speech_to_text_client.transcribe(audio_bytes, content_type=content_type, locale=locale)
