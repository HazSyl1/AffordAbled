from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.services.split_service import SplitService
from app.domain.entities import CategoryType, TransactionType
from app.infrastructure.ai.agents.contracts import HandoffContext
from app.infrastructure.ai.tools.transaction_query_tools import TransactionQueryTools


class AnalyticsToolset:
    def __init__(self, queries: TransactionQueryTools, split_service: SplitService | None = None) -> None:
        self._queries = queries
        self._splits = split_service

    def registry(self) -> dict[str, Any]:
        return {
            "get_account_balances": self.get_account_balances,
            "get_transactions": self.get_transactions,
            "get_spending_summary": self.get_spending_summary,
            "get_spending_by_account": self.get_spending_by_account,
            "get_spending_comparison": self.get_spending_comparison,
            "get_split_summary": self.get_split_summary,
        }

    async def get_split_summary(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        if self._splits is None:
            raise RuntimeError("split analytics is unavailable")
        splits = await self._splits.list_for_user(context.user_id)
        summaries = []
        total_outstanding = 0
        expense_split_outstanding = 0
        money_owed_outstanding = 0
        for split in splits:
            outstanding = sum(person.share_paise - person.settled_paise for person in split.participants)
            total_outstanding += outstanding
            if split.transaction_id is None:
                money_owed_outstanding += outstanding
            else:
                expense_split_outstanding += outstanding
            summaries.append({
                "id": str(split.id),
                "title": split.title,
                "kind": "expense_split" if split.transaction_id else "money_owed",
                "transaction_id": str(split.transaction_id) if split.transaction_id else None,
                "total_paise": split.owner_share_paise + sum(person.share_paise for person in split.participants),
                "outstanding_paise": outstanding,
                "created_at": split.created_at.isoformat() if getattr(split, 'created_at', None) else None,
                "participants": [
                    {"name": person.name, "share_paise": person.share_paise,
                     "settled_paise": person.settled_paise}
                    for person in split.participants
                ],
            })
        kind = str(args.get('kind') or 'all')
        status = str(args.get('status') or 'all')
        person_name = str(args.get('person_name') or '').strip().casefold()
        if kind != 'all':
            summaries = [item for item in summaries if item['kind'] == kind]
        if status == 'outstanding':
            summaries = [item for item in summaries if item['outstanding_paise'] > 0]
        elif status == 'settled':
            summaries = [item for item in summaries if item['outstanding_paise'] <= 0]
        if person_name:
            summaries = [
                item for item in summaries
                if any(person['name'].casefold() == person_name for person in item['participants'])
            ]
        order_by = str(args.get('order_by') or 'outstanding')
        sort_order = str(args.get('sort_order') or 'desc')
        if order_by == 'title':
            summaries.sort(key=lambda item: item['title'].casefold(), reverse=sort_order == 'desc')
        elif order_by == 'created_at':
            summaries.sort(key=lambda item: item['created_at'] or '', reverse=sort_order == 'desc')
        else:
            summaries.sort(key=lambda item: item['outstanding_paise'], reverse=sort_order == 'desc')
        total_matching_count = len(summaries)
        total_outstanding = sum(item['outstanding_paise'] for item in summaries)
        expense_split_outstanding = sum(
            item['outstanding_paise'] for item in summaries if item['kind'] == 'expense_split'
        )
        money_owed_outstanding = sum(
            item['outstanding_paise'] for item in summaries if item['kind'] == 'money_owed'
        )
        summaries = summaries[:max(1, min(int(args.get('limit') or 10), 25))]
        return {
            "split_count": len(summaries),
            "remaining_split_count": sum(item["outstanding_paise"] > 0 for item in summaries),
            "total_outstanding_paise": total_outstanding,
            "expense_split_outstanding_paise": expense_split_outstanding,
            "money_owed_outstanding_paise": money_owed_outstanding,
            "matching_split_count": total_matching_count,
            "truncated_split_count": max(0, total_matching_count - len(summaries)),
            "splits": summaries,
        }

    async def get_account_balances(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        query_arguments: dict[str, Any] = {
            'user_id': context.user_id,
            'account_names': args.get('account_names'),
        }
        for key in ('account_types', 'order_by', 'sort_order', 'limit'):
            if key in args:
                query_arguments[key] = args[key]
        return await self._queries.get_account_balances(**query_arguments)

    async def get_transactions(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        request_text = str(context.request or '')
        ranking_request = bool(re.search(
            r'\b(?:most|largest|highest|biggest|top|expensive|least|smallest|lowest|cheapest)\b',
            request_text,
            re.IGNORECASE,
        ))
        ascending_request = bool(re.search(
            r'\b(?:least|smallest|lowest|cheapest)\b', request_text, re.IGNORECASE
        ))
        relative_period = bool(re.search(
            r"\b(?:today|yesterday|this\s+(?:week|month)|last\s+(?:week|month)|\d+\s+(?:days?|weeks?))\b",
            request_text,
            re.IGNORECASE,
        ))
        mode = str(args.get('mode') or '').casefold()
        legacy_mode = not mode
        if not mode:
            original_request = str(
                context.constraints.get('latest_user_reply')
                or context.constraints.get('original_request')
                or context.request
            )
            mode = 'previous_window' if re.search(
                r"\b(?:before|earlier|prior|previous|preceding)\b", original_request, flags=re.IGNORECASE
            ) else 'recent'
        elif mode == 'recent' and context.constraints.get('last_transaction_window'):
            followup_text = str(
                context.constraints.get('latest_user_reply')
                or context.constraints.get('original_request')
                or context.request
            )
            if re.search(r"\b(?:before|earlier|prior|previous|preceding)\b", followup_text, flags=re.IGNORECASE):
                mode = 'previous_window'
        response_from: datetime | None = None
        response_to: datetime | None = None
        if mode == 'previous_window':
            date_from, date_to = self._resolve_relative_prior_window(context) or self._recent_sentinel()
        elif mode == 'date_range':
            if not args.get('date_from') or not args.get('date_to'):
                raise ValueError('date_from and date_to are required when mode is date_range')
            date_from, date_to = self._date(args['date_from']), self._date(args['date_to'])
        elif mode == 'all_time' or (mode == 'recent' and ranking_request and not relative_period):
            date_from, date_to = self._recent_sentinel()
        elif mode == 'relative_range' or (mode == 'recent' and relative_period):
            date_from, date_to = self._queries.resolve_date_window(
                request_text, timezone_name=context.timezone
            )
        elif mode == 'recent':
            response_from, response_to = self._queries.resolve_date_window(
                context.request, timezone_name=context.timezone
            )
            repository = getattr(self._queries, 'transaction_repository', None)
            if hasattr(repository, 'list_recent_for_user'):
                date_from, date_to = self._recent_sentinel()
            else:
                date_from, date_to = response_from, response_to
        elif legacy_mode:
            date_from, date_to = self._queries.resolve_date_window(context.request, timezone_name=context.timezone)
        else:
            raise ValueError(f'Unsupported transaction query mode: {mode}')
        raw_transaction_type = args.get('transaction_type')
        if raw_transaction_type:
            transaction_type = TransactionType(str(raw_transaction_type))
        elif ranking_request and re.search(r'\b(?:spend|spent|expense|purchase)\b', request_text, re.IGNORECASE):
            transaction_type = TransactionType.EXPENSE
        else:
            transaction_type = None
        order_by = str(args.get('order_by') or ('amount' if ranking_request else 'occurred_at'))
        sort_order = str(args.get('sort_order') or ('asc' if ascending_request else 'desc'))
        limit = int(args.get('limit') or (1 if ranking_request else 10))
        query_arguments: dict[str, Any] = {
            "user_id": context.user_id,
            "date_from": date_from,
            "date_to": date_to,
            "limit": limit,
        }
        if transaction_type is not None:
            query_arguments["transaction_type"] = transaction_type
        category_name = str(args.get('category_name') or '').strip()
        if category_name:
            category_type = {
                TransactionType.EXPENSE: CategoryType.EXPENSE,
                TransactionType.INCOME: CategoryType.INCOME,
            }.get(transaction_type)
            query_arguments['category_id'] = await self._queries.resolve_category_id(
                user_id=context.user_id, category_name=category_name, category_type=category_type,
            )
        account_name = str(args.get('account_name') or '').strip()
        if account_name:
            query_arguments['account_id'] = await self._queries.resolve_account_id(
                user_id=context.user_id, account_name=account_name,
            )
        if order_by != "occurred_at" or sort_order != "desc":
            query_arguments["order_by"] = order_by
            query_arguments["sort_order"] = sort_order
        transactions = await self._queries.get_transactions(**query_arguments)
        if response_from is None or response_to is None:
            response_from, response_to = date_from, date_to
        if date_from.year <= 1970 and transactions:
            occurred_at = [
                datetime.fromisoformat(str(item['occurred_at']))
                for item in transactions
                if item.get('occurred_at')
            ]
            if occurred_at:
                response_from, response_to = min(occurred_at), max(occurred_at)
        return {
            "transactions": transactions,
            "date_from": response_from.isoformat(),
            "date_to": response_to.isoformat(),
            "order_by": order_by,
            "sort_order": sort_order,
            "transaction_type": transaction_type.value if transaction_type else None,
        }

    @staticmethod
    def _resolve_relative_prior_window(context: HandoffContext) -> tuple[datetime, datetime] | None:
        """Move an earlier-transactions follow-up behind the last verified query window."""
        original_request = str(
            context.constraints.get("latest_user_reply")
            or context.constraints.get("original_request")
            or context.request
        )
        if not re.search(r"\b(?:before|earlier|prior|previous|preceding)\b", original_request, flags=re.IGNORECASE):
            return None
        window = context.constraints.get("last_transaction_window")
        if not isinstance(window, dict) or not window.get("date_from") or not window.get("date_to"):
            return None
        previous_start = datetime.fromisoformat(str(window["date_from"]))
        previous_end = datetime.fromisoformat(str(window["date_to"]))
        if previous_start.tzinfo is None or previous_end.tzinfo is None or previous_end < previous_start:
            raise ValueError("The previous transaction window is invalid. Ask for a date range.")
        prior_end = previous_start - timedelta(microseconds=1)
        prior_start = prior_end - (previous_end - previous_start)
        return prior_start, prior_end

    @staticmethod
    def _recent_sentinel() -> tuple[datetime, datetime]:
        return datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC)

    def _spending_window(self, context: HandoffContext, args: dict[str, Any]) -> tuple[datetime, datetime]:
        """Resolve relative periods in code while preserving explicit model-supplied ranges."""
        mode = str(args.get('mode') or 'relative_range')
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        if bool(date_from) != bool(date_to):
            raise ValueError("Provide both date_from and date_to, or omit both for a relative period.")
        if date_from and date_to:
            return self._date(date_from), self._date(date_to)
        if mode == 'date_range':
            raise ValueError('date_from and date_to are required when mode is date_range')
        if mode == 'all_time':
            return self._recent_sentinel()
        return self._queries.resolve_date_window(context.request, timezone_name=context.timezone)

    async def _expense_category_id(self, context: HandoffContext, args: dict[str, Any]) -> uuid.UUID | None:
        category_name = str(args.get('category_name') or '').strip()
        if not category_name:
            return None
        category, ambiguous = await self._queries.resolve_expense_category(
            user_id=context.user_id, category_hint=category_name,
        )
        if ambiguous:
            raise ValueError(f'Expense category is ambiguous: {category_name}')
        if category is None:
            raise ValueError(f'Expense category was not found: {category_name}')
        return category.id

    async def get_spending_summary(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        date_from, date_to = self._spending_window(context, args)
        if args.get('order_by') == 'transaction_count':
            raise ValueError('get_spending_summary supports order_by amount or name')
        query_arguments: dict[str, Any] = {
            'user_id': context.user_id,
            'date_from': date_from,
            'date_to': date_to,
        }
        category_id = await self._expense_category_id(context, args)
        if category_id is not None:
            query_arguments['category_id'] = category_id
        for key in ('order_by', 'sort_order', 'limit'):
            if key in args:
                query_arguments[key] = args[key]
        return await self._queries.get_spending_summary(**query_arguments)

    async def get_spending_by_account(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        date_from, date_to = self._spending_window(context, args)
        query_arguments: dict[str, Any] = {
            'user_id': context.user_id,
            'date_from': date_from,
            'date_to': date_to,
            'limit': int(args.get('limit', 10)),
        }
        category_id = await self._expense_category_id(context, args)
        if category_id is not None:
            query_arguments['category_id'] = category_id
        for key in ('account_names', 'order_by', 'sort_order'):
            if key in args:
                query_arguments[key] = args[key]
        return await self._queries.get_spending_by_account(**query_arguments)

    async def get_spending_comparison(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        """Compare two supported, matching spending windows for the authenticated user.

        The specialist deliberately supplies named periods rather than calculating dates itself;
        the query layer owns timezone-aware window resolution and the allowed period pairs.
        """
        date_period = args.get("date_period")
        comparison_period = args.get("comparison_period")
        if not isinstance(date_period, str) or not isinstance(comparison_period, str):
            raise ValueError("date_period and comparison_period are required strings")

        current_from, current_to, comparison_from, comparison_to = self._queries.resolve_spending_comparison_windows(
            date_period=date_period,
            comparison_period=comparison_period,
            timezone_name=context.timezone,
        )
        return await self._queries.get_spending_comparison(
            user_id=context.user_id,
            current_date_from=current_from,
            current_date_to=current_to,
            comparison_date_from=comparison_from,
            comparison_date_to=comparison_to,
            category_id=await self._expense_category_id(context, args),
        )

    @staticmethod
    def _date(value: Any) -> datetime:
        return datetime.fromisoformat(str(value))
