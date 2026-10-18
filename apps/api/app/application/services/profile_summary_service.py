from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass

from app.domain.entities import TransactionType
from app.domain.repositories import CategoryRepository, TransactionRepository


@dataclass
class ProfileSummaryService:
    transaction_repository: TransactionRepository
    category_repository: CategoryRepository

    async def summarize_latest(self, user_id: uuid.UUID) -> tuple[str, int]:
        transactions = await self.transaction_repository.list_recent_for_user(user_id, limit=5)
        count = len(transactions)
        if not count:
            return "Your money story is ready for its first entry. Add a transaction to get started.", 0

        expense_transactions = [item for item in transactions if item.type == TransactionType.EXPENSE]
        income_transactions = [
            item for item in transactions if item.type in {TransactionType.INCOME, TransactionType.REFUND}
        ]
        category_counts = Counter(item.category_id for item in expense_transactions if item.category_id is not None)
        if category_counts:
            category_id, appearances = category_counts.most_common(1)[0]
            if appearances >= 2:
                categories = await self.category_repository.list_for_user(user_id)
                category_name = next((item.name for item in categories if item.id == category_id), None)
                if category_name:
                    return (
                        f"{category_name} is having a moment: it shows up in {appearances} of your latest "
                        f"{count} transactions. Your wallet knows the plot.",
                        count,
                    )

        if expense_transactions and income_transactions:
            return "Money came in and went out in your latest entries. Your wallet has range.", count
        if income_transactions and not expense_transactions:
            return "Your latest entries have been a money-in montage. Nice plot twist.", count
        if expense_transactions:
            return "Your latest expenses are all accounted for. Your wallet is keeping excellent receipts.", count
        return "Your latest transactions have a story to tell. You're keeping the details close.", count
