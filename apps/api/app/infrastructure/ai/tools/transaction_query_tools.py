from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.entities import Category, CategoryType, TransactionType
from app.domain.repositories import AccountRepository, CategoryRepository, TransactionRepository


@dataclass
class TransactionQueryTools:
    transaction_repository: TransactionRepository
    account_repository: AccountRepository
    category_repository: CategoryRepository

    async def get_transactions(
        self,
        *,
        user_id: uuid.UUID,
        date_from: datetime,
        date_to: datetime,
        limit: int = 10,
        transaction_type: TransactionType | None = None,
        category_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        transactions = await self.transaction_repository.list_for_user(user_id)
        account_names = await self._account_names_for_user(user_id)
        category_names = await self._category_names_for_user(user_id)

        normalized_date_from = self._to_utc_datetime(date_from)
        normalized_date_to = self._to_utc_datetime(date_to)

        scoped_transactions = [
            transaction
            for transaction in transactions
            if normalized_date_from <= self._to_utc_datetime(transaction.occurred_at) <= normalized_date_to
            and (transaction_type is None or transaction.type == transaction_type)
            and (category_id is None or transaction.category_id == category_id)
        ]

        capped_limit = max(1, min(limit, 25))
        selected_transactions = scoped_transactions[:capped_limit]
        return [
            {
                'id': str(transaction.id),
                'type': transaction.type.value,
                'amount_paise': transaction.amount_paise,
                'occurred_at': transaction.occurred_at.isoformat(),
                'merchant': transaction.merchant,
                'note': transaction.note,
                'account_name': account_names.get(str(transaction.account_id), 'Unknown account'),
                'category_name': category_names.get(str(transaction.category_id), 'Uncategorized')
                if transaction.category_id is not None
                else 'Uncategorized',
            }
            for transaction in selected_transactions
        ]

    async def get_spending_summary(
        self,
        *,
        user_id: uuid.UUID,
        date_from: datetime,
        date_to: datetime,
        category_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        transactions = await self.transaction_repository.list_for_user(user_id)
        categories = await self.category_repository.list_for_user(user_id)
        expense_category_names = {
            str(category.id): category.name
            for category in categories
            if category.type == CategoryType.EXPENSE
        }

        normalized_date_from = self._to_utc_datetime(date_from)
        normalized_date_to = self._to_utc_datetime(date_to)

        relevant_transactions = [
            transaction
            for transaction in transactions
            if normalized_date_from <= self._to_utc_datetime(transaction.occurred_at) <= normalized_date_to
            and transaction.type == TransactionType.EXPENSE
            and (category_id is None or transaction.category_id == category_id)
        ]

        total_spent_paise = sum(transaction.amount_paise for transaction in relevant_transactions)
        by_category: dict[str, int] = {}
        for transaction in relevant_transactions:
            category_label = (
                expense_category_names.get(str(transaction.category_id), 'Uncategorized')
                if transaction.category_id is not None
                else 'Uncategorized'
            )
            by_category[category_label] = by_category.get(category_label, 0) + transaction.amount_paise

        sorted_categories = sorted(by_category.items(), key=lambda item: item[1], reverse=True)
        return {
            'total_spent_paise': total_spent_paise,
            'transaction_count': len(relevant_transactions),
            'top_categories': [
                {'category_name': category_name, 'amount_paise': amount_paise}
                for category_name, amount_paise in sorted_categories[:5]
            ],
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
        }

    async def resolve_expense_category(
        self,
        *,
        user_id: uuid.UUID,
        message: str = '',
        category_hint: str | None = None,
    ) -> tuple[Category | None, bool]:
        normalized_reference = self._normalize_lookup_text(category_hint or message)
        if not normalized_reference:
            return None, False

        categories = [
            category
            for category in await self.category_repository.list_for_user(user_id)
            if category.type == CategoryType.EXPENSE
        ]
        matching_categories = [
            category
            for category in categories
            if (
                normalized_reference == self._normalize_lookup_text(category.name)
                or f' {self._normalize_lookup_text(category.name)} ' in f' {normalized_reference} '
            )
        ]
        if not matching_categories:
            return None, False

        longest_name_length = max(len(self._normalize_lookup_text(category.name)) for category in matching_categories)
        best_matches = [
            category
            for category in matching_categories
            if len(self._normalize_lookup_text(category.name)) == longest_name_length
        ]
        if len(best_matches) != 1:
            return None, True
        return best_matches[0], False

    @staticmethod
    def resolve_date_window(
        message: str,
        *,
        now_utc: datetime | None = None,
        timezone_name: str = 'UTC',
        date_period: str | None = None,
        period_count: int | None = None,
    ) -> tuple[datetime, datetime]:
        anchor_now = now_utc or datetime.now(UTC)
        normalized_message = ' '.join(message.lower().split())

        try:
            local_timezone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            local_timezone = ZoneInfo('UTC')
        local_now = anchor_now.astimezone(local_timezone)

        if date_period is not None:
            return TransactionQueryTools._resolve_planned_date_window(
                period=date_period,
                period_count=period_count,
                local_now=local_now,
            )

        if 'this week' in normalized_message or 'this week\'s' in normalized_message:
            week_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start -= timedelta(days=week_start.weekday())
            return week_start.astimezone(UTC), anchor_now

        if 'this month' in normalized_message or 'this month\'s' in normalized_message:
            month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return month_start.astimezone(UTC), anchor_now

        if 'last week' in normalized_message:
            this_week_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            this_week_start -= timedelta(days=this_week_start.weekday())
            last_week_start = this_week_start - timedelta(days=7)
            last_week_end = this_week_start - timedelta(microseconds=1)
            return last_week_start.astimezone(UTC), last_week_end.astimezone(UTC)

        if 'last month' in normalized_message:
            this_month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_month_end = this_month_start - timedelta(microseconds=1)
            last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return last_month_start.astimezone(UTC), last_month_end.astimezone(UTC)

        weeks_match = re.search(r'\b(\d{1,2})\s+weeks?\b', normalized_message)
        if weeks_match:
            weeks = max(1, min(12, int(weeks_match.group(1))))
            return anchor_now - timedelta(weeks=weeks), anchor_now

        days_match = re.search(r'\b(\d{1,3})\s+days?\b', normalized_message)
        if days_match:
            days = max(1, min(180, int(days_match.group(1))))
            return anchor_now - timedelta(days=days), anchor_now

        if 'yesterday' in normalized_message:
            yesterday = local_now - timedelta(days=1)
            start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
            return start.astimezone(UTC), end.astimezone(UTC)

        if 'today' in normalized_message:
            start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start.astimezone(UTC), anchor_now

        return anchor_now - timedelta(days=14), anchor_now

    @staticmethod
    def _resolve_planned_date_window(
        *,
        period: str,
        period_count: int | None,
        local_now: datetime,
    ) -> tuple[datetime, datetime]:
        today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == 'today':
            return today_start.astimezone(UTC), local_now.astimezone(UTC)
        if period == 'yesterday':
            yesterday = today_start - timedelta(days=1)
            yesterday_end = today_start - timedelta(microseconds=1)
            return yesterday.astimezone(UTC), yesterday_end.astimezone(UTC)
        if period == 'this_week':
            week_start = today_start - timedelta(days=today_start.weekday())
            return week_start.astimezone(UTC), local_now.astimezone(UTC)
        if period == 'last_week':
            this_week_start = today_start - timedelta(days=today_start.weekday())
            last_week_start = this_week_start - timedelta(days=7)
            return last_week_start.astimezone(UTC), (this_week_start - timedelta(microseconds=1)).astimezone(UTC)
        if period == 'this_month':
            month_start = today_start.replace(day=1)
            return month_start.astimezone(UTC), local_now.astimezone(UTC)
        if period == 'last_month':
            this_month_start = today_start.replace(day=1)
            last_month_end = this_month_start - timedelta(microseconds=1)
            return last_month_end.replace(day=1).astimezone(UTC), last_month_end.astimezone(UTC)
        if period == 'last_n_days':
            days = max(1, min(180, int(period_count or 14)))
            start = today_start - timedelta(days=days - 1)
            return start.astimezone(UTC), local_now.astimezone(UTC)
        if period == 'last_n_weeks':
            weeks = max(1, min(12, int(period_count or 2)))
            start = today_start - timedelta(days=weeks * 7 - 1)
            return start.astimezone(UTC), local_now.astimezone(UTC)

        start = today_start - timedelta(days=13)
        return start.astimezone(UTC), local_now.astimezone(UTC)

    @staticmethod
    def _normalize_lookup_text(value: str) -> str:
        return ' '.join(re.sub(r'[^a-z0-9]+', ' ', value.lower()).split())

    async def _account_names_for_user(self, user_id: uuid.UUID) -> dict[str, str]:
        accounts = await self.account_repository.list_for_user(user_id)
        return {str(account.id): account.name for account in accounts}

    async def _category_names_for_user(self, user_id: uuid.UUID) -> dict[str, str]:
        categories = await self.category_repository.list_for_user(user_id)
        return {str(category.id): category.name for category in categories}

    @staticmethod
    def _to_utc_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
