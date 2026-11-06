from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.dto import CreateTransactionInput, UpdateTransactionInput
from app.application.services.recurring_transaction_service import (
    CreateRecurringRuleInput,
    RecurringTransactionService,
)
from app.application.services.transaction_service import TransactionService
from app.domain.entities import RecurrenceUnit, TransactionType
from app.infrastructure.ai.agents.contracts import HandoffContext
from app.infrastructure.ai.agents.extraction import TransactionExtractionAgent


class TransactionToolset:
    def __init__(
        self, service: TransactionService, extraction_agent: TransactionExtractionAgent | None = None,
        recurring_service: RecurringTransactionService | None = None,
    ) -> None:
        self._service = service
        self._extraction_agent = extraction_agent
        self._recurring_service = recurring_service

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
            **({
                "create_recurring_transaction": self.create_recurring_transaction,
                "list_recurring_transactions": self.list_recurring_transactions,
                "pause_recurring_transaction": self.pause_recurring_transaction,
                "resume_recurring_transaction": self.resume_recurring_transaction,
                "update_recurring_transaction": self.update_recurring_transaction,
                "cancel_recurring_transaction": self.cancel_recurring_transaction,
            } if self._recurring_service else {}),
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

    @staticmethod
    def _category_answer_signal_from_history(history: list[dict[str, str]]) -> bool:
        """Recover a category clarification signal if interrupt state lost its metadata."""
        latest_user_index = next(
            (index for index in range(len(history) - 1, -1, -1) if history[index].get("role") == "user"),
            None,
        )
        if latest_user_index is None:
            return False
        latest_user_reply = str(history[latest_user_index].get("content") or "").strip().casefold()
        if not latest_user_reply or latest_user_reply in {"no", "nope", "cancel", "skip"}:
            return False
        prior_assistant = next(
            (
                str(history[index].get("content") or "")
                for index in range(latest_user_index - 1, -1, -1)
                if history[index].get("role") == "assistant"
            ),
            "",
        ).casefold()
        asks_category = "categor" in prior_assistant and any(
            phrase in prior_assistant for phrase in ("which", "what", "choose", "use", "should i")
        )
        return asks_category

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
        merchant = args.get("merchant")
        category_id = uuid.UUID(str(args["category_id"])) if args.get("category_id") else None
        memory_signal = context.constraints.get("memory_review_signal")
        if not isinstance(memory_signal, dict) and self._category_answer_signal_from_history(context.history):
            # Interrupt resumes can update the parent checkpoint while a nested
            # specialist continues from its own checkpoint. Recover the signal
            # from the persisted transcript at the transaction tool boundary.
            memory_signal = {"signal_type": "category_mapping"}
        memory_review_context = None
        if isinstance(memory_signal, dict) and memory_signal.get("signal_type") in {
            "category_mapping", "account_mapping", "preference", "split_preference",
        }:
            remaining = 8_000
            bounded_history: list[dict[str, str]] = []
            for message in reversed(context.history[-12:]):
                content = str(message.get("content") or "")[-remaining:]
                bounded_history.append({"role": str(message.get("role") or "")[:16], "content": content})
                remaining -= len(content)
                if remaining <= 0:
                    break
            memory_review_context = {
                "signal_type": memory_signal["signal_type"],
                "payload": {
                    "transaction": {
                        "type": str(args.get("type") or "")[:16],
                        "amount_paise": amount_paise,
                        "merchant": str(merchant or "")[:255],
                        "category_name": next((item.get("name") for item in context.constraints.get(
                            "available_categories", []) if str(item.get("id")) == str(category_id)), None),
                        "account_name": next((item.get("name") for item in context.constraints.get(
                            "available_accounts", []) if str(item.get("id")) == str(args.get("account_id"))), None),
                    },
                    "history": list(reversed(bounded_history)),
                    "signal": {key: str(value)[:200] for key, value in memory_signal.items()
                               if key in {"signal_type", "subject_hint"} and value is not None},
                    "categories": context.constraints.get("available_categories", [])[:50],
                    "accounts": context.constraints.get("available_accounts", [])[:30],
                },
            }
        transaction = await self._service.create_transaction(
            CreateTransactionInput(
                user_id=context.user_id,
                account_id=uuid.UUID(str(args["account_id"])),
                category_id=category_id,
                to_account_id=uuid.UUID(str(args["to_account_id"])) if args.get("to_account_id") else None,
                type=TransactionType(str(args["type"]).lower()),
                amount_paise=amount_paise,
                occurred_at=occurred_at,
                merchant=merchant,
                note=args.get("note"),
                memory_review_context=memory_review_context,
                source_turn_id=(
                    uuid.UUID(str(context.constraints["turn_id"]))
                    if context.constraints.get("turn_id") else None
                ),
                source_task_id=(
                    str(context.constraints["task_id"])
                    if context.constraints.get("task_id") else None
                ),
                source_item_index=int(args.get("_source_item_index", 0)),
                timezone=context.timezone,
            )
        )
        return {"transaction": self._serialize(transaction)}

    async def create_transaction_batch(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        rows = args.get("transactions")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 10:
            raise ValueError("transactions must contain between 1 and 10 rows")
        created = [
            await self.create_transaction(context, {**row, "_source_item_index": index})
            for index, row in enumerate(rows)
            if isinstance(row, dict)
        ]
        if len(created) != len(rows):
            raise ValueError("each batch row must be an object")
        return {"transactions": [item["transaction"] for item in created]}

    async def create_recurring_transaction(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        if self._recurring_service is None:
            raise RuntimeError('Recurring transactions are unavailable.')
        if args.get('confirmed') is not True:
            raise ValueError('Explicit confirmation is required to activate a recurring transaction.')
        try:
            amount_paise = int(Decimal(str(args['amount_rupees'])) * 100)
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise ValueError('A valid recurring amount in rupees is required.') from exc
        anchor_at = self._occurred_at(args.get('anchor_at'), context.timezone)
        rule, initial = await self._recurring_service.create_rule(CreateRecurringRuleInput(
            user_id=context.user_id, account_id=uuid.UUID(str(args['account_id'])),
            category_id=uuid.UUID(str(args['category_id'])),
            type=TransactionType(str(args['type']).lower()), amount_paise=amount_paise,
            merchant=args.get('merchant'), note=args.get('note'),
            recurrence_unit=RecurrenceUnit(str(args['recurrence_unit']).lower()),
            interval_count=int(args.get('interval_count', 1)), anchor_at=anchor_at,
            timezone=context.timezone, end_at=datetime.fromisoformat(args['end_at']) if args.get('end_at') else None,
            max_occurrences=args.get('max_occurrences'),
            create_initial_transaction=bool(args.get('create_initial_transaction', True)), source='chat',
            source_turn_id=(uuid.UUID(str(context.constraints['turn_id']))
                            if context.constraints.get('turn_id') else None),
            source_task_id=str(context.constraints['task_id']) if context.constraints.get('task_id') else None,
        ))
        return {
            'recurring_rule': self._serialize_rule(rule),
            'initial_transaction': self._serialize(initial) if initial else None,
        }

    async def list_recurring_transactions(self, context: HandoffContext, _args: dict[str, Any]) -> dict[str, Any]:
        if self._recurring_service is None:
            raise RuntimeError('Recurring transactions are unavailable.')
        return {'recurring_rules': [
            self._serialize_rule(rule) for rule in await self._recurring_service.list_rules(context.user_id)
        ]}

    async def pause_recurring_transaction(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        return await self._change_recurring(context, args, 'pause')

    async def resume_recurring_transaction(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        return await self._change_recurring(context, args, 'resume')

    async def cancel_recurring_transaction(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        if args.get('confirmed') is not True:
            raise ValueError('Explicit confirmation is required to cancel a recurring transaction.')
        return await self._change_recurring(context, args, 'cancel')

    async def update_recurring_transaction(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        if self._recurring_service is None:
            raise RuntimeError('Recurring transactions are unavailable.')
        if args.get('confirmed') is not True:
            raise ValueError('Explicit confirmation is required to update a recurring transaction.')
        changes: dict[str, Any] = {}
        if args.get('account_id'):
            changes['account_id'] = uuid.UUID(str(args['account_id']))
        if args.get('category_id'):
            changes['category_id'] = uuid.UUID(str(args['category_id']))
        if args.get('amount_rupees') is not None:
            changes['amount_paise'] = int(Decimal(str(args['amount_rupees'])) * 100)
        if args.get('recurrence_unit'):
            changes['recurrence_unit'] = RecurrenceUnit(str(args['recurrence_unit']))
        for field in ('interval_count', 'max_occurrences', 'merchant', 'note'):
            if field in args and args[field] is not None:
                changes[field] = args[field]
        for field in ('anchor_at', 'end_at'):
            if args.get(field):
                changes[field] = datetime.fromisoformat(str(args[field]))
        rule = await self._recurring_service.update_rule(
            context.user_id, uuid.UUID(str(args['rule_id'])), changes,
        )
        return {'recurring_rule': self._serialize_rule(rule)}

    async def _change_recurring(self, context: HandoffContext, args: dict[str, Any], action: str) -> dict[str, Any]:
        if self._recurring_service is None:
            raise RuntimeError('Recurring transactions are unavailable.')
        rule = await getattr(self._recurring_service, action)(context.user_id, uuid.UUID(str(args['rule_id'])))
        return {'recurring_rule': self._serialize_rule(rule)}

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
    def _serialize_rule(rule: Any) -> dict[str, Any]:
        return {
            'id': str(rule.id), 'type': rule.type.value, 'amount_paise': rule.amount_paise,
            'account_id': str(rule.account_id) if rule.account_id else None,
            'category_id': str(rule.category_id) if rule.category_id else None,
            'recurrence_unit': rule.recurrence_unit.value, 'interval_count': rule.interval_count,
            'next_occurrence_at': rule.next_occurrence_at.isoformat() if rule.next_occurrence_at else None,
            'status': rule.status.value, 'merchant': rule.merchant,
        }

    @staticmethod
    def _occurred_at(value: Any, timezone: str) -> datetime:
        if value:
            return datetime.fromisoformat(str(value))
        try:
            return datetime.now(ZoneInfo(timezone))
        except ZoneInfoNotFoundError:
            return datetime.now(UTC)
