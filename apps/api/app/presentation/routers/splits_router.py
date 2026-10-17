from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.itemized_split import ItemAllocation, calculate_itemized_split
from app.application.services.split_service import ParticipantEditShare, ParticipantShare, SplitService
from app.application.services.transaction_service import TransactionService
from app.core.dependencies import get_current_user, get_db, get_transaction_service
from app.domain.entities import User
from app.domain.exceptions import TransactionNotFoundError
from app.infrastructure.database.repositories.sqlalchemy_split_repository import SqlAlchemySplitRepository
from app.presentation.schemas.split import (
    CreateSplitRequest,
    ItemizedSplitPreviewResponse,
    ItemizedSplitRequest,
    RepayParticipantRequest,
    SettleParticipantRequest,
    SplitContactPreferenceRequest,
    SplitContactPreferenceResponse,
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


@router.get('/contacts/preferences', response_model=list[SplitContactPreferenceResponse])
async def list_split_contact_preferences(
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> list[SplitContactPreferenceResponse]:
    return [SplitContactPreferenceResponse.model_validate(contact, from_attributes=True)
            for contact in await service.list_contact_preferences(current_user.id)]


@router.get('/contacts/preference-suggestions', response_model=list[dict])
async def list_split_contact_preference_suggestions(
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> list[dict]:
    return await service.contact_preference_suggestions(current_user.id)


@router.put('/contacts/preferences', response_model=SplitContactPreferenceResponse)
async def set_split_contact_preference(
    payload: SplitContactPreferenceRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> SplitContactPreferenceResponse:
    try:
        contact = await service.set_contact_preference(
            current_user.id, payload.name, payload.dietary_preference,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return SplitContactPreferenceResponse.model_validate(contact, from_attributes=True)


@router.delete('/contacts/preferences/{contact_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_split_contact_preference(
    contact_id: uuid.UUID,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> None:
    if not await service.delete_contact_preference(current_user.id, contact_id):
        raise HTTPException(status_code=404, detail='Split contact preference not found.')


async def _itemized_calculation(
    service: SplitService, transactions: TransactionService, user_id: uuid.UUID, payload: ItemizedSplitRequest,
):
    try:
        transaction = await transactions.get_transaction(user_id, payload.transaction_id)
    except TransactionNotFoundError as error:
        raise HTTPException(status_code=404, detail='Expense transaction was not found.') from error
    if transaction.type.value != 'expense' or transaction.amount_paise != payload.amount_paise:
        raise HTTPException(status_code=422, detail='Items must match the current expense amount.')
    contacts = await service.list_contact_preferences(user_id)
    preferences = {contact.normalized_name: contact.dietary_preference for contact in contacts}
    return calculate_itemized_split(
        payload.amount_paise,
        payload.participants,
        [ItemAllocation(item.name, item.amount_paise, item.shared_by, item.food_type) for item in payload.items],
        preferences,
    )


@router.post('/itemized/preview', response_model=ItemizedSplitPreviewResponse)
async def preview_itemized_split(
    payload: ItemizedSplitRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
    transactions: TransactionService = Depends(get_transaction_service),
) -> ItemizedSplitPreviewResponse:
    try:
        calculation = await _itemized_calculation(service, transactions, current_user.id, payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return ItemizedSplitPreviewResponse(**calculation.__dict__)


@router.post('/itemized', response_model=SplitResponse, status_code=status.HTTP_201_CREATED)
async def create_itemized_split(
    payload: ItemizedSplitRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
    transactions: TransactionService = Depends(get_transaction_service),
) -> SplitResponse:
    if not payload.confirmed:
        raise HTTPException(status_code=422, detail='Review and confirm the itemized split before saving.')
    try:
        calculation = await _itemized_calculation(service, transactions, current_user.id, payload)
        if calculation.warnings and not payload.approve_warnings:
            raise ValueError('Review the dietary preference warnings before saving.')
        split = await service.create(
            current_user.id, payload.transaction_id, payload.title, payload.amount_paise,
            'custom',
            [ParticipantShare(name, amount) for name, amount in calculation.participant_shares.items()],
            calculation.owner_share_paise,
            calculation.items,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return SplitResponse.from_model(split)


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


@router.post('/{split_id}/participants/{participant_id}/repay', response_model=SplitResponse)
async def repay_split_participant(
    split_id: uuid.UUID, participant_id: uuid.UUID, payload: RepayParticipantRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> SplitResponse:
    try:
        split = await service.repay(current_user.id, split_id, participant_id, payload.account_id)
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
