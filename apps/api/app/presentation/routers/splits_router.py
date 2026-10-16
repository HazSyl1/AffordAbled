from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.split_service import ParticipantEditShare, ParticipantShare, SplitService
from app.core.dependencies import get_current_user, get_db
from app.domain.entities import User
from app.infrastructure.database.repositories.sqlalchemy_split_repository import SqlAlchemySplitRepository
from app.presentation.schemas.split import (
    CreateSplitRequest,
    SettleParticipantRequest,
    SplitResponse,
    UpdateSplitRequest,
)

router = APIRouter(prefix='/splits', tags=['splits'])


def get_split_service(db: AsyncSession = Depends(get_db)) -> SplitService:
    return SplitService(SqlAlchemySplitRepository(db))


@router.get('', response_model=list[SplitResponse])
async def list_splits(
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> list[SplitResponse]:
    return [SplitResponse.from_model(split) for split in await service.list_for_user(current_user.id)]


@router.get('/contacts', response_model=list[str])
async def list_split_contacts(
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> list[str]:
    return await service.contact_names(current_user.id)


@router.post('', response_model=SplitResponse, status_code=status.HTTP_201_CREATED)
async def create_split(
    payload: CreateSplitRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> SplitResponse:
    try:
        split = await service.create(
            current_user.id, payload.transaction_id, payload.title, payload.amount_paise,
            payload.mode,
            [ParticipantShare(person.name, person.share_paise) for person in payload.participants],
            payload.owner_share_paise,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return SplitResponse.from_model(split)


@router.get('/{split_id}', response_model=SplitResponse)
async def get_split(
    split_id: uuid.UUID,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> SplitResponse:
    split = await service.get_for_user(current_user.id, split_id)
    if split is None:
        raise HTTPException(status_code=404, detail='Split not found.')
    return SplitResponse.from_model(split)


@router.patch('/{split_id}', response_model=SplitResponse)
async def update_split(
    split_id: uuid.UUID, payload: UpdateSplitRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> SplitResponse:
    try:
        split = await service.update(
            current_user.id, split_id, payload.title, payload.owner_share_paise,
            [ParticipantEditShare(person.id, person.name, person.share_paise) for person in payload.participants],
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if split is None:
        raise HTTPException(status_code=404, detail='Split not found.')
    return SplitResponse.from_model(split)


@router.post('/{split_id}/participants/{participant_id}/settle', response_model=SplitResponse)
async def settle_split_participant(
    split_id: uuid.UUID, participant_id: uuid.UUID,
    payload: SettleParticipantRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> SplitResponse:
    try:
        split = await service.settle(current_user.id, split_id, participant_id, payload.repayment_transaction_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if split is None:
        raise HTTPException(status_code=404, detail='Split participant not found.')
    return SplitResponse.from_model(split)


@router.delete('/{split_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_split(
    split_id: uuid.UUID,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> None:
    if not await service.delete(current_user.id, split_id):
        raise HTTPException(status_code=404, detail='Split not found.')
