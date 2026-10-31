from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.services.split_service import ParticipantEditShare, ParticipantShare
from app.infrastructure.database.models import (
    AccountModel,
    CategoryModel,
    SettlementPlanModel,
    SettlementPlanTransactionModel,
    SettlementPlanTransferModel,
    SplitContactModel,
    SplitModel,
    SplitParticipantModel,
    SplitPaymentModel,
    TransactionModel,
    UserModel,
)

SPLIT_REPAYMENT_CATEGORY = 'Split'
DEBT_REPAYMENT_CATEGORY = 'Split'


class SqlAlchemySplitRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def is_linked(self, user_id: uuid.UUID, transaction_id: uuid.UUID) -> bool:
        split_id = await self.session.scalar(
            select(SplitModel.id).where(
                SplitModel.user_id == user_id, SplitModel.transaction_id == transaction_id
            )
        )
        if split_id is not None:
            return True
        plan_link = await self.session.scalar(
            select(SettlementPlanTransactionModel.transaction_id).join(SettlementPlanModel).where(
                SettlementPlanModel.user_id == user_id,
                SettlementPlanTransactionModel.transaction_id == transaction_id,
            )
        )
        if plan_link is not None:
            return True
        plan_repayment = await self.session.scalar(
            select(SettlementPlanTransferModel.id).join(SettlementPlanModel).where(
                SettlementPlanModel.user_id == user_id,
                SettlementPlanTransferModel.repayment_transaction_id == transaction_id,
            )
        )
        if plan_repayment is not None:
            return True
        repayment_id = await self.session.scalar(
            select(SplitParticipantModel.id).join(SplitModel).where(
                SplitModel.user_id == user_id,
                SplitParticipantModel.repayment_transaction_id == transaction_id,
            )
        )
        if repayment_id is not None:
            return True
        payment_id = await self.session.scalar(
            select(SplitPaymentModel.id).join(SplitParticipantModel).join(SplitModel).where(
                SplitModel.user_id == user_id,
                SplitPaymentModel.transaction_id == transaction_id,
            )
        )
        return payment_id is not None

    async def create(
        self, user_id: uuid.UUID, transaction_id: uuid.UUID, title: str,
        owner_share_paise: int, participants: list[ParticipantShare], item_breakdown: list[dict] | None = None,
        settlement_breakdown: dict | None = None,
    ) -> SplitModel:
        existing_plan = await self.session.scalar(
            select(SettlementPlanTransactionModel.transaction_id).join(SettlementPlanModel).where(
                SettlementPlanModel.user_id == user_id,
                SettlementPlanTransactionModel.transaction_id == transaction_id,
            )
        )
        if existing_plan is not None:
            raise ValueError('This expense already belongs to a group settlement plan.')
        transaction = await self.session.scalar(
            select(TransactionModel).where(
                TransactionModel.id == transaction_id,
                TransactionModel.user_id == user_id,
                TransactionModel.deleted_at.is_(None),
                TransactionModel.type == 'expense',
            )
        )
        if transaction is None:
            raise LookupError('Expense transaction was not found.')
        if owner_share_paise + sum(person.share_paise for person in participants) != transaction.amount_paise:
            raise ValueError('Split shares must match the current expense amount.')
        existing = await self.session.scalar(select(SplitModel.id).where(SplitModel.transaction_id == transaction_id))
        if existing is not None:
            raise ValueError('This expense already has a split.')
        split = SplitModel(
            id=uuid.uuid4(), user_id=user_id, transaction_id=transaction_id,
            title=title, owner_share_paise=owner_share_paise, item_breakdown=item_breakdown,
            settlement_breakdown=settlement_breakdown,
            participants=[
                SplitParticipantModel(id=uuid.uuid4(), name=person.name, share_paise=person.share_paise,
                                      settled_paise=0)
                for person in participants
            ],
        )
        self.session.add(split)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise ValueError('This expense already has a split.') from error
        except Exception:
            await self.session.rollback()
            raise
        return await self.get_for_user(user_id, split.id)

    async def create_owed(
        self, user_id: uuid.UUID, title: str, person: ParticipantShare, direction: str = 'to_you',
    ) -> SplitModel:
        return (await self.create_owed_batch(user_id, title, [person], direction))[0]

    async def create_owed_batch(
        self, user_id: uuid.UUID, title: str, people: list[ParticipantShare], direction: str,
    ) -> list[SplitModel]:
        splits = [
            SplitModel(
                id=uuid.uuid4(), user_id=user_id, transaction_id=None, title=title,
                direction=direction, owner_share_paise=0, item_breakdown=None,
                participants=[SplitParticipantModel(
                    id=uuid.uuid4(), name=person.name, share_paise=person.share_paise, settled_paise=0,
                )],
            )
            for person in people
        ]
        self.session.add_all(splits)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return [await self.get_for_user(user_id, split.id) for split in splits]

    async def list_for_user(self, user_id: uuid.UUID) -> list[SplitModel]:
        rows = await self.session.scalars(
            select(SplitModel).where(SplitModel.user_id == user_id)
            .options(selectinload(SplitModel.participants).selectinload(SplitParticipantModel.payments))
            .order_by(SplitModel.created_at.desc(), SplitModel.id.desc())
            .execution_options(populate_existing=True)
        )
        return list(rows.all())

    async def get_for_user(self, user_id: uuid.UUID, split_id: uuid.UUID) -> SplitModel | None:
        return await self.session.scalar(
            select(SplitModel).where(SplitModel.id == split_id, SplitModel.user_id == user_id)
            .options(selectinload(SplitModel.participants).selectinload(SplitParticipantModel.payments))
            .execution_options(populate_existing=True)
        )

    async def update(
        self, user_id: uuid.UUID, split_id: uuid.UUID, title: str,
        owner_share_paise: int, participants: list[ParticipantEditShare],
    ) -> SplitModel | None:
        split = await self.get_for_user(user_id, split_id)
        if split is None:
            return None
        if split.transaction_id is None:
            raise ValueError('Edit standalone money owed entries from the owed amount form.')
        amount_paise = await self.session.scalar(
            select(TransactionModel.amount_paise).where(
                TransactionModel.id == split.transaction_id,
                TransactionModel.user_id == user_id,
                TransactionModel.deleted_at.is_(None),
                TransactionModel.type == 'expense',
            )
        )
        if amount_paise is None:
            raise LookupError('Expense transaction was not found.')
        if owner_share_paise + sum(person.share_paise for person in participants) != amount_paise:
            raise ValueError('Split shares must match the current expense amount.')

        existing = {person.id: person for person in split.participants}
        requested_ids = {person.id for person in participants if person.id is not None}
        if requested_ids - existing.keys():
            raise ValueError('A participant does not belong to this split.')
        requested = {person.id: person for person in participants if person.id is not None}
        same_allocations = (
            owner_share_paise == split.owner_share_paise
            and len(participants) == len(split.participants)
            and all(
                person.id in existing
                and person.name == existing[person.id].name
                and person.share_paise == existing[person.id].share_paise
                for person in participants
            )
        )
        has_settlement_repayments = any(
            transfer.get('repayment_transaction_id')
            for transfer in (split.settlement_breakdown or {}).get('transfers', [])
        )
        if has_settlement_repayments and not same_allocations:
            raise ValueError('A settlement plan with recorded repayments cannot be changed.')
        for person in split.participants:
            if person.repayment_transaction_id is not None or person.settled_paise > 0:
                updated = requested.get(person.id)
                if updated is None or updated.share_paise != person.share_paise:
                    raise ValueError('A person with a linked repayment cannot be removed or have their share changed.')

        try:
            for person in list(split.participants):
                if person.id not in requested_ids:
                    split.participants.remove(person)
            await self.session.flush()

            renamed = [person for person in participants if person.id is not None and
                       existing[person.id].name != person.name]
            for person in renamed:
                existing[person.id].name = f'__edit_{uuid.uuid4().hex}'
            if renamed:
                await self.session.flush()

            split.title = title
            split.owner_share_paise = owner_share_paise
            if not same_allocations:
                split.item_breakdown = None
                split.settlement_breakdown = None
            for person in participants:
                if person.id is None:
                    split.participants.append(SplitParticipantModel(
                        id=uuid.uuid4(), name=person.name, share_paise=person.share_paise, settled_paise=0,
                    ))
                else:
                    existing[person.id].name = person.name
                    existing[person.id].share_paise = person.share_paise
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise ValueError('Participant names must be unique within the split.') from error
        except Exception:
            await self.session.rollback()
            raise
        return await self.get_for_user(user_id, split_id)

    async def settle(
        self, user_id: uuid.UUID, split_id: uuid.UUID,
        participant_id: uuid.UUID, repayment_transaction_id: uuid.UUID,
    ) -> SplitModel | None:
        split = await self.get_for_user(user_id, split_id)
        if split is None:
            return None
        participant = next((person for person in split.participants if person.id == participant_id), None)
        if participant is None:
            return None
        remaining_paise = participant.share_paise - participant.settled_paise
        if remaining_paise <= 0:
            raise ValueError('This person is already settled.')
        repayment = await self.session.scalar(
            select(TransactionModel).where(
                TransactionModel.id == repayment_transaction_id,
                TransactionModel.user_id == user_id,
                TransactionModel.deleted_at.is_(None),
                TransactionModel.type.in_(['income', 'refund']),
            )
        )
        if repayment is None:
            raise LookupError('Repayment transaction was not found.')
        if repayment.amount_paise <= 0 or repayment.amount_paise > remaining_paise:
            raise ValueError('Repayment amount must be positive and no more than the remaining share.')
        already_linked = await self.session.scalar(select(SplitParticipantModel.id).where(
            SplitParticipantModel.repayment_transaction_id == repayment_transaction_id,
        ))
        if already_linked is None:
            already_linked = await self.session.scalar(select(SplitPaymentModel.id).where(
                SplitPaymentModel.transaction_id == repayment_transaction_id,
            ))
        if already_linked is not None:
            raise ValueError('That repayment is already linked to a split.')
        self.session.add(SplitPaymentModel(
            id=uuid.uuid4(), participant_id=participant.id, amount_paise=repayment.amount_paise,
            transaction_id=repayment.id,
        ))
        participant.settled_paise += repayment.amount_paise
        if participant.settled_paise == participant.share_paise:
            participant.repayment_transaction_id = repayment_transaction_id
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise ValueError('That repayment is already linked to a split.') from error
        return await self.get_for_user(user_id, split_id)

    async def repay(
        self, user_id: uuid.UUID, split_id: uuid.UUID,
        participant_id: uuid.UUID, account_id: uuid.UUID,
    ) -> SplitModel | None:
        split = await self.get_for_user(user_id, split_id)
        if split is None:
            return None
        if split.transaction_id is None and split.direction != 'to_you':
            raise ValueError('This is money you owe. Use Mark paid to record the expense repayment.')
        return await self.record_payment(user_id, split_id, participant_id, account_id, None)

    async def pay_owed(
        self, user_id: uuid.UUID, split_id: uuid.UUID,
        participant_id: uuid.UUID, account_id: uuid.UUID,
    ) -> SplitModel | None:
        """Record the full remaining outgoing payment for a standalone debt."""
        split = await self.get_for_user(user_id, split_id)
        if split is None:
            return None
        if split.transaction_id is not None or split.direction != 'by_you':
            raise ValueError('Only standalone amounts you owe can be marked paid here.')
        return await self.record_payment(user_id, split_id, participant_id, account_id, None)

    async def record_payment(
        self, user_id: uuid.UUID, split_id: uuid.UUID, participant_id: uuid.UUID,
        account_id: uuid.UUID, amount_paise: int | None,
    ) -> SplitModel | None:
        """Record an incoming or outgoing payment and atomically update its outstanding balance."""
        await self.session.scalar(select(UserModel.id).where(UserModel.id == user_id).with_for_update())
        split = await self.get_for_user(user_id, split_id)
        if split is None:
            return None
        participant = next((person for person in split.participants if person.id == participant_id), None)
        if participant is None:
            return None
        remaining_paise = participant.share_paise - participant.settled_paise
        if remaining_paise <= 0:
            raise ValueError('This amount is already fully settled.')
        payment_paise = remaining_paise if amount_paise is None else amount_paise
        if amount_paise is not None and payment_paise <= 100:
            raise ValueError('Enter a payment greater than 1 rupee.')
        if payment_paise > remaining_paise:
            raise ValueError('Payment cannot exceed the remaining amount owed.')
        account = await self.session.scalar(select(AccountModel).where(
            AccountModel.id == account_id, AccountModel.user_id == user_id, AccountModel.is_active.is_(True),
        ))
        if account is None:
            raise LookupError('Payment account was not found or is inactive.')
        outgoing = split.transaction_id is None and split.direction == 'by_you'
        transaction_type = 'expense' if outgoing else 'income'
        category = await self.session.scalar(select(CategoryModel).where(
            CategoryModel.user_id == user_id, CategoryModel.type == transaction_type,
            CategoryModel.name == SPLIT_REPAYMENT_CATEGORY,
        ))
        now = datetime.now(UTC)
        if category is None:
            category = CategoryModel(
                id=uuid.uuid4(), user_id=user_id, name=SPLIT_REPAYMENT_CATEGORY, type=transaction_type,
            )
            self.session.add(category)
        transaction = TransactionModel(
            id=uuid.uuid4(), user_id=user_id, account_id=account_id,
            category_id=category.id, type=transaction_type, amount_paise=payment_paise,
            merchant=participant.name,
            note=(f'Payment for amount owed: {split.title}' if outgoing else f'Repayment for split: {split.title}'),
            occurred_at=now, created_at=now, updated_at=now,
        )
        self.session.add(transaction)
        await self.session.flush()
        self.session.add(SplitPaymentModel(
            id=uuid.uuid4(), participant_id=participant.id, amount_paise=payment_paise,
            transaction_id=transaction.id, created_at=now,
        ))
        try:
            await self.session.flush()
            account.balance_paise += -payment_paise if outgoing else payment_paise
            account.updated_at = now
            participant.settled_paise += payment_paise
            if participant.settled_paise == participant.share_paise:
                participant.repayment_transaction_id = transaction.id
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return await self.get_for_user(user_id, split_id)

    async def settle_balance(
        self, user_id: uuid.UUID, person_name: str, account_id: uuid.UUID | None,
        amount_paise: int | None, expected_owed_to_you_paise: int, expected_you_owe_paise: int,
    ) -> dict:
        """Net mutual IOUs, then apply an optional cash payment to the smallest open split entries first."""
        await self.session.scalar(select(UserModel.id).where(UserModel.id == user_id).with_for_update())
        splits = await self.list_for_user(user_id)
        requested_name = person_name.strip().casefold()
        entries: dict[str, list[tuple[SplitModel, SplitParticipantModel, int, int | None]]] = {
            'to_you': [], 'by_you': [],
        }
        canonical_names: set[str] = set()
        for split in splits:
            if split.settlement_breakdown is not None:
                for transfer_index, transfer in enumerate(split.settlement_breakdown.get('transfers', [])):
                    debtor = str(transfer.get('debtor') or '').strip()
                    creditor = str(transfer.get('creditor') or '').strip()
                    if creditor.casefold() == 'you':
                        name, direction = debtor, 'to_you'
                    elif debtor.casefold() == 'you':
                        name, direction = creditor, 'by_you'
                    else:
                        continue
                    if name.casefold() != requested_name:
                        continue
                    participant = next(
                        (person for person in split.participants if person.name.casefold() == name.casefold()), None,
                    )
                    if participant is None:
                        continue
                    total = int(transfer.get('amount_paise') or 0)
                    settled = int(transfer.get('settled_paise') or 0)
                    if transfer.get('repayment_transaction_id'):
                        settled = total
                    remaining = max(0, total - settled)
                    if remaining:
                        entries[direction].append((split, participant, remaining, transfer_index))
                        canonical_names.add(participant.name)
                continue
            direction = 'to_you' if split.transaction_id is not None else split.direction
            if direction not in entries:
                continue
            for participant in split.participants:
                if participant.name.strip().casefold() != requested_name:
                    continue
                remaining = max(0, participant.share_paise - participant.settled_paise)
                if remaining > 0:
                    entries[direction].append((split, participant, remaining, None))
                    canonical_names.add(participant.name)
        if not canonical_names:
            raise LookupError(f'No outstanding split or IOU was found for {person_name.strip()}.')
        if len(canonical_names) > 1:
            raise ValueError('This name matches multiple saved people. Select one exact contact name.')
        for direction_entries in entries.values():
            direction_entries.sort(key=lambda row: (row[2], row[0].created_at, row[1].name.casefold()))

        to_you = sum(row[2] for row in entries['to_you'])
        by_you = sum(row[2] for row in entries['by_you'])
        if to_you != expected_owed_to_you_paise or by_you != expected_you_owe_paise:
            raise ValueError('This preview is out of date because the balance changed. Refresh and review it again.')
        offset_paise = min(to_you, by_you)
        touched_split_ids: set[uuid.UUID] = set()

        def apply_to_entry(
            split: SplitModel, participant: SplitParticipantModel, transfer_index: int | None,
            applied_paise: int, transaction_id: uuid.UUID | None = None,
        ) -> None:
            if transfer_index is None:
                participant.settled_paise += applied_paise
                if transaction_id and participant.settled_paise == participant.share_paise:
                    participant.repayment_transaction_id = transaction_id
            else:
                breakdown = dict(split.settlement_breakdown or {})
                transfers = [dict(item) for item in breakdown.get('transfers', [])]
                transfer = transfers[transfer_index]
                total = int(transfer.get('amount_paise') or 0)
                settled = int(transfer.get('settled_paise') or 0) + applied_paise
                transfer['settled_paise'] = settled
                if transaction_id and settled >= total:
                    transfer['repayment_transaction_id'] = str(transaction_id)
                transfers[transfer_index] = transfer
                split.settlement_breakdown = {**breakdown, 'transfers': transfers}

        def allocate_offset(direction: str, amount: int) -> None:
            remaining_offset = amount
            for index, (split, participant, remaining, transfer_index) in enumerate(entries[direction]):
                if remaining_offset <= 0:
                    break
                applied = min(remaining, remaining_offset)
                apply_to_entry(split, participant, transfer_index, applied)
                entries[direction][index] = (split, participant, remaining - applied, transfer_index)
                self.session.add(SplitPaymentModel(
                    id=uuid.uuid4(), participant_id=participant.id, amount_paise=applied,
                    transaction_id=None,
                ))
                touched_split_ids.add(split.id)
                remaining_offset -= applied
            if remaining_offset:
                raise ValueError('The outstanding balance changed. Refresh and review the settlement again.')

        if offset_paise:
            allocate_offset('to_you', offset_paise)
            allocate_offset('by_you', offset_paise)

        net_paise = to_you - by_you
        cash_due_paise = abs(net_paise)
        cash_paise = cash_due_paise if amount_paise is None else amount_paise
        if cash_paise > cash_due_paise:
            raise ValueError('Settlement payment cannot exceed the remaining net balance.')
        if cash_paise and cash_paise <= 100:
            raise ValueError('Enter a settlement amount greater than one rupee.')
        if cash_paise and account_id is None:
            raise ValueError('Choose the wallet account used for the settlement payment.')
        account = None
        if cash_paise and account_id is not None:
            account = await self.session.scalar(select(AccountModel).where(
                AccountModel.id == account_id, AccountModel.user_id == user_id, AccountModel.is_active.is_(True),
            ))
            if account is None:
                raise LookupError('Settlement account was not found or is inactive.')

        direction = 'to_you' if net_paise > 0 else 'by_you'
        remaining_cash = cash_paise
        payment_transactions: list[dict] = []
        if cash_paise:
            category_type = 'income' if direction == 'to_you' else 'expense'
            category = await self.session.scalar(select(CategoryModel).where(
                CategoryModel.user_id == user_id, CategoryModel.type == category_type,
                CategoryModel.name == (SPLIT_REPAYMENT_CATEGORY if direction == 'to_you' else DEBT_REPAYMENT_CATEGORY),
            ))
            now = datetime.now(UTC)
            if category is None:
                category = CategoryModel(
                    id=uuid.uuid4(), user_id=user_id, name=SPLIT_REPAYMENT_CATEGORY, type=category_type,
                )
                self.session.add(category)
            for split, participant, entry_remaining, transfer_index in entries[direction]:
                if remaining_cash <= 0:
                    break
                applied = min(entry_remaining, remaining_cash)
                transaction = TransactionModel(
                    id=uuid.uuid4(), user_id=user_id, account_id=account.id,
                    category_id=category.id, type=category_type, amount_paise=applied,
                    merchant=participant.name,
                    note=f'Balance settlement: {split.title}',
                    occurred_at=now, created_at=now, updated_at=now,
                )
                self.session.add(transaction)
                await self.session.flush()
                apply_to_entry(split, participant, transfer_index, applied, transaction.id)
                self.session.add(SplitPaymentModel(
                    id=uuid.uuid4(), participant_id=participant.id, amount_paise=applied,
                    transaction_id=transaction.id, created_at=now,
                ))
                touched_split_ids.add(split.id)
                payment_transactions.append({
                    'id': str(transaction.id), 'split_id': str(split.id), 'amount_paise': applied,
                })
                remaining_cash -= applied
            if remaining_cash:
                raise ValueError('The outstanding balance changed. Refresh and review the settlement again.')
            account.balance_paise += cash_paise if direction == 'to_you' else -cash_paise
            account.updated_at = now

        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return {
            'person': next(iter(canonical_names)),
            'offset_paise': offset_paise,
            'cash_direction': direction if cash_paise else None,
            'cash_paise': cash_paise,
            'net_before_paise': net_paise,
            'net_after_paise': net_paise - (cash_paise if net_paise > 0 else -cash_paise),
            'split_ids': [str(split_id) for split_id in sorted(touched_split_ids, key=str)],
            'transactions': payment_transactions,
        }

    async def repay_settlement_transfer(
        self, user_id: uuid.UUID, split_id: uuid.UUID, debtor: str, account_id: uuid.UUID,
    ) -> SplitModel | None:
        await self.session.scalar(select(UserModel.id).where(UserModel.id == user_id).with_for_update())
        split = await self.get_for_user(user_id, split_id)
        if split is None:
            return None
        breakdown = split.settlement_breakdown
        if breakdown is None:
            raise ValueError('This split has no settlement plan.')
        transfers = [dict(item) for item in breakdown.get('transfers', [])]
        matches = [
            transfer for transfer in transfers
            if str(transfer.get('debtor', '')).casefold() == debtor.strip().casefold()
            and str(transfer.get('creditor', '')).strip().casefold() == 'you'
        ]
        if len(matches) != 1:
            raise LookupError('A settlement transfer payable to you was not found.')
        transfer = matches[0]
        transfer_total = int(transfer.get('amount_paise') or 0)
        transfer_settled = int(transfer.get('settled_paise') or 0)
        if transfer.get('repayment_transaction_id') or transfer_settled >= transfer_total:
            raise ValueError('This settlement transfer is already repaid.')
        participant = next(
            (person for person in split.participants if person.name.casefold() == debtor.strip().casefold()), None,
        )
        if participant is None:
            raise LookupError('Settlement participant was not found.')
        amount_paise = transfer_total - transfer_settled
        if amount_paise <= 0:
            raise ValueError('Settlement transfer amount must be positive.')
        account = await self.session.scalar(select(AccountModel).where(
            AccountModel.id == account_id, AccountModel.user_id == user_id, AccountModel.is_active.is_(True),
        ))
        if account is None:
            raise LookupError('Receiving account was not found or is inactive.')
        category = await self.session.scalar(select(CategoryModel).where(
            CategoryModel.user_id == user_id, CategoryModel.type == 'income',
            CategoryModel.name == SPLIT_REPAYMENT_CATEGORY,
        ))
        now = datetime.now(UTC)
        if category is None:
            category = CategoryModel(
                id=uuid.uuid4(), user_id=user_id, name=SPLIT_REPAYMENT_CATEGORY, type='income',
            )
            self.session.add(category)
        transaction = TransactionModel(
            id=uuid.uuid4(), user_id=user_id, account_id=account_id,
            category_id=category.id, type='income', amount_paise=amount_paise,
            merchant=debtor.strip(), note=f'Repayment for split: {split.title}',
            occurred_at=now, created_at=now, updated_at=now,
        )
        self.session.add(transaction)
        await self.session.flush()
        self.session.add(SplitPaymentModel(
            id=uuid.uuid4(), participant_id=participant.id, amount_paise=amount_paise,
            transaction_id=transaction.id, created_at=now,
        ))
        try:
            await self.session.flush()
            account.balance_paise += amount_paise
            account.updated_at = now
            participant.settled_paise += amount_paise
            participant.repayment_transaction_id = transaction.id
            transfer['repayment_transaction_id'] = str(transaction.id)
            transfer['settled_paise'] = transfer_total
            split.settlement_breakdown = {**breakdown, 'transfers': transfers}
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return await self.get_for_user(user_id, split_id)

    async def delete(self, user_id: uuid.UUID, split_id: uuid.UUID) -> bool:
        split = await self.get_for_user(user_id, split_id)
        if split is None:
            return False
        await self.session.delete(split)
        await self.session.commit()
        return True

    async def contact_names(self, user_id: uuid.UUID) -> list[str]:
        rows = await self.session.scalars(
            select(SplitParticipantModel.name).join(SplitModel)
            .where(SplitModel.user_id == user_id).distinct().order_by(SplitParticipantModel.name)
        )
        names = {name.casefold(): name for name in rows.all()}
        contacts = await self.list_contact_preferences(user_id)
        for contact in contacts:
            names[contact.normalized_name] = contact.name
        return sorted(names.values(), key=str.casefold)

    async def list_contact_preferences(self, user_id: uuid.UUID) -> list[SplitContactModel]:
        rows = await self.session.scalars(
            select(SplitContactModel).where(SplitContactModel.user_id == user_id)
            .order_by(SplitContactModel.normalized_name)
        )
        return list(rows.all())

    async def contact_preference_suggestions(self, user_id: uuid.UUID) -> list[dict]:
        """Suggest, but never save, a preference after repeated reviewed item allocations."""
        known = {contact.normalized_name for contact in await self.list_contact_preferences(user_id)
                 if contact.dietary_preference}
        rows = await self.session.scalars(
            select(SplitModel).where(SplitModel.user_id == user_id, SplitModel.item_breakdown.is_not(None))
            .order_by(SplitModel.created_at.desc()).limit(100)
        )
        evidence: dict[str, dict] = {}
        for split in rows.all():
            for item in split.item_breakdown or []:
                food_type = item.get('food_type')
                if food_type not in {'vegetarian', 'vegan', 'contains_meat'}:
                    continue
                for allocation in item.get('allocations') or []:
                    name = str(allocation.get('person') or '').strip()
                    key = name.casefold()
                    if not key or key == 'me' or key in known:
                        continue
                    person = evidence.setdefault(key, {'name': name, 'vegetarian_splits': set(), 'meat_splits': set()})
                    bucket = 'meat_splits' if food_type == 'contains_meat' else 'vegetarian_splits'
                    person[bucket].add(split.id)
        return [
            {'name': person['name'], 'suggested_preference': 'vegetarian',
             'evidence_splits': len(person['vegetarian_splits'])}
            for person in evidence.values()
            if len(person['vegetarian_splits']) >= 3 and not person['meat_splits']
        ]

    async def set_contact_preference(
        self, user_id: uuid.UUID, name: str, dietary_preference: str | None,
    ) -> SplitContactModel:
        clean_name = name.strip()
        normalized_name = clean_name.casefold()
        if not clean_name or len(clean_name) > 100:
            raise ValueError('Contact name must be between 1 and 100 characters.')
        if dietary_preference not in {None, 'vegetarian', 'vegan', 'omnivore'}:
            raise ValueError('Dietary preference must be vegetarian, vegan, or omnivore.')
        contact = await self.session.scalar(
            select(SplitContactModel).where(
                SplitContactModel.user_id == user_id,
                SplitContactModel.normalized_name == normalized_name,
            )
        )
        if contact is None:
            contact = SplitContactModel(
                id=uuid.uuid4(), user_id=user_id, name=clean_name, normalized_name=normalized_name,
            )
            self.session.add(contact)
        else:
            contact.name = clean_name
        contact.dietary_preference = dietary_preference
        contact.preference_confirmed_at = datetime.now(UTC) if dietary_preference else None
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise ValueError('This split contact already exists. Please try again.') from error
        return contact

    async def delete_contact_preference(self, user_id: uuid.UUID, contact_id: uuid.UUID) -> bool:
        contact = await self.session.scalar(
            select(SplitContactModel).where(SplitContactModel.user_id == user_id, SplitContactModel.id == contact_id)
        )
        if contact is None:
            return False
        await self.session.delete(contact)
        await self.session.commit()
        return True
