from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from app.application.services.chat_service import ChatService
from app.application.services.image_service import ImageService
from app.application.services.speech_service import SpeechService
from app.application.services.user_usage_service import CHAT_TURN, MEDIA_REQUEST, UsageLimitExceeded, UserUsageService
from app.core.dependencies import (
    get_chat_service,
    get_chat_turn_job_repository,
    get_current_user,
    get_image_service,
    get_speech_service,
    get_user_usage_service,
)
from app.domain.entities import User
from app.infrastructure.chat_turn_scheduler_signal import (
    publish_chat_turn_status,
    wait_for_chat_turn_status,
    wake_chat_turn_scheduler,
)
from app.infrastructure.database.models import ChatTurnJobModel
from app.infrastructure.database.repositories.sqlalchemy_chat_turn_job_repository import (
    ChatTurnConflictError,
    SqlAlchemyChatTurnJobRepository,
)
from app.presentation.schemas.chat import (
    ChatInsightResponse,
    ChatRequest,
    ChatResponse,
    ChatTurnStatusResponse,
    ChatTurnSubmitRequest,
    ImageAnalysisResponse,
    PendingTransactionProposalResponse,
    VoiceTranscriptionResponse,
)

router = APIRouter(prefix="/chat", tags=["chat"])


def _quota_http_error(error: UsageLimitExceeded) -> HTTPException:
    retry_after = max(0, int((error.reset_at - datetime.now(UTC)).total_seconds()))
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=error.detail(),
        headers={'Retry-After': str(retry_after)},
    )


async def _consume_media(usage_service: UserUsageService, user: User) -> None:
    try:
        await usage_service.consume(user.id, MEDIA_REQUEST, f'media:{uuid.uuid4()}', commit=True)
    except UsageLimitExceeded as exc:
        raise _quota_http_error(exc) from exc


def _turn_status_response(job: ChatTurnJobModel) -> ChatTurnStatusResponse:
    return ChatTurnStatusResponse(
        turn_id=job.id,
        thread_id=job.thread_id,
        status=job.status,
        result=ChatResponse.model_validate(job.result_json) if job.result_json else None,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        claimed_at=job.claimed_at,
        completed_at=job.completed_at,
    )


