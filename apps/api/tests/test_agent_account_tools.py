from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.application.dto import CreateAccountInput
from app.domain.entities import Account, AccountType
from app.infrastructure.ai.agents.account import AccountToolset
from app.infrastructure.ai.agents.contracts import HandoffContext


class RecordingAccountService:
    def __init__(self) -> None:
        self.created: CreateAccountInput | None = None

    async def create_account(self, data: CreateAccountInput) -> Account:
        self.created = data
        now = datetime.now(UTC)
        return Account(
            id=uuid.uuid4(),
            user_id=data.user_id,
            name=data.name,
            type=data.type,
            balance_paise=data.balance_paise,
            currency=data.currency,
            is_active=True,
            is_default=True,
            created_at=now,
            updated_at=now,
        )


@pytest.mark.asyncio
async def test_account_tool_converts_user_rupees_to_paise_and_defaults_to_bank() -> None:
    service = RecordingAccountService()
    user_id = uuid.uuid4()

    result = await AccountToolset(service).create_account(  # type: ignore[arg-type]
        HandoffContext(user_id=user_id, request="Create Axis with 6000 rupees"),
        {"name": "Axis", "balance_rupees": 6000},
    )

    assert service.created is not None
    assert service.created.name == "Axis"
    assert service.created.type == AccountType.BANK
    assert service.created.balance_paise == 600_000
    assert result["account"]["balance_paise"] == 600_000
