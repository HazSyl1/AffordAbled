from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.entities import Account, AccountType, Category, CategoryType, Transaction, TransactionType
from app.infrastructure.ai.tools.category_tools import CategoryTools
from app.infrastructure.ai.tools.langgraph_finance_tools import LangGraphFinanceTools
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
    def __init__(self, accounts: list[Account] | None = None) -> None:
        self.accounts = accounts or []

    async def list_for_user(self, user_id: uuid.UUID) -> list[Account]:
        return [account for account in self.accounts if account.user_id == user_id]


class OptimizedTransactionRepository:
    def __init__(self) -> None:
        self.list_called = False
        self.window_called = False
        self.aggregate_called = False
        self.account_aggregate_called = False

    async def list_for_user(self, _user_id: uuid.UUID) -> list[Transaction]:
        self.list_called = True
        raise AssertionError('full history must not be loaded')

    async def list_for_user_window(self, _user_id: uuid.UUID, **_kwargs: object) -> tuple[list[Transaction], int]:
        self.window_called = True
        return [], 5000

    async def spending_summary_for_user(self, _user_id: uuid.UUID, **_kwargs: object) -> dict[str, object]:
        self.aggregate_called = True
        return {'total_spent_paise': 12345, 'transaction_count': 77, 'by_category': []}

    async def spending_by_account_for_user(self, _user_id: uuid.UUID, **_kwargs: object) -> list[dict[str, object]]:
        self.account_aggregate_called = True
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


def test_month_comparison_windows_match_elapsed_local_dates_and_clamp_prior_month_end() -> None:
    now_utc = datetime(2026, 3, 31, 17, 30, tzinfo=UTC)

    current_from, current_to, prior_from, prior_to = TransactionQueryTools.resolve_spending_comparison_windows(
        date_period='this_month',
        comparison_period='last_month',
        now_utc=now_utc,
        timezone_name='Asia/Kolkata',
    )

    assert current_from == datetime(2026, 2, 28, 18, 30, tzinfo=UTC)
    assert current_to == now_utc
    assert prior_from == datetime(2026, 1, 31, 18, 30, tzinfo=UTC)
    assert prior_to == datetime(2026, 2, 28, 17, 30, tzinfo=UTC)


def test_week_comparison_windows_use_same_local_weekday_and_time() -> None:
    now_utc = datetime(2026, 10, 14, 8, 30, tzinfo=UTC)  # Wednesday

    current_from, current_to, prior_from, prior_to = TransactionQueryTools.resolve_spending_comparison_windows(
        date_period='this_week',
        comparison_period='last_week',
        now_utc=now_utc,
        timezone_name='UTC',
    )

    assert current_from == datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
    assert current_to == now_utc
    assert prior_from == datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
    assert prior_to == datetime(2026, 10, 7, 8, 30, tzinfo=UTC)


def test_spending_comparison_rejects_unsupported_period_pair() -> None:
    with pytest.raises(ValueError, match='Unsupported spending comparison'):
        TransactionQueryTools.resolve_spending_comparison_windows(
            date_period='last_month', comparison_period='last_week', now_utc=datetime(2026, 10, 14, tzinfo=UTC)
        )


def test_large_paise_amount_formats_without_float_precision_loss() -> None:
    assert TransactionQueryTools._format_paise(90_071_992_547_409_939) == 'INR 900,719,925,474,099.39'


@pytest.mark.asyncio
async def test_analytics_uses_database_window_and_aggregate_methods() -> None:
    user_id = uuid.uuid4()
    repository = OptimizedTransactionRepository()
    tools = TransactionQueryTools(
        transaction_repository=repository,  # type: ignore[arg-type]
        account_repository=StubAccountRepository(),
        category_repository=StubCategoryRepository([]),
    )
    date_from = datetime(2026, 10, 1, tzinfo=UTC)
    date_to = datetime(2026, 10, 31, tzinfo=UTC)

    assert await tools.get_transactions(user_id=user_id, date_from=date_from, date_to=date_to, limit=10) == []
    summary = await tools.get_spending_summary(user_id=user_id, date_from=date_from, date_to=date_to)
    breakdown = await tools.get_spending_by_account(user_id=user_id, date_from=date_from, date_to=date_to)

    assert summary['total_spent_paise'] == 12345
    assert summary['transaction_count'] == 77
    assert breakdown['accounts'] == []
    assert repository.window_called is True
    assert repository.aggregate_called is True
    assert repository.account_aggregate_called is True
    assert repository.list_called is False


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


