from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.application.services.chat_service import ChatService
from app.application.services.speech_service import SpeechService
from app.core.dependencies import get_chat_service, get_current_user, get_speech_service
from app.domain.entities import User
from app.presentation.schemas.chat import (
    ChatRequest,
    ChatResponse,
    PendingTransactionProposalResponse,
    VoiceTranscriptionResponse,
)

router = APIRouter(prefix='/chat', tags=['chat'])


@router.post('', response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def send_chat_message(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    response = await chat_service.send_message(
        user_id=current_user.id,
        message=payload.message,
        thread_id=payload.thread_id,
    )
    proposal = response.pending_transaction_proposal
    return ChatResponse(
        thread_id=response.thread_id,
        message=response.message,
        pending_transaction_proposal=(
            PendingTransactionProposalResponse(
                type=proposal.type,
                amount_paise=proposal.amount_paise,
                occurred_at=proposal.occurred_at,
                account_id=proposal.account_id,
                account_name=proposal.account_name,
                category_id=proposal.category_id,
                category_name=proposal.category_name,
                confidence_score=proposal.confidence_score,
                merchant=proposal.merchant,
                note=proposal.note,
            )
            if proposal is not None
            else None
        ),
        transaction_logged=response.transaction_logged,
        manual_transaction_input_required=response.manual_transaction_input_required,
    )


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
