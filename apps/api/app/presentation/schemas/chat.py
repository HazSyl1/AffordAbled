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
    manual_transaction_input_required: bool = False
    insights: list[ChatInsightResponse] | None = None


class VoiceTranscriptionResponse(BaseModel):
    transcript: str
    locale: str


class ImageAnalysisResponse(BaseModel):
    extracted_text: str
    prompt: str
