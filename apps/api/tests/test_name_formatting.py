from __future__ import annotations

import uuid

import pytest

from app.application.dto import CreateAccountInput, CreateCategoryInput
from app.application.services.account_service import AccountService
from app.application.services.category_service import CategoryService
from app.application.services.split_service import ParticipantShare, SplitService
from app.domain.entities import AccountType, CategoryType


class AccountStore:
    async def list_for_user(self, _user_id: uuid.UUID) -> list:
        return []

    async def create(self, account):
        return account


class CategoryStore:
    async def create(self, category):
        return category


class SplitStore:
    async def create(self, _user_id, _transaction_id, _title, _owner_share, participants, _items):
        return participants


@pytest.mark.asyncio
async def test_new_account_and_category_names_start_with_a_capital() -> None:
    user_id = uuid.uuid4()
    account = await AccountService(AccountStore()).create_account(
        CreateAccountInput(user_id, '  axis  ', AccountType.BANK, 0)
    )
    category = await CategoryService(CategoryStore()).create_category(
        CreateCategoryInput(user_id, '  groceries  ', CategoryType.EXPENSE)
    )

    assert account.name == 'Axis'
    assert category.name == 'Groceries'


@pytest.mark.asyncio
async def test_split_participant_names_start_with_a_capital() -> None:
    people = await SplitService(SplitStore()).create(
        uuid.uuid4(), uuid.uuid4(), 'Dinner', 300, 'equal',
        [ParticipantShare('isha', 0)], owner_share_paise=None,
    )

    assert people[0].name == 'Isha'
