from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.dto import CreateTransactionInput, UpdateTransactionInput
from app.application.services.transaction_service import TransactionService
from app.domain.entities import TransactionType
from app.infrastructure.ai.agents.contracts import HandoffContext
from app.infrastructure.ai.agents.extraction import TransactionExtractionAgent


class TransactionToolset:
    def __init__(self, service: TransactionService, extraction_agent: TransactionExtractionAgent | None = None) -> None:
        self._service = service
        self._extraction_agent = extraction_agent

    def registry(self) -> dict[str, Any]:
        return {
            "extract_transaction": self.extract_transaction,
            "list_transactions": self.list_transactions,
            "create_transaction": self.create_transaction,
            "update_transaction": self.update_transaction,
            "delete_transaction": self.delete_transaction,
            "restore_transaction": self.restore_transaction,
            "list_accounts": self.list_accounts,
            "list_categories": self.list_categories,
            "create_transaction_batch": self.create_transaction_batch,
        }

    async def extract_transaction(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        if self._extraction_agent is None:
            raise RuntimeError("transaction extraction sub-agent is unavailable")
        return await self._extraction_agent.extract(context, args)

    async def list_transactions(self, context: HandoffContext, _args: dict[str, Any]) -> dict[str, Any]:
        transactions = await self._service.list_transactions(context.user_id)
        return {"transactions": [self._serialize(item) for item in transactions]}

    async def list_accounts(self, context: HandoffContext, _args: dict[str, Any]) -> dict[str, Any]:
        accounts = await self._service.account_repository.list_for_user(context.user_id)
        return {
            "accounts": [
                {
                    "id": str(item.id),
                    "name": item.name,
                    "type": item.type.value,
                    "is_active": item.is_active,
                    "is_default": item.is_default,
                }
                for item in accounts
            ]
        }

    async def list_categories(self, context: HandoffContext, _args: dict[str, Any]) -> dict[str, Any]:
        categories = await self._service.category_repository.list_for_user(context.user_id)
        return {"categories": [{"id": str(item.id), "name": item.name, "type": item.type.value} for item in categories]}

    async def create_transaction(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        try:
            if "amount_rupees" in args:
                amount_paise = int(Decimal(str(args["amount_rupees"])) * 100)
            else:
                amount_paise = int(args["amount_paise"])
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise ValueError("transaction amount is required and must be a valid rupee amount") from exc
        if amount_paise <= 0:
            raise ValueError("transaction amount must be greater than zero")
        occurred_at = self._occurred_at(args.get("occurred_at"), context.timezone)
        transaction = await self._service.create_transaction(
            CreateTransactionInput(
                user_id=context.user_id,
                account_id=uuid.UUID(str(args["account_id"])),
                category_id=uuid.UUID(str(args["category_id"])) if args.get("category_id") else None,
                to_account_id=uuid.UUID(str(args["to_account_id"])) if args.get("to_account_id") else None,
                type=TransactionType(str(args["type"]).lower()),
                amount_paise=amount_paise,
                occurred_at=occurred_at,
                merchant=args.get("merchant"),
                note=args.get("note"),
            )
        )
        return {"transaction": self._serialize(transaction)}

    async def create_transaction_batch(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        rows = args.get("transactions")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 10:
            raise ValueError("transactions must contain between 1 and 10 rows")
        created = [await self.create_transaction(context, row) for row in rows if isinstance(row, dict)]
        if len(created) != len(rows):
            raise ValueError("each batch row must be an object")
        return {"transactions": [item["transaction"] for item in created]}

    async def update_transaction(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        transaction = await self._service.update_transaction(
            context.user_id,
            uuid.UUID(str(args["transaction_id"])),
            UpdateTransactionInput(
                amount_paise=int(args["amount_paise"]) if args.get("amount_paise") is not None else None,
                merchant=args.get("merchant"),
                note=args.get("note"),
            ),
        )
        return {"transaction": self._serialize(transaction)}

    async def delete_transaction(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        if args.get("confirmed") is not True:
            raise ValueError("explicit confirmation is required to delete a transaction")
        transaction_id = uuid.UUID(str(args["transaction_id"]))
        transaction = await self._service.get_transaction(context.user_id, transaction_id)
        await self._service.soft_delete_transaction(context.user_id, transaction_id)
        return {"deleted_transaction_id": str(transaction_id), "transaction": self._serialize(transaction)}

    async def restore_transaction(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        transaction_id = uuid.UUID(str(args["transaction_id"]))
        await self._service.restore_transaction(context.user_id, transaction_id)
        return {"restored_transaction_id": str(transaction_id)}

    @staticmethod
    def _serialize(transaction: Any) -> dict[str, Any]:
        return {
            "id": str(transaction.id),
            "type": transaction.type.value,
            "amount_paise": transaction.amount_paise,
            "account_id": str(transaction.account_id),
            "category_id": str(transaction.category_id) if transaction.category_id else None,
            "occurred_at": transaction.occurred_at.isoformat(),
            "merchant": transaction.merchant,
            "note": transaction.note,
        }

    @staticmethod
    def _occurred_at(value: Any, timezone: str) -> datetime:
        if value:
            return datetime.fromisoformat(str(value))
        try:
            return datetime.now(ZoneInfo(timezone))
        except ZoneInfoNotFoundError:
            return datetime.now(UTC)
