from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TransactionImportPreviewResponse(BaseModel):
    file_hash: str
    row_count: int
    valid_count: int
    already_imported: bool
    preview_rows: list[dict[str, Any]]
    errors: list[dict[str, Any]]


class TransactionImportCommitResponse(BaseModel):
    imported_count: int
