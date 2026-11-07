import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    thread_id: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)


class PendingTransactionProposalResponse(BaseModel):
    type: str
    amount_paise: int
    occurred_at: str
    account_id: str
    account_name: str
    category_id: str
    category_name: str
    confidence_score: int = Field(ge=0, le=100)
    merchant: str | None = None
    note: str | None = None


class ChatInsightResponse(BaseModel):
    title: str
    detail: str


class ChatResponse(BaseModel):
    thread_id: str
    message: str
    tasks_completed: bool = False
    show_completion_popup: bool = False
    pending_transaction_proposal: PendingTransactionProposalResponse | None = None
    pending_transaction_proposals: list[PendingTransactionProposalResponse] | None = None
    transaction_logged: bool = False
    created_transaction_id: str | None = None
    created_split_ids: list[str] = Field(default_factory=list)
    manual_transaction_input_required: bool = False
    insights: list[ChatInsightResponse] | None = None


class ChatTurnSubmitRequest(BaseModel):
    turn_id: uuid.UUID
    thread_id: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=8000)
    timezone: str = Field(default='UTC', min_length=1, max_length=64)


class ChatTurnStatusResponse(BaseModel):
    turn_id: uuid.UUID
    thread_id: str
    status: Literal['queued', 'processing', 'succeeded', 'failed']
    result: ChatResponse | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class VoiceTranscriptionResponse(BaseModel):
    transcript: str
    locale: str


class ImageAnalysisResponse(BaseModel):
    extracted_text: str
    prompt: str
