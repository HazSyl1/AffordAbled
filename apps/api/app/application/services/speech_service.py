from __future__ import annotations

from dataclasses import dataclass

from app.domain.exceptions import InvalidSpeechInputError
from app.domain.ports import AudioTranscoder, SpeechToTextClient

_MAX_AUDIO_BYTES = 10 * 1024 * 1024
_NATIVE_WAV_CONTENT_TYPES = {
    'audio/wav',
    'audio/x-wav',
    'audio/wave',
}
_TRANSCODABLE_AUDIO_CONTENT_TYPES = {
    'audio/ogg',
    'audio/webm',
    'audio/mp4',
    'audio/x-m4a',
    'audio/m4a',
}
_SUPPORTED_AUDIO_CONTENT_TYPES = _NATIVE_WAV_CONTENT_TYPES | _TRANSCODABLE_AUDIO_CONTENT_TYPES


@dataclass
class SpeechService:
    speech_to_text_client: SpeechToTextClient
    audio_transcoder: AudioTranscoder | None = None

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
                'Unsupported audio format. Use WAV (audio/wav), WEBM/Opus (audio/webm), or OGG/Opus (audio/ogg).'
            )

        speech_input_bytes = audio_bytes
        speech_content_type = normalized_content_type

        if normalized_content_type not in _NATIVE_WAV_CONTENT_TYPES:
            if self.audio_transcoder is None:
                raise InvalidSpeechInputError(
                    'Audio conversion service is unavailable. Install ffmpeg on the API server or upload WAV.'
                )

            speech_input_bytes = await self.audio_transcoder.to_wav(
                audio_bytes,
                source_content_type=normalized_content_type,
            )
            speech_content_type = 'audio/wav'

        return await self.speech_to_text_client.transcribe(
            speech_input_bytes,
            content_type=speech_content_type,
            locale=locale,
        )
