from __future__ import annotations

import logging

import httpx

from app.core.config import Settings
from app.domain.exceptions import InvalidSpeechInputError, SpeechServiceNotConfiguredError, SpeechTranscriptionError

logger = logging.getLogger(__name__)


class AzureSpeechToTextClient:
    def __init__(self, settings: Settings) -> None:
        self._speech_key = settings.azure_speech_key
        self._speech_region = settings.azure_speech_region

    async def transcribe(self, audio_bytes: bytes, *, content_type: str, locale: str) -> str:
        if not self._speech_key or not self._speech_region:
            raise SpeechServiceNotConfiguredError('Azure speech credentials are not configured')

        endpoint = (
            f'https://{self._speech_region}.stt.speech.microsoft.com/'
            'speech/recognition/conversation/cognitiveservices/v1'
        )

        headers = {
            'Ocp-Apim-Subscription-Key': self._speech_key,
            'Content-Type': content_type,
        }
        params = {'language': locale, 'format': 'simple'}

        logger.info(
            'speech.transcription.request',
            extra={
                'provider': 'azure_speech',
                'content_type': content_type,
                'locale': locale,
                'audio_size_bytes': len(audio_bytes),
            },
        )

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(endpoint, params=params, headers=headers, content=audio_bytes)

        logger.info(
            'speech.transcription.response',
            extra={
                'provider': 'azure_speech',
                'status_code': response.status_code,
                'content_type': content_type,
                'locale': locale,
            },
        )

        if response.status_code == 400:
            raise InvalidSpeechInputError('Speech not recognized. Upload clear speech and try again.')

        if response.status_code != 200:
            raise SpeechTranscriptionError('Speech transcription request failed')

        payload = response.json()
        recognition_status = str(payload.get('RecognitionStatus') or '').strip()
        transcript = str(payload.get('DisplayText') or '').strip()
        if not transcript:
            if recognition_status and recognition_status.lower() != 'success':
                raise InvalidSpeechInputError(
                    f'Speech not recognized ({recognition_status}). Upload clear speech and try again.'
                )
            raise InvalidSpeechInputError(
                'Speech not recognized. Please record clear speech (1-15 seconds) and try again.'
            )

        return transcript
