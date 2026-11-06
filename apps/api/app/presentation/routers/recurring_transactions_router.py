from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.services.recurring_transaction_service import (
    CreateRecurringRuleInput,
    RecurringTransactionService,
)
from app.core.dependencies import get_current_user, get_recurring_transaction_service
from app.domain.entities import User
from app.presentation.schemas.recurring_transaction import (
    CreateRecurringTransactionRequest,
    CreateRecurringTransactionResponse,
    RecurringTransactionResponse,
    UpdateRecurringTransactionRequest,
)
from app.presentation.schemas.transaction import TransactionResponse

router = APIRouter(prefix='/recurring-transactions', tags=['recurring-transactions'])


def _not_found_or_bad_request(error: Exception) -> HTTPException:
    if isinstance(error, LookupError):
        return HTTPException(status_code=404, detail='Recurring transaction was not found.')
    return HTTPException(status_code=400, detail=str(error))


@router.post('', response_model=CreateRecurringTransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_recurring_transaction(
    payload: CreateRecurringTransactionRequest,
    current_user: User = Depends(get_current_user),
    service: RecurringTransactionService = Depends(get_recurring_transaction_service),
) -> CreateRecurringTransactionResponse:
    try:
        rule, transaction = await service.create_rule(CreateRecurringRuleInput(
            user_id=current_user.id, account_id=payload.account_id, category_id=payload.category_id,
            type=payload.type, amount_paise=payload.amount_paise, merchant=payload.merchant, note=payload.note,
            recurrence_unit=payload.recurrence_unit, interval_count=payload.interval_count,
            anchor_at=payload.anchor_at, timezone=payload.timezone, end_at=payload.end_at,
            max_occurrences=payload.max_occurrences,
            create_initial_transaction=payload.create_initial_transaction,
            source='memory' if payload.source_memory_id else 'manual', source_memory_id=payload.source_memory_id,
        ))
    except (ValueError, LookupError) as error:
        raise _not_found_or_bad_request(error) from error
    return CreateRecurringTransactionResponse(
        rule=RecurringTransactionResponse.from_entity(rule),
        initial_transaction=TransactionResponse.from_entity(transaction) if transaction else None,
    )


@router.get('', response_model=list[RecurringTransactionResponse])
async def list_recurring_transactions(
    current_user: User = Depends(get_current_user),
    service: RecurringTransactionService = Depends(get_recurring_transaction_service),
) -> list[RecurringTransactionResponse]:
    return [RecurringTransactionResponse.from_entity(rule) for rule in await service.list_rules(current_user.id)]


@router.get('/{rule_id}', response_model=RecurringTransactionResponse)
async def get_recurring_transaction(
    rule_id: uuid.UUID, current_user: User = Depends(get_current_user),
    service: RecurringTransactionService = Depends(get_recurring_transaction_service),
) -> RecurringTransactionResponse:
    try:
        return RecurringTransactionResponse.from_entity(await service.get_rule(current_user.id, rule_id))
    except LookupError as error:
        raise _not_found_or_bad_request(error) from error


@router.patch('/{rule_id}', response_model=RecurringTransactionResponse)
async def update_recurring_transaction(
    rule_id: uuid.UUID, payload: UpdateRecurringTransactionRequest,
    current_user: User = Depends(get_current_user),
    service: RecurringTransactionService = Depends(get_recurring_transaction_service),
) -> RecurringTransactionResponse:
    try:
        rule = await service.update_rule(current_user.id, rule_id, payload.model_dump(exclude_unset=True))
        return RecurringTransactionResponse.from_entity(rule)
    except (ValueError, LookupError) as error:
        raise _not_found_or_bad_request(error) from error


async def _transition(rule_id: uuid.UUID, user: User, service: RecurringTransactionService, action: str):
    try:
        rule = await getattr(service, action)(user.id, rule_id)
        return RecurringTransactionResponse.from_entity(rule)
    except (ValueError, LookupError) as error:
        raise _not_found_or_bad_request(error) from error


@router.post('/{rule_id}/pause', response_model=RecurringTransactionResponse)
async def pause_recurring_transaction(
    rule_id: uuid.UUID, current_user: User = Depends(get_current_user),
    service: RecurringTransactionService = Depends(get_recurring_transaction_service),
):
    return await _transition(rule_id, current_user, service, 'pause')


@router.post('/{rule_id}/resume', response_model=RecurringTransactionResponse)
async def resume_recurring_transaction(
    rule_id: uuid.UUID, current_user: User = Depends(get_current_user),
    service: RecurringTransactionService = Depends(get_recurring_transaction_service),
):
    return await _transition(rule_id, current_user, service, 'resume')


@router.delete('/{rule_id}', response_model=RecurringTransactionResponse)
async def cancel_recurring_transaction(
    rule_id: uuid.UUID, current_user: User = Depends(get_current_user),
    service: RecurringTransactionService = Depends(get_recurring_transaction_service),
):
    return await _transition(rule_id, current_user, service, 'cancel')
