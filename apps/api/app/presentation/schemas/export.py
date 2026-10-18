from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class CreateTransactionExportRequest(BaseModel):
    format: Literal['csv', 'xlsx', 'pdf']
    date_from: date | None = None
    date_to: date | None = None
    timezone: str = Field(default='UTC', max_length=80)


class CreateTransactionExportResponse(BaseModel):
    export_id: str
    download_url: str
    expires_at: datetime
    filename: str
    row_count: int


class ExportDownloadUrlResponse(BaseModel):
    export_id: str
    download_url: str
    expires_at: datetime
