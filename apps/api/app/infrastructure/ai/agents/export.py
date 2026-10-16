from __future__ import annotations

import re
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from app.application.services.export_service import ExportService
from app.infrastructure.ai.agents.contracts import HandoffContext
from app.infrastructure.ai.tools.transaction_query_tools import TransactionQueryTools


class ExportToolset:
    def __init__(self, service: ExportService) -> None:
        self._service = service

    def registry(self) -> dict[str, Any]:
        return {'create_transaction_report': self.create_transaction_report}

    async def create_transaction_report(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        """Create a downloadable transaction report for this user.

        Call when the user asks to export or download transactions. Use format csv, xlsx,
        or pdf (default pdf). Pass ISO local dates only when the user supplies explicit dates.
        Relative ranges such as last month and recent are resolved from the request.
        The tool scopes records to the authenticated user and returns a report ID.
        """
        format_name = str(args.get('format') or 'pdf').strip().lower()
        try:
            date_from = date.fromisoformat(str(args['date_from'])) if args.get('date_from') else None
            date_to = date.fromisoformat(str(args['date_to'])) if args.get('date_to') else None
        except ValueError as exc:
            raise ValueError('Use ISO dates (YYYY-MM-DD) for the report range.') from exc
        if date_from is None and date_to is None and re.search(
            r'\b(?:recent|latest|today|yesterday|this week|last week|this month|last month|\d+ days?|\d+ weeks?)\b',
            context.request,
            flags=re.IGNORECASE,
        ):
            start, end = TransactionQueryTools.resolve_date_window(
                context.request, timezone_name=context.timezone
            )
            local_timezone = ZoneInfo(context.timezone)
            date_from, date_to = start.astimezone(local_timezone).date(), end.astimezone(local_timezone).date()
        artifact = await self._service.create_report(
            user_id=context.user_id,
            format=format_name,
            date_from=date_from,
            date_to=date_to,
            timezone=context.timezone,
        )
        return {
            'export_id': str(artifact.id),
            'filename': artifact.filename,
            'format': artifact.format,
            'row_count': artifact.row_count,
            'expires_at': artifact.expires_at.isoformat(),
        }
