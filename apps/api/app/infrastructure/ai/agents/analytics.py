from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from app.infrastructure.ai.agents.contracts import HandoffContext
from app.infrastructure.ai.tools.transaction_query_tools import TransactionQueryTools


class AnalyticsToolset:
    def __init__(self, queries: TransactionQueryTools) -> None:
        self._queries = queries

    def registry(self) -> dict[str, Any]:
        return {
            "get_account_balances": self.get_account_balances,
            "get_transactions": self.get_transactions,
            "get_spending_summary": self.get_spending_summary,
            "get_spending_by_account": self.get_spending_by_account,
            "get_spending_comparison": self.get_spending_comparison,
        }

    async def get_account_balances(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        return await self._queries.get_account_balances(
            user_id=context.user_id, account_names=args.get("account_names")
        )

    async def get_transactions(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        relative_prior_window = self._resolve_relative_prior_window(context)
        if relative_prior_window is not None:
            date_from, date_to = relative_prior_window
        elif re.search(r"\b(?:recent|latest)\b", context.request, flags=re.IGNORECASE) or not (
            args.get("date_from") and args.get("date_to")
        ):
            date_from, date_to = self._queries.resolve_date_window(context.request, timezone_name=context.timezone)
        else:
            date_from, date_to = self._date(args["date_from"]), self._date(args["date_to"])
        return {
            "transactions": await self._queries.get_transactions(
                user_id=context.user_id,
                date_from=date_from,
                date_to=date_to,
                limit=int(args.get("limit", 10)),
            ),
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        }

    @staticmethod
    def _resolve_relative_prior_window(context: HandoffContext) -> tuple[datetime, datetime] | None:
        """Move an earlier-transactions follow-up behind the last verified query window."""
        original_request = str(context.constraints.get("original_request") or context.request)
        if not re.search(r"\b(?:before|earlier|prior|previous|preceding)\b", original_request, flags=re.IGNORECASE):
            return None
        window = context.constraints.get("last_transaction_window")
        if not isinstance(window, dict) or not window.get("date_from") or not window.get("date_to"):
            raise ValueError("No earlier transaction window is available in this chat. Ask for a date range.")
        previous_start = datetime.fromisoformat(str(window["date_from"]))
        previous_end = datetime.fromisoformat(str(window["date_to"]))
        if previous_start.tzinfo is None or previous_end.tzinfo is None or previous_end < previous_start:
            raise ValueError("The previous transaction window is invalid. Ask for a date range.")
        prior_end = previous_start - timedelta(microseconds=1)
        prior_start = prior_end - (previous_end - previous_start)
        return prior_start, prior_end

    async def get_spending_summary(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        return await self._queries.get_spending_summary(
            user_id=context.user_id,
            date_from=self._date(args["date_from"]),
            date_to=self._date(args["date_to"]),
        )

    async def get_spending_by_account(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        return await self._queries.get_spending_by_account(
            user_id=context.user_id,
            date_from=self._date(args["date_from"]),
            date_to=self._date(args["date_to"]),
            limit=int(args.get("limit", 10)),
        )

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
        )

    @staticmethod
    def _date(value: Any) -> datetime:
        return datetime.fromisoformat(str(value))
