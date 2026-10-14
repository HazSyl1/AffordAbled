from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import InjectedState

from app.domain.entities import CategoryType, TransactionType
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
            date_period: str = 'recent_default',
            period_count: int | None = None,
            timezone_name: str = 'UTC',
            category_hint: str | None = None,
            transaction_type: str = 'all',
            state: Annotated[dict[str, Any], InjectedState] | None = None,
        ) -> str:
            'Fetch recent user transactions for a finance query message.'
            runtime_state = state or {}
            user_id = uuid.UUID(str(runtime_state['runtime_user_id']))
            date_from, date_to = transaction_query_tools.resolve_date_window(
                message,
                timezone_name=timezone_name,
                date_period=date_period,
                period_count=period_count,
            )
            category, ambiguous_category = await transaction_query_tools.resolve_expense_category(
                user_id=user_id,
                message=message,
                category_hint=category_hint,
            )
            if ambiguous_category:
                reply = 'I found more than one matching expense category. Please specify which category.'
                return json.dumps(
                    {'reply': reply, 'insights': [], 'error': 'category_ambiguous', 'category_hint': category_hint},
                    ensure_ascii=False,
                )
            if category_hint and category is None:
                reply = f"I couldn't match '{category_hint}' to an expense category. Please check the category name."
                return json.dumps(
                    {'reply': reply, 'insights': [], 'error': 'category_not_found', 'category_hint': category_hint},
                    ensure_ascii=False,
                )
            try:
                normalized_transaction_type = (
                    None if transaction_type == 'all' else TransactionType(transaction_type)
                )
            except ValueError:
                return json.dumps(
                    {'reply': 'I could not apply that transaction filter.', 'error': 'invalid_transaction_type'},
                    ensure_ascii=False,
                )
            transactions = await transaction_query_tools.get_transactions(
                user_id=user_id,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                transaction_type=normalized_transaction_type,
                category_id=category.id if category is not None else None,
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
                occurred_on = _local_date_label(latest_transaction['occurred_at'], timezone_name)
                category_name = str(latest_transaction.get('category_name') or 'Uncategorized')
                category_scope = f' in {category.name}' if category is not None else ''
                reply = (
                    f'I found {len(transactions)} matching transactions. '
                    f'Latest: {occurred_on}, INR {amount_inr:.2f}, {merchant}, under {category_name}'
                    f'{category_scope}.'
                )
                insights = [
                    {
                        'title': 'Most recent transaction',
                        'detail': f'{merchant} in {category_name} on {occurred_on}.',
                    }
                ]

            return json.dumps(
                {
                    'reply': reply,
                    'insights': insights,
                    'facts': {
                        'query_kind': 'transaction_list',
                        'category': category.name if category is not None else None,
                        'date_from': _local_date_label(date_from.isoformat(), timezone_name),
                        'date_to': _local_date_label(date_to.isoformat(), timezone_name),
                        'transaction_count': len(transactions),
                        'transactions': [
                            {
                                'id': item['id'],
                                'occurred_at': item['occurred_at'],
                                'date': _local_date_label(item['occurred_at'], timezone_name),
                                'amount': f"INR {int(item['amount_paise']) / 100:,.2f}",
                                'merchant': item.get('merchant') or 'merchant not provided',
                                'category': item.get('category_name') or 'Uncategorized',
                                'type': item['type'],
                            }
                            for item in transactions
                        ],
                    },
                },
                ensure_ascii=False,
            )

        @tool('query_spending_summary')
        async def query_spending_summary(
            message: str,
            date_period: str = 'recent_default',
            period_count: int | None = None,
            timezone_name: str = 'UTC',
            category_hint: str | None = None,
            state: Annotated[dict[str, Any], InjectedState] | None = None,
        ) -> str:
            'Compute spending summary for the date window inferred from message.'
            runtime_state = state or {}
            user_id = uuid.UUID(str(runtime_state['runtime_user_id']))
            date_from, date_to = transaction_query_tools.resolve_date_window(
                message,
                timezone_name=timezone_name,
                date_period=date_period,
                period_count=period_count,
            )
            category, ambiguous_category = await transaction_query_tools.resolve_expense_category(
                user_id=user_id,
                message=message,
                category_hint=category_hint,
            )
            if ambiguous_category:
                reply = 'I found more than one matching expense category. Please specify the category name.'
                return json.dumps(
                    {
                        'reply': reply,
                        'insights': [{'title': 'Category needed', 'detail': reply}],
                        'error': 'category_ambiguous',
                        'category_hint': category_hint,
                    },
                    ensure_ascii=False,
                )
            if category_hint and category is None:
                reply = f"I couldn't match '{category_hint}' to an expense category. Please check the category name."
                return json.dumps(
                    {
                        'reply': reply,
                        'insights': [{'title': 'Category needed', 'detail': reply}],
                        'error': 'category_not_found',
                        'category_hint': category_hint,
                    },
                    ensure_ascii=False,
                )

            summary = await transaction_query_tools.get_spending_summary(
                user_id=user_id,
                date_from=date_from,
                date_to=date_to,
                category_id=category.id if category is not None else None,
            )

            total_spent_inr = summary['total_spent_paise'] / 100
            total_spent_display = f'INR {total_spent_inr:,.2f}'
            transaction_count = int(summary['transaction_count'])
            local_date_from = _local_date_label(date_from.isoformat(), timezone_name)
            local_date_to = _local_date_label(date_to.isoformat(), timezone_name)
            date_range = f'{local_date_from} to {local_date_to}'
            category_scope = f' on {category.name}' if category is not None else ''
            reply = (
                f'From {date_range}, you spent {total_spent_display}{category_scope} '
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
                        'detail': f'Analyzed {date_range}{category_scope}.',
                },
            ]
            return json.dumps(
                {
                    'reply': reply,
                    'insights': insights,
                    'facts': {
                        'query_kind': 'spending_summary',
                        'category': category.name if category is not None else None,
                        'date_from': local_date_from,
                        'date_to': local_date_to,
                        'total_spent_paise': summary['total_spent_paise'],
                        'total_spent_display': total_spent_display,
                        'transaction_count': transaction_count,
                        'average_spend_paise': (
                            summary['total_spent_paise'] // transaction_count if transaction_count else 0
                        ),
                        'average_spend_display': f'INR {average_spend_inr:,.2f}',
                    },
                },
                ensure_ascii=False,
            )

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


def _local_date_label(value: str, timezone_name: str) -> str:
    from datetime import datetime

    try:
        timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        timezone = ZoneInfo('UTC')
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo('UTC'))
    return parsed.astimezone(timezone).date().isoformat()
