from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from app.application.dto import CreateAccountInput, UpdateAccountInput
from app.application.services.account_service import AccountService
from app.domain.entities import AccountType
from app.infrastructure.ai.agents.contracts import HandoffContext


class AccountToolset:
    def __init__(self, service: AccountService) -> None:
        self._service = service

    def registry(self) -> dict[str, Any]:
        return {
            "list_accounts": self.list_accounts,
            "create_account": self.create_account,
            "update_account": self.update_account,
            "set_default_account": self.set_default_account,
            "delete_account": self.delete_account,
            "rename_account": self.rename_account,
            "activate_account": self.activate_account,
            "deactivate_account": self.deactivate_account,
        }

    async def list_accounts(self, context: HandoffContext, _args: dict[str, Any]) -> dict[str, Any]:
        return {"accounts": [self._serialize(a) for a in await self._service.list_accounts(context.user_id)]}

    async def create_account(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("account name is required")
        try:
            if "balance_rupees" in args:
                balance_paise = int(Decimal(str(args["balance_rupees"])) * 100)
            else:
                balance_paise = int(args.get("balance_paise", 0))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("initial balance must be a valid rupee amount") from exc
        if balance_paise < 0:
            raise ValueError("initial balance cannot be negative")
        account = await self._service.create_account(
            CreateAccountInput(
                user_id=context.user_id,
                name=name,
                type=AccountType(str(args.get("type", "bank")).lower()),
                balance_paise=balance_paise,
                currency=str(args.get("currency", "INR")).upper(),
            )
        )
        return {"account": self._serialize(account)}

    async def update_account(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        account = await self._service.update_account(
            context.user_id,
            uuid.UUID(str(args["account_id"])),
            UpdateAccountInput(
                name=str(args["name"]).strip() if args.get("name") else None, is_active=args.get("is_active")
            ),
        )
        return {"account": self._serialize(account)}

    async def set_default_account(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        account = await self._service.set_default_account(context.user_id, uuid.UUID(str(args["account_id"])))
        return {"account": self._serialize(account)}

    async def rename_account(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        return await self.update_account(context, {"account_id": args["account_id"], "name": args["name"]})

    async def activate_account(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        return await self.update_account(context, {"account_id": args["account_id"], "is_active": True})

    async def deactivate_account(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        return await self.update_account(context, {"account_id": args["account_id"], "is_active": False})

    async def delete_account(self, _context: HandoffContext, _args: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("account deletion is not supported by the existing domain model")

    @staticmethod
    def _serialize(account: Any) -> dict[str, Any]:
        return {
            "id": str(account.id),
            "name": account.name,
            "type": account.type.value,
            "balance_paise": account.balance_paise,
            "currency": account.currency,
            "is_active": account.is_active,
            "is_default": account.is_default,
        }
