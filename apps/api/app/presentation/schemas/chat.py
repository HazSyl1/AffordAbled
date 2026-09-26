from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(default=None, min_length=1, max_length=120)


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


class ChatResponse(BaseModel):
    thread_id: str
    message: str
    pending_transaction_proposal: PendingTransactionProposalResponse | None = None
    transaction_logged: bool = False
    manual_transaction_input_required: bool = False


class VoiceTranscriptionResponse(BaseModel):
    transcript: str
    locale: str