@router.post('/turns', response_model=ChatTurnStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_chat_turn(
    payload: ChatTurnSubmitRequest,
    current_user: User = Depends(get_current_user),
    repository: SqlAlchemyChatTurnJobRepository = Depends(get_chat_turn_job_repository),
    usage_service: UserUsageService = Depends(get_user_usage_service),
) -> ChatTurnStatusResponse:
    try:
        await usage_service.consume(
            current_user.id, CHAT_TURN, f'turn:{payload.turn_id}', commit=True,
        )
        job = await repository.create_or_get(
            turn_id=payload.turn_id,
            user_id=current_user.id,
            thread_id=payload.thread_id,
            message=payload.message.strip(),
            timezone=payload.timezone,
        )
    except ChatTurnConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except UsageLimitExceeded as exc:
        raise _quota_http_error(exc) from exc
    wake_chat_turn_scheduler()
    publish_chat_turn_status(str(job.id))
    return _turn_status_response(job)


@router.get('/turns/{turn_id}', response_model=ChatTurnStatusResponse)
async def get_chat_turn_status(
    turn_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    repository: SqlAlchemyChatTurnJobRepository = Depends(get_chat_turn_job_repository),
) -> ChatTurnStatusResponse:
    job = await repository.get_for_user(current_user.id, turn_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Chat turn not found')
    return _turn_status_response(job)


@router.get('/turns/{turn_id}/events', include_in_schema=False)
async def stream_chat_turn_status(
    turn_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    repository: SqlAlchemyChatTurnJobRepository = Depends(get_chat_turn_job_repository),
) -> StreamingResponse:
    """Authenticated status stream with DB rechecks for restart/process recovery."""
    async def events():
        last_payload = None
        while True:
            job = await repository.get_for_user_fresh(current_user.id, turn_id)
            if job is None:
                yield 'event: error\ndata: {"error":"not_found"}\n\n'
                return
            payload = _turn_status_response(job).model_dump(mode='json')
            serialized = json.dumps(payload, separators=(',', ':'))
            if serialized != last_payload:
                yield f'event: status\ndata: {serialized}\n\n'
                last_payload = serialized
            if job.status in {'succeeded', 'failed'}:
                return
            changed = await wait_for_chat_turn_status(str(turn_id), timeout_seconds=1)
            if not changed:
                yield ': keepalive\n\n'

    return StreamingResponse(
        events(), media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache, no-store', 'X-Accel-Buffering': 'no'},
    )


@router.post("", response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def send_chat_message(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
    usage_service: UserUsageService = Depends(get_user_usage_service),
) -> ChatResponse:
    turn_id = uuid.uuid4()
    try:
        await usage_service.consume(current_user.id, CHAT_TURN, f'turn:{turn_id}', commit=True)
        response = await chat_service.send_message(
            user_id=current_user.id,
            message=payload.message,
            thread_id=payload.thread_id,
            timezone=payload.timezone,
            turn_id=turn_id,
        )
    except UsageLimitExceeded as exc:
        raise _quota_http_error(exc) from exc
    proposal = response.pending_transaction_proposal
    proposals = response.pending_transaction_proposals or []
    return ChatResponse(
        thread_id=response.thread_id,
        message=response.message,
        tasks_completed=response.tasks_completed,
        show_completion_popup=response.show_completion_popup,
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
        pending_transaction_proposals=(
            [
                PendingTransactionProposalResponse(
                    type=item.type,
                    amount_paise=item.amount_paise,
                    occurred_at=item.occurred_at,
                    account_id=item.account_id,
                    account_name=item.account_name,
                    category_id=item.category_id,
                    category_name=item.category_name,
                    confidence_score=item.confidence_score,
                    merchant=item.merchant,
                    note=item.note,
                )
                for item in proposals
            ]
            or None
        ),
        transaction_logged=response.transaction_logged,
        created_transaction_id=response.created_transaction_id,
        created_split_ids=response.created_split_ids or [],
        manual_transaction_input_required=response.manual_transaction_input_required,
        insights=(
            [
                ChatInsightResponse(
                    title=str(item.get("title") or "").strip(),
                    detail=str(item.get("detail") or "").strip(),
                )
                for item in (response.insights or [])
                if str(item.get("title") or "").strip() and str(item.get("detail") or "").strip()
            ]
            or None
        ),
    )


@router.post(
    "/voice",
    response_model=VoiceTranscriptionResponse,
    status_code=status.HTTP_200_OK,
)
async def transcribe_voice(
    audio: UploadFile = File(...),
    locale: str = Form("en-IN"),
    speech_service: SpeechService = Depends(get_speech_service),
    current_user: User = Depends(get_current_user),
    usage_service: UserUsageService = Depends(get_user_usage_service),
) -> VoiceTranscriptionResponse:
    await _consume_media(usage_service, current_user)
    audio_bytes = await audio.read()
    content_type = audio.content_type or "application/octet-stream"

    transcript = await speech_service.transcribe_voice(audio_bytes, content_type=content_type, locale=locale)
    return VoiceTranscriptionResponse(transcript=transcript, locale=locale)


@router.post(
    "/image",
    response_model=ImageAnalysisResponse,
    status_code=status.HTTP_200_OK,
)
async def analyze_image(
    image: UploadFile = File(...),
    image_service: ImageService = Depends(get_image_service),
    current_user: User = Depends(get_current_user),
    usage_service: UserUsageService = Depends(get_user_usage_service),
) -> ImageAnalysisResponse:
    await _consume_media(usage_service, current_user)
    image_bytes = await image.read()
    content_type = image.content_type or "application/octet-stream"

    analysis = await image_service.analyze_image(
        image_bytes,
        content_type=content_type,
        filename=image.filename,
    )
    return ImageAnalysisResponse(extracted_text=analysis.extracted_text, prompt=analysis.prompt)
