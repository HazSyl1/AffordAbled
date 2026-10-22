from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.complex_settlement import SettlementInput
from app.application.services.complex_settlement_service import ComplexSettlementService
from app.core.dependencies import get_current_user, get_db
from app.domain.entities import User
from app.infrastructure.database.repositories.sqlalchemy_complex_settlement_repository import (
    SqlAlchemyComplexSettlementRepository,
)

router = APIRouter(prefix='/settlement-plans', tags=['settlement-plans'])


def get_complex_settlement_service(db: AsyncSession = Depends(get_db)) -> ComplexSettlementService:
    return ComplexSettlementService(SqlAlchemyComplexSettlementRepository(db))


class DraftCreateRequest(BaseModel):
    request_key: str = Field(min_length=1, max_length=120)
    data: SettlementInput
    revision_plan_id: uuid.UUID | None = None


class DraftUpdateRequest(BaseModel):
    version: int = Field(gt=0)
    data: SettlementInput


class ConfirmRequest(BaseModel):
    version: int = Field(gt=0)


class SettleTransferRequest(BaseModel):
    account_id: uuid.UUID | None = None


def _draft_response(draft) -> dict:
    return {
        'id': draft.id, 'version': draft.version, 'status': draft.status,
        'data': draft.input_json, 'preview': draft.preview_json, 'plan_id': draft.plan_id,
        'revision_plan_id': draft.revision_plan_id,
    }


def _plan_response(plan) -> dict:
    return {
        'id': plan.id, 'title': plan.title, 'total_paise': plan.total_paise,
        'data': plan.input_json, 'preview': plan.preview_json,
        'transaction_ids': [row.transaction_id for row in plan.transactions],
        'transfers': [{
            'id': row.id, 'debtor': row.debtor, 'creditor': row.creditor,
            'amount_paise': row.amount_paise, 'settled_at': row.settled_at,
            'repayment_transaction_id': row.repayment_transaction_id,
        } for row in plan.transfers],
    }


def _error(exc: ValueError | LookupError) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, LookupError) else 409, detail=str(exc))


@router.post('/drafts')
async def create_draft(
    payload: DraftCreateRequest, current_user: User = Depends(get_current_user),
    service: ComplexSettlementService = Depends(get_complex_settlement_service),
) -> dict:
    try:
        return _draft_response(await service.create_draft(
            current_user.id, payload.request_key, payload.data, payload.revision_plan_id,
        ))
    except (ValueError, LookupError) as exc:
        raise _error(exc) from exc


@router.get('/drafts/{draft_id}')
async def get_draft(
    draft_id: uuid.UUID, current_user: User = Depends(get_current_user),
    service: ComplexSettlementService = Depends(get_complex_settlement_service),
) -> dict:
    draft = await service.get_draft(current_user.id, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail='Settlement draft was not found.')
    return _draft_response(draft)


@router.put('/drafts/{draft_id}')
async def update_draft(
    draft_id: uuid.UUID, payload: DraftUpdateRequest, current_user: User = Depends(get_current_user),
    service: ComplexSettlementService = Depends(get_complex_settlement_service),
) -> dict:
    try:
        return _draft_response(await service.update_draft(
            current_user.id, draft_id, payload.version, payload.data,
        ))
    except (ValueError, LookupError) as exc:
        raise _error(exc) from exc


@router.post('/drafts/{draft_id}/confirm')
async def confirm_draft(
    draft_id: uuid.UUID, payload: ConfirmRequest, current_user: User = Depends(get_current_user),
    service: ComplexSettlementService = Depends(get_complex_settlement_service),
) -> dict:
    try:
        return _plan_response(await service.confirm(current_user.id, draft_id, payload.version))
    except (ValueError, LookupError) as exc:
        raise _error(exc) from exc


@router.get('')
async def list_plans(
    current_user: User = Depends(get_current_user),
    service: ComplexSettlementService = Depends(get_complex_settlement_service),
) -> list[dict]:
    return [_plan_response(plan) for plan in await service.list_plans(current_user.id)]


@router.get('/{plan_id}')
async def get_plan(
    plan_id: uuid.UUID, current_user: User = Depends(get_current_user),
    service: ComplexSettlementService = Depends(get_complex_settlement_service),
) -> dict:
    plan = await service.get_plan(current_user.id, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail='Settlement plan was not found.')
    return _plan_response(plan)


@router.post('/{plan_id}/transfers/{transfer_id}/settle')
async def settle_transfer(
    plan_id: uuid.UUID, transfer_id: uuid.UUID, payload: SettleTransferRequest,
    current_user: User = Depends(get_current_user),
    service: ComplexSettlementService = Depends(get_complex_settlement_service),
) -> dict:
    try:
        return _plan_response(await service.settle_transfer(
            current_user.id, plan_id, transfer_id, payload.account_id,
        ))
    except (ValueError, LookupError) as exc:
        raise _error(exc) from exc
