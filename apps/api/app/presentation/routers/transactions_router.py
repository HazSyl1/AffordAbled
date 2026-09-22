from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.application.dto import CreateTransactionInput, UpdateTransactionInput
from app.application.services.transaction_service import TransactionService
from app.core.dependencies import get_current_user, get_transaction_service
from app.domain.entities import User
from app.presentation.schemas.transaction import (
    CreateTransactionRequest,
    TransactionResponse,
    UpdateTransactionRequest,
)

router = APIRouter(prefix='/transactions', tags=['transactions'])


@router.post('', response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    payload: CreateTransactionRequest,
    current_user: User = Depends(get_current_user),
    transaction_service: TransactionService = Depends(get_transaction_service),
) -> TransactionResponse:
    transaction = await transaction_service.create_transaction(
        CreateTransactionInput(
            user_id=current_user.id,
            account_id=payload.account_id,
            type=payload.type,
            amount_paise=payload.amount_paise,
            occurred_at=payload.occurred_at,
            category_id=payload.category_id,
            to_account_id=payload.to_account_id,
            merchant=payload.merchant,
            note=payload.note,
        )
    )
    return TransactionResponse.from_entity(transaction)


@router.get('', response_model=list[TransactionResponse])
async def list_transactions(
    current_user: User = Depends(get_current_user),
    transaction_service: TransactionService = Depends(get_transaction_service),
) -> list[TransactionResponse]:
    transactions = await transaction_service.list_transactions(current_user.id)
    return [TransactionResponse.from_entity(transaction) for transaction in transactions]


@router.get('/{transaction_id}', response_model=TransactionResponse)
async def get_transaction(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    transaction_service: TransactionService = Depends(get_transaction_service),
) -> TransactionResponse:
    transaction = await transaction_service.get_transaction(current_user.id, transaction_id)
    return TransactionResponse.from_entity(transaction)


@router.patch('/{transaction_id}', response_model=TransactionResponse)
async def update_transaction(
    transaction_id: uuid.UUID,
    payload: UpdateTransactionRequest,
    current_user: User = Depends(get_current_user),
    transaction_service: TransactionService = Depends(get_transaction_service),
) -> TransactionResponse:
    transaction = await transaction_service.update_transaction(
        current_user.id,
        transaction_id,
        UpdateTransactionInput(
            account_id=payload.account_id,
            type=payload.type,
            amount_paise=payload.amount_paise,
            occurred_at=payload.occurred_at,
            category_id=payload.category_id,
            to_account_id=payload.to_account_id,
            merchant=payload.merchant,
            note=payload.note,
        ),
    )
    return TransactionResponse.from_entity(transaction)


@router.delete('/{transaction_id}', status_code=status.HTTP_204_NO_CONTENT)
async def soft_delete_transaction(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    transaction_service: TransactionService = Depends(get_transaction_service),
) -> None:
    await transaction_service.soft_delete_transaction(current_user.id, transaction_id)


@router.post('/{transaction_id}/restore', status_code=status.HTTP_204_NO_CONTENT)
async def restore_transaction(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    transaction_service: TransactionService = Depends(get_transaction_service),
) -> None:
    await transaction_service.restore_transaction(current_user.id, transaction_id)
