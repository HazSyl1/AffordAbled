from pydantic import BaseModel


class VoiceTranscriptionResponse(BaseModel):
    transcript: str
    locale: str
