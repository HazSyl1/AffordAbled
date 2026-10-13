from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.entities import CategoryType, TransactionType
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

    @staticmethod
    def resolve_date_window(message: str, *, now_utc: datetime | None = None) -> tuple[datetime, datetime]:
        anchor_now = now_utc or datetime.now(UTC)
        normalized_message = ' '.join(message.lower().split())

        weeks_match = re.search(r'\b(\d{1,2})\s+weeks?\b', normalized_message)
        if weeks_match:
            weeks = max(1, min(12, int(weeks_match.group(1))))
            return anchor_now - timedelta(weeks=weeks), anchor_now

        days_match = re.search(r'\b(\d{1,3})\s+days?\b', normalized_message)
        if days_match:
            days = max(1, min(180, int(days_match.group(1))))
            return anchor_now - timedelta(days=days), anchor_now

        if 'yesterday' in normalized_message:
            start = (anchor_now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = (anchor_now - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)
            return start, end

        if 'today' in normalized_message:
            start = anchor_now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = anchor_now
            return start, end

        return anchor_now - timedelta(days=14), anchor_now

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
