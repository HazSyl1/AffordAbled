from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.application.dto import CreateAccountInput, UpdateAccountInput
from app.application.services.account_service import AccountService
from app.core.dependencies import get_account_service, get_current_user
from app.domain.entities import User
from app.presentation.schemas.account import AccountResponse, CreateAccountRequest, UpdateAccountRequest

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: CreateAccountRequest,
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
) -> AccountResponse:
    account = await account_service.create_account(
        CreateAccountInput(
            user_id=current_user.id,
            name=payload.name,
            type=payload.type,
            balance_paise=payload.balance_paise,
            currency=payload.currency,
        )
    )
    return AccountResponse.from_entity(account)


@router.get("", response_model=list[AccountResponse])
async def list_accounts(
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
) -> list[AccountResponse]:
    accounts = await account_service.list_accounts(current_user.id)
    return [AccountResponse.from_entity(account) for account in accounts]


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
) -> AccountResponse:
    account = await account_service.get_account(current_user.id, account_id)
    return AccountResponse.from_entity(account)


@router.patch("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: uuid.UUID,
    payload: UpdateAccountRequest,
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
) -> AccountResponse:
    account = await account_service.update_account(
        current_user.id,
        account_id,
        UpdateAccountInput(name=payload.name, is_active=payload.is_active),
    )
    return AccountResponse.from_entity(account)
