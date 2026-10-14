from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.domain.entities import Category, CategoryType, Transaction, TransactionType
from app.infrastructure.ai.tools.transaction_query_tools import TransactionQueryTools


class StubTransactionRepository:
    def __init__(self, transactions: list[Transaction]) -> None:
        self.transactions = transactions

    async def list_for_user(self, user_id: uuid.UUID) -> list[Transaction]:
        return [transaction for transaction in self.transactions if transaction.user_id == user_id]


class StubCategoryRepository:
    def __init__(self, categories: list[Category]) -> None:
        self.categories = categories

    async def list_for_user(self, user_id: uuid.UUID) -> list[Category]:
        return [category for category in self.categories if category.user_id == user_id]


class StubAccountRepository:
    async def list_for_user(self, user_id: uuid.UUID) -> list[Any]:
        del user_id
        return []


def test_this_week_window_starts_monday_and_ends_at_now() -> None:
    now = datetime(2026, 10, 14, 8, 30, tzinfo=UTC)  # Wednesday

    date_from, date_to = TransactionQueryTools.resolve_date_window('spent this week', now_utc=now)

    assert date_from == datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
    assert date_to == now


def test_this_month_window_starts_on_first_day_and_ends_at_now() -> None:
    now = datetime(2026, 10, 14, 8, 30, tzinfo=UTC)

    date_from, date_to = TransactionQueryTools.resolve_date_window('spending this month', now_utc=now)

    assert date_from == datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    assert date_to == now


def test_today_window_uses_requested_local_timezone() -> None:
    now_utc = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)

    date_from, date_to = TransactionQueryTools.resolve_date_window(
        'today',
        now_utc=now_utc,
        timezone_name='America/Los_Angeles',
        date_period='today',
    )

    assert date_from == datetime(2026, 10, 13, 7, 0, tzinfo=UTC)
    assert date_to == now_utc


@pytest.mark.asyncio
async def test_spending_summary_filters_to_matching_expense_category() -> None:
    user_id = uuid.uuid4()
    food = Category(
        id=uuid.uuid4(),
        user_id=user_id,
        name='Food',
        icon=None,
        color=None,
        type=CategoryType.EXPENSE,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    travel = Category(
        id=uuid.uuid4(),
        user_id=user_id,
        name='Travel',
        icon=None,
        color=None,
        type=CategoryType.EXPENSE,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    occurred_at = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
    transactions = [
        Transaction(
            id=uuid.uuid4(),
            user_id=user_id,
            account_id=uuid.uuid4(),
            to_account_id=None,
            category_id=food.id,
            type=TransactionType.EXPENSE,
            amount_paise=125000,
            merchant='Restaurant',
            note='Dinner',
            occurred_at=occurred_at,
            deleted_at=None,
            created_at=occurred_at,
            updated_at=occurred_at,
        ),
        Transaction(
            id=uuid.uuid4(),
            user_id=user_id,
            account_id=uuid.uuid4(),
            to_account_id=None,
            category_id=travel.id,
            type=TransactionType.EXPENSE,
            amount_paise=500000,
            merchant='Airline',
            note='Flight',
            occurred_at=occurred_at,
            deleted_at=None,
            created_at=occurred_at,
            updated_at=occurred_at,
        ),
    ]
    tools = TransactionQueryTools(
        transaction_repository=StubTransactionRepository(transactions),
        account_repository=StubAccountRepository(),
        category_repository=StubCategoryRepository([food, travel]),
    )

    matched_category, ambiguous = await tools.resolve_expense_category(
        user_id=user_id,
        message='How much have I spent on food this month?',
    )
    summary = await tools.get_spending_summary(
        user_id=user_id,
        date_from=datetime(2026, 10, 1, tzinfo=UTC),
        date_to=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
        category_id=matched_category.id if matched_category else None,
    )

    assert ambiguous is False
    assert matched_category == food
    assert summary['total_spent_paise'] == 125000
    assert summary['transaction_count'] == 1
    assert summary['top_categories'] == [{'category_name': 'Food', 'amount_paise': 125000}]
