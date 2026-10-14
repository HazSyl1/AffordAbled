from datetime import datetime

from pydantic import BaseModel


class ExportDownloadUrlResponse(BaseModel):
    export_id: str
    download_url: str
    expires_at: datetime
