from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import InjectedState

from app.domain.entities import CategoryType
from app.infrastructure.ai.tools.category_tools import CategoryTools
from app.infrastructure.ai.tools.transaction_query_tools import TransactionQueryTools


@dataclass
class LangGraphFinanceTools:
    category_tools: CategoryTools
    transaction_query_tools: TransactionQueryTools

    def build_query_tools(self) -> list[BaseTool]:
        transaction_query_tools = self.transaction_query_tools

        @tool('query_transactions')
        async def query_transactions(
            message: str,
            limit: int = 5,
            state: Annotated[dict[str, Any], InjectedState] | None = None,
        ) -> str:
            'Fetch recent user transactions for a finance query message.'
            runtime_state = state or {}
            user_id = uuid.UUID(str(runtime_state['runtime_user_id']))
            date_from, date_to = transaction_query_tools.resolve_date_window(message)
            transactions = await transaction_query_tools.get_transactions(
                user_id=user_id,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )

            if not transactions:
                reply = 'No matching transactions found for that time range.'
                insights = [
                    {
                        'title': 'No transactions found',
                        'detail': 'Try a broader range like this month or last 30 days.',
                    }
                ]
            else:
                latest_transaction = transactions[0]
                merchant = latest_transaction.get('merchant') or 'merchant not provided'
                amount_inr = int(latest_transaction['amount_paise']) / 100
                occurred_on = str(latest_transaction['occurred_at'])[:10]
                category_name = str(latest_transaction.get('category_name') or 'Uncategorized')
                reply = (
                    f'I found {len(transactions)} matching transactions. '
                    f'Latest: {occurred_on}, INR {amount_inr:.2f}, {merchant}, under {category_name}.'
                )
                insights = [
                    {
                        'title': 'Most recent transaction',
                        'detail': f'{merchant} in {category_name} on {occurred_on}.',
                    }
                ]

            return json.dumps({'reply': reply, 'insights': insights}, ensure_ascii=False)

        @tool('query_spending_summary')
        async def query_spending_summary(
            message: str,
            state: Annotated[dict[str, Any], InjectedState] | None = None,
        ) -> str:
            'Compute spending summary for the date window inferred from message.'
            runtime_state = state or {}
            user_id = uuid.UUID(str(runtime_state['runtime_user_id']))
            date_from, date_to = transaction_query_tools.resolve_date_window(message)
            summary = await transaction_query_tools.get_spending_summary(
                user_id=user_id,
                date_from=date_from,
                date_to=date_to,
            )

            total_spent_inr = summary['total_spent_paise'] / 100
            transaction_count = int(summary['transaction_count'])
            date_range = f'{date_from.date().isoformat()} to {date_to.date().isoformat()}'
            reply = (
                f'From {date_range}, you spent INR {total_spent_inr:.2f} '
                f'in {transaction_count} transactions.'
            )
            average_spend_inr = (total_spent_inr / transaction_count) if transaction_count > 0 else 0.0
            insights = [
                {
                    'title': 'Average spend per transaction',
                    'detail': f'INR {average_spend_inr:.2f} in the selected range.',
                },
                {
                    'title': 'Spending window',
                    'detail': f'Analyzed {date_range}.',
                },
            ]
            return json.dumps({'reply': reply, 'insights': insights}, ensure_ascii=False)

        return [query_transactions, query_spending_summary]

    def build_category_tools(self) -> list[BaseTool]:
        category_tools = self.category_tools

        @tool('create_category')
        async def create_category(
            category_name: str,
            category_type: str,
            state: Annotated[dict[str, Any], InjectedState] | None = None,
        ) -> str:
            'Create a category for the current user if it does not exist.'
            runtime_state = state or {}
            user_id = uuid.UUID(str(runtime_state['runtime_user_id']))
            normalized_categories = _normalize_state_categories(runtime_state.get('user_categories'))

            try:
                normalized_type = CategoryType(category_type.strip().lower())
            except ValueError:
                return json.dumps({'ok': False, 'category': None, 'error': 'invalid_category_type'}, ensure_ascii=False)

            created = await category_tools.ensure_category_exists(
                user_id=user_id,
                category_name=category_name,
                category_type=normalized_type,
                existing_categories=normalized_categories,
            )
            return json.dumps({'ok': created is not None, 'category': created}, ensure_ascii=False)

        return [create_category]


def _normalize_state_categories(raw_categories: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_categories, list):
        return []

    normalized_categories: list[dict[str, Any]] = []
    for raw_category in raw_categories:
        if not isinstance(raw_category, dict):
            continue

        category_id = str(raw_category.get('id') or '').strip()
        category_name = str(raw_category.get('name') or '').strip()
        category_type = str(raw_category.get('type') or '').strip().lower()
        if not category_id or not category_name:
            continue
        if category_type not in {CategoryType.EXPENSE.value, CategoryType.INCOME.value}:
            continue

        normalized_categories.append(
            {
                'id': category_id,
                'name': category_name,
                'type': category_type,
            }
        )

    return normalized_categories
