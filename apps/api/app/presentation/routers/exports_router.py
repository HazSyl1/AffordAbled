from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response

from app.application.services.export_service import ExportService
from app.core.dependencies import get_current_user, get_export_service
from app.domain.entities import User
from app.presentation.schemas.export import (
    CreateTransactionExportRequest,
    CreateTransactionExportResponse,
    ExportDownloadUrlResponse,
)

router = APIRouter(prefix='/exports', tags=['exports'])


@router.post('/transactions', response_model=CreateTransactionExportResponse)
async def create_transaction_export(
    payload: CreateTransactionExportRequest,
    current_user: User = Depends(get_current_user),
    export_service: ExportService = Depends(get_export_service),
) -> CreateTransactionExportResponse:
    artifact = await export_service.create_report(
        user_id=current_user.id,
        format=payload.format,
        date_from=payload.date_from,
        date_to=payload.date_to,
        timezone=payload.timezone,
    )
    return CreateTransactionExportResponse(
        export_id=str(artifact.id),
        download_url=artifact.download_url,
        expires_at=artifact.expires_at,
        filename=artifact.filename or f'transactions.{artifact.format}',
        row_count=artifact.row_count or 0,
    )


@router.get('/{export_id}/file')
async def download_export_file(
    export_id: uuid.UUID,
    token: str,
    export_service: ExportService = Depends(get_export_service),
) -> Response:
    artifact = await export_service.get_file(export_id=export_id, token=token)
    return Response(
        content=artifact.content,
        media_type=artifact.content_type or 'application/octet-stream',
        headers={
            'Content-Disposition': f'attachment; filename="{artifact.filename or "transactions"}"',
            'Cache-Control': 'private, no-store',
            'X-Content-Type-Options': 'nosniff',
        },
    )


@router.get('/{export_id}/download-url', response_model=ExportDownloadUrlResponse)
async def get_export_download_url(
    export_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    export_service: ExportService = Depends(get_export_service),
) -> ExportDownloadUrlResponse:
    export = await export_service.get_download_url(user_id=current_user.id, export_id=export_id)
    return ExportDownloadUrlResponse(
        export_id=str(export.id),
        download_url=export.download_url,
        expires_at=export.expires_at,
    )
