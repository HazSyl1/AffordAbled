from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.application.services.complex_settlement import SettlementInput


class ComplexSettlementStore(Protocol):
    async def create_draft(self, user_id: uuid.UUID, request_key: str, data: SettlementInput,
                           revision_plan_id: uuid.UUID | None = None): ...
    async def get_draft(self, user_id: uuid.UUID, draft_id: uuid.UUID): ...
    async def update_draft(self, user_id: uuid.UUID, draft_id: uuid.UUID, version: int, data: SettlementInput): ...
    async def confirm(self, user_id: uuid.UUID, draft_id: uuid.UUID, version: int): ...
    async def list_plans(self, user_id: uuid.UUID): ...
    async def get_plan(self, user_id: uuid.UUID, plan_id: uuid.UUID): ...
    async def settle_transfer(self, user_id: uuid.UUID, plan_id: uuid.UUID, transfer_id: uuid.UUID,
                              account_id: uuid.UUID | None): ...


@dataclass
class ComplexSettlementService:
    store: ComplexSettlementStore

    async def create_draft(self, user_id: uuid.UUID, request_key: str, data: SettlementInput,
                           revision_plan_id: uuid.UUID | None = None):
        return await self.store.create_draft(user_id, request_key, data, revision_plan_id)

    async def get_draft(self, user_id: uuid.UUID, draft_id: uuid.UUID):
        return await self.store.get_draft(user_id, draft_id)

    async def update_draft(self, user_id: uuid.UUID, draft_id: uuid.UUID, version: int, data: SettlementInput):
        return await self.store.update_draft(user_id, draft_id, version, data)

    async def confirm(self, user_id: uuid.UUID, draft_id: uuid.UUID, version: int):
        return await self.store.confirm(user_id, draft_id, version)

    async def list_plans(self, user_id: uuid.UUID):
        return await self.store.list_plans(user_id)

    async def get_plan(self, user_id: uuid.UUID, plan_id: uuid.UUID):
        return await self.store.get_plan(user_id, plan_id)

    async def settle_transfer(self, user_id: uuid.UUID, plan_id: uuid.UUID, transfer_id: uuid.UUID,
                              account_id: uuid.UUID | None):
        return await self.store.settle_transfer(user_id, plan_id, transfer_id, account_id)
