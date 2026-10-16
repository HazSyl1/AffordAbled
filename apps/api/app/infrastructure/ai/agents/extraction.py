from __future__ import annotations

from decimal import Decimal
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.infrastructure.ai.agents.contracts import HandoffContext


class TransactionCandidate(BaseModel):
    transaction_type: str | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    account_hint: str | None = None
    category_hint: str | None = None
    occurred_at: str | None = None
    merchant: str | None = None
    note: str | None = None
    missing_fields: list[str] = Field(default_factory=list)


class TransactionExtractionAgent:
    """A transaction-specialist-only sub-agent; it has no domain tools."""

    def __init__(self, llm: Any) -> None:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "Extract a transaction candidate from the request. Never invent values; list missing fields.",
                ),
                ("human", "Request: {request}\nTimezone: {timezone}"),
            ]
        )
        self._chain = prompt | llm.with_structured_output(TransactionCandidate, method="function_calling")

    async def extract(self, context: HandoffContext, _arguments: dict[str, Any]) -> dict[str, Any]:
        candidate = await self._chain.ainvoke({"request": context.request, "timezone": context.timezone})
        return candidate.model_dump(mode="json")
