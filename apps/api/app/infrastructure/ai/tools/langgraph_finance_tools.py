from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
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
            requested_limit = max(1, min(int(limit), 10))
            transactions = await transaction_query_tools.get_transactions(
                user_id=user_id,
                date_from=date_from,
                date_to=date_to,
                limit=requested_limit + 1,
                transaction_type=normalized_transaction_type,
                category_id=category.id if category is not None else None,
            )
            has_more = len(transactions) > requested_limit
            transactions = transactions[:requested_limit]

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
                count_qualifier = 'at least ' if has_more else ''
                reply = (
                    f'I found {count_qualifier}{len(transactions)} matching transactions. '
                    f'Latest: {occurred_on}, INR {amount_inr:.2f}, {merchant}, under {category_name}'
                    f'{category_scope}.'
                    + (
                        f' Showing the {len(transactions)} most recent; more matching transactions exist.'
                        if has_more
                        else ''
                    )
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
                        'has_more': has_more,
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

            total_spent_inr = Decimal(int(summary['total_spent_paise'])) / Decimal(100)
            total_spent_display = _format_paise(int(summary['total_spent_paise']))
            transaction_count = int(summary['transaction_count'])
            local_date_from = _local_date_label(date_from.isoformat(), timezone_name)
            local_date_to = _local_date_label(date_to.isoformat(), timezone_name)
            date_range = f'{local_date_from} to {local_date_to}'
            category_scope = f' on {category.name}' if category is not None else ''
            reply = (
                f'From {date_range}, you spent {total_spent_display}{category_scope} '
                f'in {transaction_count} transactions.'
            )
            average_spend_inr = (total_spent_inr / transaction_count) if transaction_count > 0 else Decimal(0)
            average_spend_display = f"INR {average_spend_inr.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"
            insights = [
                {
                    'title': 'Average spend per transaction',
                    'detail': f'{average_spend_display} in the selected range.',
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
                        'top_categories': [
                            {
                                'name': str(item['category_name']),
                                'total_spent_paise': int(item['amount_paise']),
                                'total_spent_display': _format_paise(int(item['amount_paise'])),
                            }
                            for item in summary['top_categories']
                        ],
                        'category_count': int(summary['category_count']),
                        'truncated_category_count': int(summary['truncated_category_count']),
                        'average_spend_paise': (
                            summary['total_spent_paise'] // transaction_count if transaction_count else 0
                        ),
                        'average_spend_display': average_spend_display,
                    },
                },
                ensure_ascii=False,
            )

        @tool('query_spending_comparison')
        async def query_spending_comparison(
            message: str,
            date_period: str,
            comparison_period: str,
            timezone_name: str = 'UTC',
            category_hint: str | None = None,
            state: Annotated[dict[str, Any], InjectedState] | None = None,
        ) -> str:
            'Compare user-scoped spending for supported matching month-to-date or week-to-date periods.'
            runtime_state = state or {}
            user_id = uuid.UUID(str(runtime_state['runtime_user_id']))
            try:
                current_from, current_to, comparison_from, comparison_to = (
                    transaction_query_tools.resolve_spending_comparison_windows(
                        date_period=date_period,
                        comparison_period=comparison_period,
                        timezone_name=timezone_name,
                    )
                )
            except ValueError:
                return json.dumps(
                    {'error': 'unsupported_comparison_period', 'category_hint': category_hint},
                    ensure_ascii=False,
                )

            category, ambiguous_category = await transaction_query_tools.resolve_expense_category(
                user_id=user_id,
                message=message,
                category_hint=category_hint,
            )
            if ambiguous_category:
                return json.dumps(
                    {
                        'error': 'category_ambiguous',
                        'category_hint': category_hint,
                        'reply': 'I found more than one matching expense category. Please specify the category.',
                    },
                    ensure_ascii=False,
                )
            if category_hint and category is None:
                return json.dumps(
                    {
                        'error': 'category_not_found',
                        'category_hint': category_hint,
                        'reply': f"I couldn't match '{category_hint}' to an expense category.",
                    },
                    ensure_ascii=False,
                )

            result = await transaction_query_tools.get_spending_comparison(
                user_id=user_id,
                current_date_from=current_from,
                current_date_to=current_to,
                comparison_date_from=comparison_from,
                comparison_date_to=comparison_to,
                category_id=category.id if category is not None else None,
            )
            current = result['current']
            previous = result['comparison']
            current_total = int(current['total_spent_paise'])
            previous_total = int(previous['total_spent_paise'])
            delta = int(result['delta_paise'])
            percent_change = result['percent_change']
            category_name = category.name if category is not None else None
            current_from_label = _local_date_label(current_from.isoformat(), timezone_name)
            current_to_label = _local_date_label(current_to.isoformat(), timezone_name)
            previous_from_label = _local_date_label(comparison_from.isoformat(), timezone_name)
            previous_to_label = _local_date_label(comparison_to.isoformat(), timezone_name)
            facts = {
                'query_kind': 'spending_comparison',
                'category': category_name,
                'current_period': {
                    'name': 'this month' if date_period == 'this_month' else 'this week',
                    'date_from': current_from_label,
                    'date_to': current_to_label,
                    'total_spent_paise': current_total,
                    'total_spent_display': f'INR {current_total / 100:,.2f}',
                    'transaction_count': int(current['transaction_count']),
                },
                'comparison_period': {
                    'name': (
                        'matching dates last month'
                        if comparison_period == 'last_month'
                        else 'matching days last week'
                    ),
                    'date_from': previous_from_label,
                    'date_to': previous_to_label,
                    'total_spent_paise': previous_total,
                    'total_spent_display': f'INR {previous_total / 100:,.2f}',
                    'transaction_count': int(previous['transaction_count']),
                },
                'delta_paise': delta,
                'delta_display': _format_paise(abs(delta)),
                'percent_change': percent_change,
                'direction': result['direction'],
            }
            return json.dumps(
                {
                    'reply': '',
                    'insights': [],
                    'facts': facts,
                },
                ensure_ascii=False,
            )

        @tool('query_account_balances')
        async def query_account_balances(
            account_names: list[str] | None = None,
            state: Annotated[dict[str, Any], InjectedState] | None = None,
        ) -> str:
            'Read balances for the authenticated user’s active accounts; never recompute them from transactions.'
            runtime_state = state or {}
            user_id = uuid.UUID(str(runtime_state['runtime_user_id']))
            result = await transaction_query_tools.get_account_balances(
                user_id=user_id,
                account_names=account_names,
            )
            status = str(result.get('status') or 'failed')
            if status == 'not_found':
                return json.dumps(
                    {
                        'error': 'account_not_found',
                        'requested_account': result.get('requested_account'),
                        'reply': f"I couldn't find an active account named '{result.get('requested_account')}'.",
                    },
                    ensure_ascii=False,
                )
            if status == 'ambiguous':
                return json.dumps(
                    {
                        'error': 'account_ambiguous',
                        'requested_account': result.get('requested_account'),
                        'reply': (
                            f"More than one active account matches '{result.get('requested_account')}'. "
                            'Please specify the exact name.'
                        ),
                    },
                    ensure_ascii=False,
                )
            accounts = result.get('accounts') or []
            facts = {
                'query_kind': 'account_balance',
                'account_count': int(result.get('account_count') or len(accounts)),
                'truncated_account_count': int(result.get('truncated_account_count') or 0),
                'accounts': accounts,
            }
            return json.dumps({'reply': '', 'insights': [], 'facts': facts}, ensure_ascii=False)

        @tool('query_spending_by_account')
        async def query_spending_by_account(
            message: str,
            date_period: str = 'recent_default',
            period_count: int | None = None,
            timezone_name: str = 'UTC',
            category_hint: str | None = None,
            state: Annotated[dict[str, Any], InjectedState] | None = None,
        ) -> str:
            'Group database-derived expense totals by the authenticated user’s active account, returning at most 10.'
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
                return json.dumps(
                    {
                        'error': 'category_ambiguous',
                        'category_hint': category_hint,
                        'reply': 'I found more than one matching expense category. Please specify the category.',
                    },
                    ensure_ascii=False,
                )
            if category_hint and category is None:
                return json.dumps(
                    {
                        'error': 'category_not_found',
                        'category_hint': category_hint,
                        'reply': f"I couldn't match '{category_hint}' to an expense category.",
                    },
                    ensure_ascii=False,
                )

            summary = await transaction_query_tools.get_spending_by_account(
                user_id=user_id,
                date_from=date_from,
                date_to=date_to,
                category_id=category.id if category is not None else None,
                limit=10,
            )
            facts = {
                'query_kind': 'spending_by_account',
                'category': category.name if category is not None else None,
                'date_from': _local_date_label(date_from.isoformat(), timezone_name),
                'date_to': _local_date_label(date_to.isoformat(), timezone_name),
                **summary,
                'accounts': [
                    {
                        **item,
                        'total_spent_display': _format_paise(int(item['total_spent_paise'])),
                    }
                    for item in summary['accounts']
                ],
            }
            return json.dumps({'reply': '', 'insights': [], 'facts': facts}, ensure_ascii=False)

        return [
            query_transactions,
            query_spending_summary,
            query_spending_comparison,
            query_account_balances,
            query_spending_by_account,
        ]

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


def _format_paise(amount_paise: int) -> str:
    amount = (Decimal(int(amount_paise)) / Decimal(100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return f'INR {amount:,.2f}'
