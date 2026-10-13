from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.application.dto import CreateChatThreadInput
from app.application.services.thread_service import ThreadService
from app.core.dependencies import get_current_user, get_thread_service
from app.domain.entities import User
from app.presentation.schemas.thread import (
    CreateThreadRequest,
    ThreadDetailResponse,
    ThreadMessageResponse,
    ThreadResponse,
)

router = APIRouter(prefix='/threads', tags=['threads'])


@router.post('', response_model=ThreadResponse, status_code=status.HTTP_201_CREATED)
async def create_thread(
    payload: CreateThreadRequest,
    current_user: User = Depends(get_current_user),
    thread_service: ThreadService = Depends(get_thread_service),
) -> ThreadResponse:
    thread = await thread_service.create_thread(
        CreateChatThreadInput(user_id=current_user.id, thread_id=payload.thread_id, title=payload.title)
    )
    return ThreadResponse.from_entity(thread)


@router.get('', response_model=list[ThreadResponse])
async def list_threads(
    current_user: User = Depends(get_current_user),
    thread_service: ThreadService = Depends(get_thread_service),
) -> list[ThreadResponse]:
    threads = await thread_service.list_threads(current_user.id)
    return [ThreadResponse.from_entity(thread) for thread in threads]


@router.get('/{thread_id}', response_model=ThreadDetailResponse)
async def get_thread(
    thread_id: str,
    current_user: User = Depends(get_current_user),
    thread_service: ThreadService = Depends(get_thread_service),
) -> ThreadDetailResponse:
    detail = await thread_service.get_thread(current_user.id, thread_id)
    messages = [ThreadMessageResponse.from_entity(message) for message in detail.messages]
    return ThreadDetailResponse(
        thread=ThreadResponse.from_entity(detail.thread, message_count=len(messages)),
        messages=messages,
    )


@router.delete('/{thread_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: str,
    current_user: User = Depends(get_current_user),
    thread_service: ThreadService = Depends(get_thread_service),
) -> None:
    await thread_service.delete_thread(current_user.id, thread_id)
