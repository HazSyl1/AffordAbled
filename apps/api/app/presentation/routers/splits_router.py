from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.itemized_split import ItemAllocation, calculate_itemized_split
from app.application.services.split_notification_service import SplitNotificationError, SplitNotificationService
from app.application.services.split_service import ParticipantEditShare, ParticipantShare, SplitService
from app.application.services.transaction_service import TransactionService
from app.core.config import Settings
from app.core.dependencies import get_current_user, get_db, get_settings_dependency, get_transaction_service
from app.domain.entities import User
from app.domain.exceptions import TransactionNotFoundError
from app.infrastructure.database.repositories.sqlalchemy_memory_repository import SqlAlchemyMemoryRepository
from app.infrastructure.database.repositories.sqlalchemy_split_notification_repository import (
    SqlAlchemySplitNotificationRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_split_repository import SqlAlchemySplitRepository
from app.infrastructure.sms_scheduler_signal import wake_sms_scheduler
from app.presentation.schemas.split import (
    CreateOwedRequest,
    CreateSplitRequest,
    ItemizedSplitPreviewResponse,
    ItemizedSplitRequest,
    PayOwedRequest,
    RecordSplitPaymentRequest,
    RenameSplitRequest,
    RepayParticipantRequest,
    RepaySettlementTransferRequest,
    SettleBalanceRequest,
    SettleParticipantRequest,
    SplitContactDetailsRequest,
    SplitContactDetailsResponse,
    SplitContactPreferenceRequest,
    SplitContactPreferenceResponse,
    SplitNotificationBatchQueueResponse,
    SplitNotificationBatchRequest,
    SplitNotificationQueueResponse,
    SplitNotificationSkippedRecipientResponse,
    SplitNotificationSplitStatusResponse,
    SplitResponse,
    UpdateSplitRequest,
)

router = APIRouter(prefix='/splits', tags=['splits'])


def get_split_service(db: AsyncSession = Depends(get_db)) -> SplitService:
    return SplitService(SqlAlchemySplitRepository(db), SqlAlchemyMemoryRepository(db))


def get_split_notification_service(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings_dependency),
) -> SplitNotificationService:
    email_configured = bool(settings.email_enabled and settings.acs_connection_string and settings.email_sender_address)
    sms_configured = bool(settings.sms_enabled and settings.acs_connection_string and settings.acs_sender_number)
    configured = email_configured or sms_configured
    return SplitNotificationService(
        repository=SqlAlchemySplitNotificationRepository(db), enabled=configured,
        provider_name=settings.email_provider if email_configured else settings.sms_provider,
        cooldown_hours=max(1, settings.notification_cooldown_hours),
        max_per_split=max(1, settings.max_notifications_per_split),
        max_per_user_daily=max(1, settings.max_sms_per_user_per_day),
        channel='email' if email_configured else 'sms',
    )


def _notification_http_error(error: SplitNotificationError) -> HTTPException:
    detail = {'code': error.code, 'message': error.message}
    if error.retry_after_seconds is not None:
        detail['retry_after_seconds'] = error.retry_after_seconds
    if error.next_available_at is not None:
        detail['next_available_at'] = error.next_available_at.isoformat()
    return HTTPException(status_code=error.status_code, detail=detail)


