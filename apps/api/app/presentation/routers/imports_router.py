from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.application.services.transaction_import_service import TransactionImportService
from app.core.dependencies import get_current_user, get_transaction_import_service
from app.domain.entities import User
from app.domain.exceptions import InvalidImportError
from app.infrastructure.files.transaction_import import MAX_IMPORT_BYTES
from app.presentation.schemas.transaction_import import (
    TransactionImportCommitResponse,
    TransactionImportPreviewResponse,
)

router = APIRouter(prefix='/imports', tags=['imports'])


async def _read_file(file: UploadFile) -> bytes:
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise InvalidImportError('The import file must be no larger than 10 MB.')
    return content


@router.post('/transactions/preview', response_model=TransactionImportPreviewResponse)
async def preview_transaction_import(
    file: UploadFile = File(...),
    timezone: str = Form(default='UTC'),
    current_user: User = Depends(get_current_user),
    import_service: TransactionImportService = Depends(get_transaction_import_service),
) -> TransactionImportPreviewResponse:
    validation = await import_service.preview(
        user_id=current_user.id,
        filename=file.filename or '',
        content=await _read_file(file),
        timezone=timezone,
    )
    return TransactionImportPreviewResponse(
        file_hash=validation.file_hash,
        row_count=validation.row_count,
        valid_count=validation.valid_count,
        already_imported=validation.already_imported,
        preview_rows=validation.preview_rows,
        errors=validation.errors,
    )


@router.post('/transactions/confirm', response_model=TransactionImportCommitResponse)
async def confirm_transaction_import(
    file: UploadFile = File(...),
    preview_hash: str = Form(...),
    timezone: str = Form(default='UTC'),
    current_user: User = Depends(get_current_user),
    import_service: TransactionImportService = Depends(get_transaction_import_service),
) -> TransactionImportCommitResponse:
    count = await import_service.commit(
        user_id=current_user.id,
        filename=file.filename or '',
        content=await _read_file(file),
        timezone=timezone,
        preview_hash=preview_hash,
    )
    return TransactionImportCommitResponse(imported_count=count)
