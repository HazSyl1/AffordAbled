from __future__ import annotations

import uuid
from typing import Any

from app.application.services.split_service import ParticipantShare, SplitService
from app.application.services.transaction_service import TransactionService
from app.infrastructure.ai.agents.contracts import HandoffContext


class SplitToolset:
    """Scoped chat tools for creating and inspecting expense splits."""

    def __init__(self, split_service: SplitService, transaction_service: TransactionService) -> None:
        self._splits = split_service
        self._transactions = transaction_service

    def registry(self) -> dict[str, Any]:
        return {
            "list_split_contacts": self.list_split_contacts,
            "create_split": self.create_split,
        }

    async def list_split_contacts(self, context: HandoffContext, _args: dict[str, Any]) -> dict[str, Any]:
        return {"contacts": await self._splits.contact_names(context.user_id)}

    async def create_split(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        transaction_id = args.get("transaction_id")
        if not transaction_id:
            created = context.constraints.get("created_transaction_ids") or []
            transaction_id = created[-1] if created else None
        if not transaction_id:
            raise ValueError("The expense transaction must be recorded before creating its split.")
        transaction = await self._transactions.get_transaction(context.user_id, uuid.UUID(str(transaction_id)))
        if transaction.type.value != "expense":
            raise ValueError("Only expense transactions can have a split.")
        raw_people = args.get("participants") or args.get("people")
        if not isinstance(raw_people, list):
            raise ValueError("participants must be a list of person names.")
        people: list[ParticipantShare] = []
        for item in raw_people:
            if isinstance(item, str):
                name, share = item, 0
            elif isinstance(item, dict):
                name, share = item.get("name"), item.get("share_paise", item.get("share", 0))
            else:
                raise ValueError("Each participant must include a name.")
            if not name:
                raise ValueError("Each participant must include a name.")
            if isinstance(share, float):
                share = round(share * 100)
            people.append(ParticipantShare(str(name).strip(), int(share)))
        mode = str(args.get("mode") or "equal").lower()
        owner_share = args.get("owner_share_paise")
        if owner_share is None and args.get("owner_share_rupees") is not None:
            owner_share = round(float(args["owner_share_rupees"]) * 100)
        split = await self._splits.create(
            context.user_id,
            transaction.id,
            str(args.get("title") or transaction.merchant or transaction.note or "Shared expense"),
            transaction.amount_paise,
            mode,
            people,
            int(owner_share) if owner_share is not None else None,
        )
        return {
            "split": {
                "id": str(split.id),
                "transaction_id": str(split.transaction_id),
                "title": split.title,
                "owner_share_paise": split.owner_share_paise,
                "total_paise": split.owner_share_paise + sum(person.share_paise for person in split.participants),
                "participants": [
                    {"name": person.name, "share_paise": person.share_paise}
                    for person in split.participants
                ],
            }
        }