@router.get('/balances', response_model=list[dict])
async def list_balances_by_person(
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> list[dict]:
    return await service.balances_by_person(current_user.id)


@router.get('/notification-statuses', response_model=dict[str, SplitNotificationSplitStatusResponse])
async def list_notification_statuses(
    current_user: User = Depends(get_current_user),
    split_service: SplitService = Depends(get_split_service),
    notification_service: SplitNotificationService = Depends(get_split_notification_service),
) -> dict[str, SplitNotificationSplitStatusResponse]:
    result: dict[str, SplitNotificationSplitStatusResponse] = {}
    for split in await split_service.list_for_user(current_user.id):
        payload = await notification_service.status_split(current_user.id, split.id)
        result[str(split.id)] = SplitNotificationSplitStatusResponse.model_validate(payload)
    return result


@router.post('/balances/{contact_id}/email', response_model=SplitNotificationQueueResponse,
             status_code=status.HTTP_202_ACCEPTED)
async def queue_balance_statement(
    contact_id: uuid.UUID, idempotency_key: uuid.UUID = Header(alias='Idempotency-Key'),
    current_user: User = Depends(get_current_user), split_service: SplitService = Depends(get_split_service),
    notification_service: SplitNotificationService = Depends(get_split_notification_service),
) -> SplitNotificationQueueResponse:
    contacts = await split_service.list_contact_preferences(current_user.id)
    contact = next((item for item in contacts if item.id == contact_id), None)
    if contact is None:
        raise HTTPException(status_code=404, detail='Saved person was not found.')
    balance = next((item for item in await split_service.balances_by_person(current_user.id)
                    if item['person'].casefold() == contact.name.casefold()), None)
    if balance is None:
        raise HTTPException(status_code=409, detail='There is no outstanding balance with this person.')
    try:
        notification = await notification_service.queue_balance_statement(
            current_user.id, contact_id, balance, idempotency_key,
        )
    except SplitNotificationError as error:
        raise _notification_http_error(error) from error
    wake_sms_scheduler()
    return SplitNotificationQueueResponse(
        notification_id=notification.id, status=notification.status, created_at=notification.created_at,
    )


@router.post('/balances/settle', response_model=dict)
async def settle_person_balance(
    payload: SettleBalanceRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> dict:
    try:
        return await service.settle_balance(
            current_user.id, payload.person_name, payload.account_id, payload.amount_paise,
            payload.expected_owed_to_you_paise, payload.expected_you_owe_paise,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


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


@router.get('/contacts/details', response_model=list[SplitContactDetailsResponse])
async def list_split_contact_details(
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> list[SplitContactDetailsResponse]:
    return [SplitContactDetailsResponse.model_validate(contact, from_attributes=True)
            for contact in await service.list_contact_preferences(current_user.id)]


@router.put('/contacts/details', response_model=SplitContactDetailsResponse)
async def set_split_contact_details(
    payload: SplitContactDetailsRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> SplitContactDetailsResponse:
    try:
        contact = await service.set_contact_details(
            current_user.id, payload.name, payload.phone_e164, payload.email, payload.contact_id,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return SplitContactDetailsResponse.model_validate(contact, from_attributes=True)


@router.delete('/contacts/details/{contact_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_split_contact_details(
    contact_id: uuid.UUID,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> None:
    try:
        if not await service.delete_contact_preference(current_user.id, contact_id):
            raise HTTPException(status_code=404, detail='Split contact not found.')
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


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
    try:
        if not await service.delete_contact_preference(current_user.id, contact_id):
            raise HTTPException(status_code=404, detail='Split contact preference not found.')
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


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
        [
            ItemAllocation(item.name, item.amount_paise, item.shared_by, item.food_type, item.owner_excluded)
            for item in payload.items
        ],
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


@router.post('/owed', response_model=SplitResponse, status_code=status.HTTP_201_CREATED)
async def create_money_owed(
    payload: CreateOwedRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> SplitResponse:
    try:
        split = await service.create_owed(
            current_user.id, payload.title, payload.name, payload.amount_paise, payload.direction,
            owner_name=current_user.name, contact_id=payload.contact_id,
        )
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
            [ParticipantShare(person.name, person.share_paise, person.contact_id) for person in payload.participants],
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


@router.post(
    '/{split_id}/notifications',
    response_model=SplitNotificationBatchQueueResponse, status_code=status.HTTP_202_ACCEPTED,
)
async def queue_split_notifications(
    split_id: uuid.UUID,
    payload: SplitNotificationBatchRequest | None = None,
    idempotency_key: uuid.UUID = Header(alias='Idempotency-Key'),
    current_user: User = Depends(get_current_user),
    service: SplitNotificationService = Depends(get_split_notification_service),
) -> SplitNotificationBatchQueueResponse:
    try:
        queued = await service.queue_split(
            current_user.id, split_id, idempotency_key, payload.participant_ids if payload else None,
        )
    except SplitNotificationError as error:
        raise _notification_http_error(error) from error
    wake_sms_scheduler()
    first = queued.notifications[0]
    return SplitNotificationBatchQueueResponse(
        campaign_id=idempotency_key,
        notification_ids=[item.id for item in queued.notifications],
        status=first.status, created_at=first.created_at,
        skipped_recipients=[SplitNotificationSkippedRecipientResponse.model_validate(item)
                            for item in queued.skipped_recipients],
    )


@router.get('/{split_id}/notifications', response_model=SplitNotificationSplitStatusResponse)
async def get_split_notification_status(
    split_id: uuid.UUID,
    response: Response,
    current_user: User = Depends(get_current_user),
    service: SplitNotificationService = Depends(get_split_notification_service),
) -> SplitNotificationSplitStatusResponse:
    try:
        payload = await service.status_split(current_user.id, split_id)
    except SplitNotificationError as error:
        raise _notification_http_error(error) from error
    response.headers['Cache-Control'] = 'private, no-store'
    return SplitNotificationSplitStatusResponse.model_validate(payload)


@router.patch('/{split_id}/title', response_model=SplitResponse)
async def rename_split(
    split_id: uuid.UUID, payload: RenameSplitRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> SplitResponse:
    try:
        split = await service.rename(current_user.id, split_id, payload.title)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
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
            [ParticipantEditShare(person.id, person.name, person.share_paise, person.contact_id)
             for person in payload.participants],
            payload.transaction_amount_paise,
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


@router.post('/{split_id}/participants/{participant_id}/payments', response_model=SplitResponse)
async def record_split_payment(
    split_id: uuid.UUID, participant_id: uuid.UUID, payload: RecordSplitPaymentRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> SplitResponse:
    try:
        split = await service.record_payment(
            current_user.id, split_id, participant_id, payload.account_id, payload.amount_paise,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if split is None:
        raise HTTPException(status_code=404, detail='Split participant not found.')
    return SplitResponse.from_model(split)


@router.post('/{split_id}/participants/{participant_id}/pay', response_model=SplitResponse)
async def pay_money_owed(
    split_id: uuid.UUID, participant_id: uuid.UUID, payload: PayOwedRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> SplitResponse:
    try:
        split = await service.pay_owed(current_user.id, split_id, participant_id, payload.account_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if split is None:
        raise HTTPException(status_code=404, detail='Owed entry or person not found.')
    return SplitResponse.from_model(split)


@router.post('/{split_id}/settlement-transfers/repay', response_model=SplitResponse)
async def repay_settlement_transfer(
    split_id: uuid.UUID, payload: RepaySettlementTransferRequest,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> SplitResponse:
    try:
        split = await service.repay_settlement_transfer(
            current_user.id, split_id, payload.debtor, payload.account_id,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if split is None:
        raise HTTPException(status_code=404, detail='Split not found.')
    return SplitResponse.from_model(split)


@router.delete('/{split_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_split(
    split_id: uuid.UUID,
    current_user: User = Depends(get_current_user), service: SplitService = Depends(get_split_service),
) -> None:
    if not await service.delete(current_user.id, split_id):
        raise HTTPException(status_code=404, detail='Split not found.')
