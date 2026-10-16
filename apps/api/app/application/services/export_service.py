from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jwt

from app.domain.entities import ExportArtifact
from app.domain.exceptions import ExportLinkExpiredError, ExportNotFoundError, InvalidExportError
from app.domain.repositories import (
    AccountRepository,
    CategoryRepository,
    ExportArtifactRepository,
    TransactionRepository,
)
from app.infrastructure.files.transaction_report import CONTENT_TYPES, ReportRow, render_csv, render_pdf, render_xlsx

MAX_EXPORT_ROWS = 50_000
MAX_EXPORT_BYTES = 20 * 1024 * 1024


@dataclass
class ExportService:
    export_artifact_repository: ExportArtifactRepository
    transaction_repository: TransactionRepository
    account_repository: AccountRepository
    category_repository: CategoryRepository
    signing_key: str

    async def create_report(
        self,
        *,
        user_id: uuid.UUID,
        format: str,
        date_from: date | None = None,
        date_to: date | None = None,
        timezone: str = 'UTC',
    ) -> ExportArtifact:
        if format not in CONTENT_TYPES:
            raise InvalidExportError('Choose CSV, XLSX, or PDF.')
        if date_from and date_to and date_from > date_to:
            raise InvalidExportError('The start date must be on or before the end date.')
        try:
            user_timezone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise InvalidExportError('Invalid timezone.') from exc

        from_utc = (
            datetime.combine(date_from, time.min, tzinfo=user_timezone).astimezone(UTC) if date_from else None
        )
        to_utc = (
            datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=user_timezone).astimezone(UTC)
            if date_to and date_to < date.max else None
        )
        transactions = await self.transaction_repository.list_for_export(
            user_id, date_from=from_utc, date_to=to_utc, limit=MAX_EXPORT_ROWS + 1
        )
        if len(transactions) > MAX_EXPORT_ROWS:
            raise InvalidExportError('This report is too large. Choose a shorter date range.')
        accounts = {account.id: account.name for account in await self.account_repository.list_for_user(user_id)}
        categories = {category.id: category.name for category in await self.category_repository.list_for_user(user_id)}
        rows = []
        for transaction in transactions:
            occurred_at = transaction.occurred_at.astimezone(user_timezone)
            if date_from and occurred_at.date() < date_from:
                continue
            if date_to and occurred_at.date() > date_to:
                continue
            rows.append(
                ReportRow(
                    transaction_id=str(transaction.id),
                    occurred_at=occurred_at,
                    type=transaction.type.value,
                    amount_paise=transaction.amount_paise,
                    account=accounts.get(transaction.account_id, ''),
                    category=categories.get(transaction.category_id, '') if transaction.category_id else '',
                    to_account=accounts.get(transaction.to_account_id, '') if transaction.to_account_id else '',
                    merchant=transaction.merchant or '',
                )
            )
        rows.sort(key=lambda item: (item.occurred_at, item.transaction_id), reverse=True)
        renderer = {'csv': render_csv, 'xlsx': render_xlsx, 'pdf': render_pdf}[format]
        content = renderer(rows)
        if len(content) > MAX_EXPORT_BYTES:
            raise InvalidExportError('This report is too large. Choose a shorter date range.')

        now = datetime.now(UTC)
        artifact_id = uuid.uuid4()
        artifact = ExportArtifact(
            id=artifact_id,
            user_id=user_id,
            format=format,
            download_url=f'/api/v1/exports/{artifact_id}/file',
            expires_at=now + timedelta(hours=24),
            created_at=now,
            content=content,
            content_type=CONTENT_TYPES[format],
            filename=f'affordabled-transactions-{now:%Y%m%d-%H%M%S}.{format}',
            row_count=len(rows),
            report_schema_version=2,
            file_sha256=hashlib.sha256(content).hexdigest(),
        )
        await self.export_artifact_repository.create(artifact)
        return self._with_signed_url(artifact)

    async def get_download_url(self, *, user_id: uuid.UUID, export_id: uuid.UUID) -> ExportArtifact:
        export = await self._active_export(user_id, export_id)
        return self._with_signed_url(export) if export.content is not None else export

    async def get_file(self, *, export_id: uuid.UUID, token: str) -> ExportArtifact:
        try:
            claims = jwt.decode(token, self.signing_key, algorithms=['HS256'])
            if claims.get('purpose') != 'export_download' or claims.get('export_id') != str(export_id):
                raise ExportNotFoundError('Export not found')
            user_id = uuid.UUID(str(claims['sub']))
        except (jwt.InvalidTokenError, ValueError, KeyError, TypeError) as exc:
            raise ExportNotFoundError('Export not found') from exc
        artifact = await self._active_export(user_id, export_id)
        if artifact.content is None:
            raise ExportNotFoundError('Export file not found')
        return artifact

    async def _active_export(self, user_id: uuid.UUID, export_id: uuid.UUID) -> ExportArtifact:
        export = await self.export_artifact_repository.get_for_user(user_id, export_id)
        if export is None:
            raise ExportNotFoundError(f'Export not found: {export_id}')
        if export.content is not None and export.report_schema_version != 2:
            raise ExportLinkExpiredError('This report uses an older format. Generate a new export.')

        expires_at = (
            export.expires_at
            if export.expires_at.tzinfo is not None
            else export.expires_at.replace(tzinfo=UTC)
        )
        if expires_at <= datetime.now(UTC):
            raise ExportLinkExpiredError('Export download link has expired')

        return export

    def _with_signed_url(self, export: ExportArtifact) -> ExportArtifact:
        token = jwt.encode(
            {
                'sub': str(export.user_id),
                'export_id': str(export.id),
                'purpose': 'export_download',
                'exp': datetime.now(UTC) + timedelta(minutes=5),
            },
            self.signing_key,
            algorithm='HS256',
        )
        return replace(export, download_url=f'/api/v1/exports/{export.id}/file?token={token}')
