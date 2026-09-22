from __future__ import annotations

import httpx

from app.core.config import Settings
from app.domain.exceptions import InvalidSpeechInputError, SpeechServiceNotConfiguredError, SpeechTranscriptionError


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

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(endpoint, params=params, headers=headers, content=audio_bytes)

        if response.status_code == 400:
            raise InvalidSpeechInputError('Speech not recognized. Upload clear speech in WAV/OGG format.')

        if response.status_code != 200:
            raise SpeechTranscriptionError('Speech transcription request failed')

        payload = response.json()
        recognition_status = str(payload.get('RecognitionStatus') or '').strip()
        transcript = str(payload.get('DisplayText') or '').strip()
        if not transcript:
            if recognition_status and recognition_status.lower() != 'success':
                raise InvalidSpeechInputError(
                    f'Speech not recognized ({recognition_status}). Upload clear speech in WAV/OGG format.'
                )
            raise SpeechTranscriptionError('Speech transcription returned empty text')

        return transcript
