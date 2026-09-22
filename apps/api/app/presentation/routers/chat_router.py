from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.application.services.speech_service import SpeechService
from app.core.dependencies import get_current_user, get_speech_service
from app.presentation.schemas.chat import VoiceTranscriptionResponse

router = APIRouter(prefix='/chat', tags=['chat'])


@router.post(
    '/voice',
    response_model=VoiceTranscriptionResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(get_current_user)],
)
async def transcribe_voice(
    audio: UploadFile = File(...),
    locale: str = Form('en-IN'),
    speech_service: SpeechService = Depends(get_speech_service),
) -> VoiceTranscriptionResponse:
    audio_bytes = await audio.read()
    content_type = audio.content_type or 'application/octet-stream'

    transcript = await speech_service.transcribe_voice(audio_bytes, content_type=content_type, locale=locale)
    return VoiceTranscriptionResponse(transcript=transcript, locale=locale)
