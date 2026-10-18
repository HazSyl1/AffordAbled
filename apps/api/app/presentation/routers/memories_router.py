from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.domain.entities import User
from app.infrastructure.database.repositories.sqlalchemy_memory_repository import SqlAlchemyMemoryRepository
from app.presentation.schemas.memory import (
    MemoryEventResponse,
    MemoryResponse,
    MemoryReviewEventRequest,
    MemoryUpdateRequest,
)

router = APIRouter(prefix='/memories', tags=['memories'])


def _response(memory) -> MemoryResponse:
    return MemoryResponse(
        id=memory.id, scope=memory.scope, subject_key=memory.subject_key,
        memory_type=memory.memory_type, value=memory.value_json,
        status=memory.status, confidence=memory.confidence,
        evidence_count=memory.evidence_count, created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


@router.get('', response_model=list[MemoryResponse])
async def list_memories(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> list[MemoryResponse]:
    rows = await SqlAlchemyMemoryRepository(db).list_for_user(current_user.id)
    return [_response(row) for row in rows]


@router.get('/suggestions', response_model=list[MemoryResponse])
async def list_memory_suggestions(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> list[MemoryResponse]:
    rows = await SqlAlchemyMemoryRepository(db).list_for_user(current_user.id, status='suggested')
    return [_response(row) for row in rows]


@router.post('/review-events', response_model=MemoryEventResponse, status_code=status.HTTP_201_CREATED)
async def record_review_event(
    payload: MemoryReviewEventRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> MemoryEventResponse:
    repository = SqlAlchemyMemoryRepository(db)
    event = await repository.add_review_event(
        user_id=current_user.id, action=payload.action, source=payload.source,
        before=payload.before, after=payload.after,
        transaction_id=payload.transaction_id, split_id=payload.split_id,
    )
    await db.commit()
    return MemoryEventResponse(id=event.id)


@router.post('/{memory_id}/confirm', response_model=MemoryResponse)
async def confirm_memory(
    memory_id: uuid.UUID,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    memory = await SqlAlchemyMemoryRepository(db).confirm(current_user.id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail='Memory suggestion was not found.')
    return _response(memory)


@router.patch('/{memory_id}', response_model=MemoryResponse)
async def update_memory(
    memory_id: uuid.UUID, payload: MemoryUpdateRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    memory = await SqlAlchemyMemoryRepository(db).update_value(current_user.id, memory_id, payload.value)
    if memory is None:
        raise HTTPException(status_code=404, detail='Memory suggestion was not found.')
    return _response(memory)


@router.post('/{memory_id}/dismiss', response_model=MemoryResponse)
async def dismiss_memory(
    memory_id: uuid.UUID,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    memory = await SqlAlchemyMemoryRepository(db).dismiss(current_user.id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail='Memory suggestion was not found.')
    return _response(memory)


@router.delete('/{memory_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> None:
    if not await SqlAlchemyMemoryRepository(db).delete(current_user.id, memory_id):
        raise HTTPException(status_code=404, detail='Memory was not found.')
