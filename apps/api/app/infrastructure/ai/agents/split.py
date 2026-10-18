from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Any

from langgraph.types import interrupt

from app.application.services.itemized_split import ItemAllocation, calculate_itemized_split
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
            "set_split_contact_preference": self.set_split_contact_preference,
            "create_split": self.create_split,
        }

    async def list_split_contacts(self, context: HandoffContext, _args: dict[str, Any]) -> dict[str, Any]:
        preferences = await self._splits.list_contact_preferences(context.user_id)
        return {
            "contacts": await self._splits.contact_names(context.user_id),
            "confirmed_preferences": [
                {"name": contact.name, "dietary_preference": contact.dietary_preference}
                for contact in preferences if contact.dietary_preference
            ],
            "preference_suggestions": await self._splits.contact_preference_suggestions(context.user_id),
        }

    async def set_split_contact_preference(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get('name') or '').strip()
        preference = args.get('dietary_preference')
        if preference is not None:
            preference = str(preference).strip().casefold()
            preference = {
                'veg': 'vegetarian', 'nonveg': 'omnivore', 'non-veg': 'omnivore',
                'eats meat': 'omnivore',
            }.get(preference, preference)
        contact = await self._splits.set_contact_preference(context.user_id, name, preference)
        return {
            'contact': {'id': str(contact.id), 'name': contact.name,
                        'dietary_preference': contact.dietary_preference},
        }

    async def create_split(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        if 'itemized split' in context.request.casefold() and args.get('items') is None:
            raise ValueError('An itemized split needs priced items and the people who shared each item.')
        transaction_id = args.get("transaction_id")
        if not transaction_id:
            created = context.constraints.get("created_transaction_ids") or []
            transaction_id = created[-1] if created else None
        if not transaction_id:
            transaction_id = context.constraints.get('pending_split_transaction_id')
        if not transaction_id and 'split' in context.request.casefold() and re.search(
            r'\b(?:that|this|receipt|it)\b', context.request.casefold()
        ):
            prior_results = context.constraints.get('prior_specialist_results') or []
            prior_transactions = [
                transaction
                for result in prior_results[-5:]
                if result.get('specialist') == 'transaction'
                for transaction in (result.get('data') or {}).get('created_transactions', [])
                if isinstance(transaction, dict) and transaction.get('id')
            ]
            if len(prior_transactions) == 1:
                transaction_id = prior_transactions[0]['id']
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
        item_breakdown = None
        if args.get('items') is not None:
            raw_items = args['items']
            if not isinstance(raw_items, list):
                raise ValueError('items must be a list of receipt line items.')
            if len(raw_items) > 20:
                raise ValueError('Review at most 20 receipt items in chat at once.')
            for item in raw_items:
                if not isinstance(item, dict) or isinstance(item.get('amount_paise'), (bool, float)):
                    raise ValueError('Each receipt item needs an integer amount_paise.')
                if not str(item.get('amount_paise') or '').isascii() or not str(
                    item.get('amount_paise') or ''
                ).isdecimal():
                    raise ValueError('Each receipt item needs an integer amount_paise.')
            items = [
                ItemAllocation(
                    name=str(item['name']), amount_paise=int(item['amount_paise']),
                    shared_by=list(item['shared_by']), food_type=str(item.get('food_type') or 'unknown'),
                )
                for item in raw_items
            ]
            contacts = await self._splits.list_contact_preferences(context.user_id)
            calculation = calculate_itemized_split(
                transaction.amount_paise, [person.name for person in people], items,
                {contact.normalized_name: contact.dietary_preference for contact in contacts},
            )
            summary = ', '.join(
                [f'you: ₹{Decimal(calculation.owner_share_paise) / 100:.2f}', *[
                    f'{name}: ₹{Decimal(amount) / 100:.2f}'
                    for name, amount in calculation.participant_shares.items()
                ]]
            )
            item_summary = '; '.join(
                f"{item['name']} ₹{Decimal(item['amount_paise']) / 100:.2f} shared by "
                f"{', '.join(share['person'] for share in item['allocations'])}"
                for item in calculation.items
            )
            warnings = f" Warnings: {' '.join(calculation.warnings)}" if calculation.warnings else ''
            answer = interrupt({
                'agent': 'split',
                'question': f'Review the items: {item_summary}. Shares: {summary}.{warnings} Confirm this split?'
            })
            if str(answer).strip().casefold() not in {'yes', 'y', 'confirm', 'confirmed', 'proceed'}:
                feedback = str(answer).strip()[:400]
                raise ValueError(
                    f'Itemized split was not saved. User correction or refusal: {feedback}. '
                    'Revise the items if specific changes were given; otherwise ask what to change.'
                )
            mode = 'custom'
            owner_share = calculation.owner_share_paise
            people = [ParticipantShare(name, amount) for name, amount in calculation.participant_shares.items()]
            item_breakdown = calculation.items
        split = await self._splits.create(
            context.user_id,
            transaction.id,
            str(args.get("title") or transaction.merchant or transaction.note or "Shared expense"),
            transaction.amount_paise,
            mode,
            people,
            int(owner_share) if owner_share is not None else None,
            item_breakdown,
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
