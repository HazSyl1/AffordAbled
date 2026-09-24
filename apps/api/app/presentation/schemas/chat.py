from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(default=None, min_length=1, max_length=120)


class ChatResponse(BaseModel):
    thread_id: str
    message: str


class VoiceTranscriptionResponse(BaseModel):
    transcript: str
    locale: str
