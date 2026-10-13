from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.application.services.export_service import ExportService
from app.core.dependencies import get_current_user, get_export_service
from app.domain.entities import User
from app.presentation.schemas.export import ExportDownloadUrlResponse

router = APIRouter(prefix='/exports', tags=['exports'])


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