@pytest.mark.asyncio
async def test_spending_comparison_applies_category_and_owner_scope_and_computes_delta() -> None:
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    food = Category(
        id=uuid.uuid4(),
        user_id=user_id,
        name='Food',
        icon=None,
        color=None,
        type=CategoryType.EXPENSE,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    other_food = Category(
        id=uuid.uuid4(),
        user_id=other_user_id,
        name='Food',
        icon=None,
        color=None,
        type=CategoryType.EXPENSE,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    def transaction(
        *,
        owner_id: uuid.UUID,
        category_id: uuid.UUID,
        amount_paise: int,
        occurred_at: datetime,
        transaction_type: TransactionType = TransactionType.EXPENSE,
    ) -> Transaction:
        return Transaction(
            id=uuid.uuid4(),
            user_id=owner_id,
            account_id=uuid.uuid4(),
            to_account_id=None,
            category_id=category_id,
            type=transaction_type,
            amount_paise=amount_paise,
            merchant='Shop',
            note=None,
            occurred_at=occurred_at,
            deleted_at=None,
            created_at=occurred_at,
            updated_at=occurred_at,
        )

    current_from = datetime(2026, 10, 1, tzinfo=UTC)
    current_to = datetime(2026, 10, 14, 12, tzinfo=UTC)
    prior_from = datetime(2026, 9, 1, tzinfo=UTC)
    prior_to = datetime(2026, 9, 14, 12, tzinfo=UTC)
    tools = TransactionQueryTools(
        transaction_repository=StubTransactionRepository(
            [
                transaction(
                    owner_id=user_id,
                    category_id=food.id,
                    amount_paise=15000,
                    occurred_at=datetime(2026, 10, 8, tzinfo=UTC),
                ),
                transaction(
                    owner_id=user_id,
                    category_id=food.id,
                    amount_paise=10000,
                    occurred_at=datetime(2026, 9, 8, tzinfo=UTC),
                ),
                transaction(
                    owner_id=user_id,
                    category_id=food.id,
                    amount_paise=50000,
                    occurred_at=datetime(2026, 9, 20, tzinfo=UTC),
                ),
                transaction(
                    owner_id=other_user_id,
                    category_id=other_food.id,
                    amount_paise=90000,
                    occurred_at=datetime(2026, 10, 8, tzinfo=UTC),
                ),
            ]
        ),
        account_repository=StubAccountRepository(),
        category_repository=StubCategoryRepository([food, other_food]),
    )

    comparison = await tools.get_spending_comparison(
        user_id=user_id,
        current_date_from=current_from,
        current_date_to=current_to,
        comparison_date_from=prior_from,
        comparison_date_to=prior_to,
        category_id=food.id,
    )

    assert comparison['current']['total_spent_paise'] == 15000
    assert comparison['current']['transaction_count'] == 1
    assert comparison['comparison']['total_spent_paise'] == 10000
    assert comparison['comparison']['transaction_count'] == 1
    assert comparison['delta_paise'] == 5000
    assert comparison['percent_change'] == 50.0
    assert comparison['direction'] == 'higher'


@pytest.mark.asyncio
async def test_spending_comparison_with_zero_baseline_has_no_infinite_percentage() -> None:
    user_id = uuid.uuid4()
    category = Category(
        id=uuid.uuid4(),
        user_id=user_id,
        name='Food',
        icon=None,
        color=None,
        type=CategoryType.EXPENSE,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    current_date = datetime(2026, 10, 10, tzinfo=UTC)
    tool = TransactionQueryTools(
        transaction_repository=StubTransactionRepository(
            [
                Transaction(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    account_id=uuid.uuid4(),
                    to_account_id=None,
                    category_id=category.id,
                    type=TransactionType.EXPENSE,
                    amount_paise=25000,
                    merchant='Shop',
                    note=None,
                    occurred_at=current_date,
                    deleted_at=None,
                    created_at=current_date,
                    updated_at=current_date,
                )
            ]
        ),
        account_repository=StubAccountRepository(),
        category_repository=StubCategoryRepository([category]),
    )

    result = await tool.get_spending_comparison(
        user_id=user_id,
        current_date_from=datetime(2026, 10, 1, tzinfo=UTC),
        current_date_to=datetime(2026, 10, 14, tzinfo=UTC),
        comparison_date_from=datetime(2026, 9, 1, tzinfo=UTC),
        comparison_date_to=datetime(2026, 9, 14, tzinfo=UTC),
    )

    assert result['comparison']['total_spent_paise'] == 0
    assert result['delta_paise'] == 25000
    assert result['percent_change'] is None
    assert result['direction'] == 'higher'


@pytest.mark.asyncio
async def test_registered_comparison_tool_uses_injected_user_state_and_returns_comparison_facts() -> None:
    user_id = uuid.uuid4()
    category_repository = StubCategoryRepository([])
    query_tools = TransactionQueryTools(
        transaction_repository=StubTransactionRepository([]),
        account_repository=StubAccountRepository(),
        category_repository=category_repository,
    )
    finance_tools = LangGraphFinanceTools(
        category_tools=CategoryTools(category_repository=category_repository),
        transaction_query_tools=query_tools,
    )
    comparison_tool = next(
        tool for tool in finance_tools.build_query_tools() if tool.name == 'query_spending_comparison'
    )
    assert comparison_tool.coroutine is not None
    raw_payload = await comparison_tool.coroutine(
        message='Compare this month vs last month',
        date_period='this_month',
        comparison_period='last_month',
        timezone_name='UTC',
        category_hint=None,
        state={'runtime_user_id': str(user_id)},
    )
    payload = json.loads(raw_payload)

    assert payload['facts']['query_kind'] == 'spending_comparison'
    assert payload['facts']['current_period']['total_spent_paise'] == 0
    assert payload['facts']['comparison_period']['total_spent_paise'] == 0
    assert payload['facts']['direction'] == 'same'


@pytest.mark.asyncio
async def test_registered_transaction_query_caps_rows_and_marks_more_results() -> None:
    user_id = uuid.uuid4()
    occurred_at = datetime(2026, 10, 14, tzinfo=UTC)
    transactions = [
        Transaction(
            id=uuid.uuid4(),
            user_id=user_id,
            account_id=uuid.uuid4(),
            to_account_id=None,
            category_id=None,
            type=TransactionType.EXPENSE,
            amount_paise=100 + index,
            merchant=f'Merchant {index}',
            note=None,
            occurred_at=occurred_at,
            deleted_at=None,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        for index in range(11)
    ]
    category_repository = StubCategoryRepository([])
    query_tools = TransactionQueryTools(
        transaction_repository=StubTransactionRepository(transactions),
        account_repository=StubAccountRepository(),
        category_repository=category_repository,
    )
    finance_tools = LangGraphFinanceTools(
        category_tools=CategoryTools(category_repository=category_repository),
        transaction_query_tools=query_tools,
    )
    query_tool = next(tool for tool in finance_tools.build_query_tools() if tool.name == 'query_transactions')
    assert query_tool.coroutine is not None

    raw_payload = await query_tool.coroutine(
        message='Show transactions this month',
        limit=10,
        date_period='this_month',
        timezone_name='UTC',
        transaction_type='all',
        state={'runtime_user_id': str(user_id)},
    )
    payload = json.loads(raw_payload)

    assert len(payload['facts']['transactions']) == 10
    assert payload['facts']['transaction_count'] == 10
    assert payload['facts']['has_more'] is True
    assert 'more matching transactions exist' in payload['reply']


@pytest.mark.asyncio
async def test_account_balances_are_user_scoped_active_and_filterable_by_exact_name() -> None:
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    now = datetime(2026, 10, 14, tzinfo=UTC)

    def make_account(
        *, owner_id: uuid.UUID, name: str, balance_paise: int, active: bool = True
    ) -> Account:
        return Account(
            id=uuid.uuid4(),
            user_id=owner_id,
            name=name,
            type=AccountType.BANK,
            balance_paise=balance_paise,
            currency='INR',
            is_active=active,
            is_default=False,
            created_at=now,
            updated_at=now,
        )

    checking = make_account(owner_id=user_id, name='Checking', balance_paise=12345)
    savings = make_account(owner_id=user_id, name='Savings', balance_paise=50000)
    inactive = make_account(owner_id=user_id, name='Old account', balance_paise=777, active=False)
    other_user_account = make_account(owner_id=other_user_id, name='Private', balance_paise=99999)
    query_tools = TransactionQueryTools(
        transaction_repository=StubTransactionRepository([]),
        account_repository=StubAccountRepository([checking, savings, inactive, other_user_account]),
        category_repository=StubCategoryRepository([]),
    )

    all_balances = await query_tools.get_account_balances(user_id=user_id)
    highest_balance = await query_tools.get_account_balances(
        user_id=user_id, order_by='balance', sort_order='desc', limit=1,
    )
    one_balance = await query_tools.get_account_balances(user_id=user_id, account_names=['savings'])
    not_found = await query_tools.get_account_balances(user_id=user_id, account_names=['Private'])

    assert [account['name'] for account in all_balances['accounts']] == ['Checking', 'Savings']
    assert [account['name'] for account in highest_balance['accounts']] == ['Savings']
    assert [account['name'] for account in one_balance['accounts']] == ['Savings']
    assert one_balance['accounts'][0]['balance_paise'] == 50000
    assert one_balance['accounts'][0]['balance_display'] == 'INR 500.00'
    assert not_found == {'status': 'not_found', 'requested_account': 'Private', 'accounts': []}


@pytest.mark.asyncio
async def test_spending_by_account_groups_scoped_expenses_and_reports_truncation() -> None:
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    category = Category(
        id=uuid.uuid4(),
        user_id=user_id,
        name='Food',
        icon=None,
        color=None,
        type=CategoryType.EXPENSE,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    now = datetime(2026, 10, 14, tzinfo=UTC)
    accounts = [
        Account(
            id=uuid.uuid4(),
            user_id=user_id,
            name=f'Account {index:02}',
            type=AccountType.BANK,
            balance_paise=0,
            currency='INR',
            is_active=True,
            is_default=False,
            created_at=now,
            updated_at=now,
        )
        for index in range(12)
    ]
    inactive_account = Account(
        id=uuid.uuid4(),
        user_id=user_id,
        name='Inactive',
        type=AccountType.BANK,
        balance_paise=0,
        currency='INR',
        is_active=False,
        is_default=False,
        created_at=now,
        updated_at=now,
    )
    outsider_account = Account(
        id=uuid.uuid4(),
        user_id=other_user_id,
        name='Other user',
        type=AccountType.BANK,
        balance_paise=0,
        currency='INR',
        is_active=True,
        is_default=False,
        created_at=now,
        updated_at=now,
    )

    def transaction(
        *,
        owner_id: uuid.UUID,
        account_id: uuid.UUID,
        amount_paise: int,
        transaction_type: TransactionType = TransactionType.EXPENSE,
        transaction_category_id: uuid.UUID | None = None,
        occurred_at: datetime = now,
    ) -> Transaction:
        return Transaction(
            id=uuid.uuid4(),
            user_id=owner_id,
            account_id=account_id,
            to_account_id=None,
            category_id=transaction_category_id,
            type=transaction_type,
            amount_paise=amount_paise,
            merchant='Shop',
            note=None,
            occurred_at=occurred_at,
            deleted_at=None,
            created_at=occurred_at,
            updated_at=occurred_at,
        )

    transactions = [
        transaction(
            owner_id=user_id,
            account_id=account.id,
            amount_paise=(12 - index) * 100,
            transaction_category_id=category.id,
        )
        for index, account in enumerate(accounts)
    ]
    transactions.extend(
        [
            transaction(
                owner_id=user_id,
                account_id=accounts[0].id,
                amount_paise=99999,
                transaction_type=TransactionType.INCOME,
                transaction_category_id=category.id,
            ),
            transaction(
                owner_id=user_id,
                account_id=accounts[0].id,
                amount_paise=88888,
                transaction_category_id=None,
            ),
            transaction(
                owner_id=user_id,
                account_id=inactive_account.id,
                amount_paise=77777,
                transaction_category_id=category.id,
            ),
            transaction(
                owner_id=other_user_id,
                account_id=outsider_account.id,
                amount_paise=66666,
                transaction_category_id=None,
            ),
            transaction(
                owner_id=user_id,
                account_id=accounts[0].id,
                amount_paise=55555,
                transaction_category_id=category.id,
                occurred_at=datetime(2026, 9, 30, tzinfo=UTC),
            ),
        ]
    )
    query_tools = TransactionQueryTools(
        transaction_repository=StubTransactionRepository(transactions),
        account_repository=StubAccountRepository([*accounts, inactive_account, outsider_account]),
        category_repository=StubCategoryRepository([category]),
    )

    result = await query_tools.get_spending_by_account(
        user_id=user_id,
        date_from=datetime(2026, 10, 1, tzinfo=UTC),
        date_to=datetime(2026, 10, 31, tzinfo=UTC),
        category_id=category.id,
    )

    assert result['total_spent_paise'] == sum(range(1200, 0, -100))
    assert result['transaction_count'] == 12
    assert result['account_count'] == 12
    assert len(result['accounts']) == 10
    assert result['truncated_account_count'] == 2
    assert result['accounts'][0]['account_name'] == 'Account 00'
    assert result['accounts'][0]['total_spent_paise'] == 1200


@pytest.mark.asyncio
async def test_transaction_query_returns_newest_rows_before_applying_limit() -> None:
    user_id = uuid.uuid4()
    base = datetime(2026, 10, 1, tzinfo=UTC)
    transactions = [
        Transaction(
            id=uuid.uuid4(),
            user_id=user_id,
            account_id=uuid.uuid4(),
            to_account_id=None,
            category_id=None,
            type=TransactionType.EXPENSE,
            amount_paise=index * 100,
            merchant=f'Merchant {index}',
            note=None,
            occurred_at=base + timedelta(days=index),
            deleted_at=None,
            created_at=base + timedelta(days=index),
            updated_at=base + timedelta(days=index),
        )
        for index in range(12)
    ]
    query_tools = TransactionQueryTools(
        transaction_repository=StubTransactionRepository(transactions),
        account_repository=StubAccountRepository(),
        category_repository=StubCategoryRepository([]),
    )

    result = await query_tools.get_transactions(
        user_id=user_id,
        date_from=base,
        date_to=base + timedelta(days=20),
        limit=3,
    )

    assert [transaction['merchant'] for transaction in result] == ['Merchant 11', 'Merchant 10', 'Merchant 9']


@pytest.mark.asyncio
async def test_transaction_query_can_rank_largest_expense_before_applying_limit() -> None:
    user_id = uuid.uuid4()
    base = datetime(2026, 10, 1, tzinfo=UTC)
    transactions = [
        Transaction(
            id=uuid.uuid4(), user_id=user_id, account_id=uuid.uuid4(), to_account_id=None,
            category_id=None, type=transaction_type, amount_paise=amount_paise,
            merchant=merchant, note=None, occurred_at=base + timedelta(days=day), deleted_at=None,
            created_at=base + timedelta(days=day), updated_at=base + timedelta(days=day),
        )
        for merchant, amount_paise, day, transaction_type in [
            ('Recent small expense', 10_000, 3, TransactionType.EXPENSE),
            ('Largest expense', 90_000, 1, TransactionType.EXPENSE),
            ('Larger income', 200_000, 2, TransactionType.INCOME),
        ]
    ]
    query_tools = TransactionQueryTools(
        transaction_repository=StubTransactionRepository(transactions),
        account_repository=StubAccountRepository(),
        category_repository=StubCategoryRepository([]),
    )

    result = await query_tools.get_transactions(
        user_id=user_id, date_from=base, date_to=base + timedelta(days=5), limit=1,
        transaction_type=TransactionType.EXPENSE, order_by='amount', sort_order='desc',
    )

    assert [transaction['merchant'] for transaction in result] == ['Largest expense']


@pytest.mark.asyncio
async def test_transaction_query_combines_account_category_and_amount_ranking_filters() -> None:
    user_id = uuid.uuid4()
    axis_id = uuid.uuid4()
    cash_id = uuid.uuid4()
    food_id = uuid.uuid4()
    shopping_id = uuid.uuid4()
    base = datetime(2026, 10, 1, tzinfo=UTC)

    def transaction(merchant: str, amount: int, account_id: uuid.UUID, category_id: uuid.UUID) -> Transaction:
        return Transaction(
            id=uuid.uuid4(), user_id=user_id, account_id=account_id, to_account_id=None,
            category_id=category_id, type=TransactionType.EXPENSE, amount_paise=amount,
            merchant=merchant, note=None, occurred_at=base, deleted_at=None,
            created_at=base, updated_at=base,
        )

    query_tools = TransactionQueryTools(
        transaction_repository=StubTransactionRepository([
            transaction('Axis Food', 90_000, axis_id, food_id),
            transaction('Cash Food', 100_000, cash_id, food_id),
            transaction('Axis Shopping', 120_000, axis_id, shopping_id),
        ]),
        account_repository=StubAccountRepository(),
        category_repository=StubCategoryRepository([]),
    )

    result = await query_tools.get_transactions(
        user_id=user_id, date_from=base - timedelta(days=1), date_to=base + timedelta(days=1),
        account_id=axis_id, category_id=food_id, transaction_type=TransactionType.EXPENSE,
        order_by='amount', sort_order='desc', limit=1,
    )

    assert [transaction['merchant'] for transaction in result] == ['Axis Food']
