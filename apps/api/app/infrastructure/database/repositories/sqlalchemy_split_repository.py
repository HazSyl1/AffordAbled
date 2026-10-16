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
    SplitModel,
    SplitParticipantModel,
    TransactionModel,
    UserModel,
)

SPLIT_REPAYMENT_CATEGORY = 'Split repayment'


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
        repayment_id = await self.session.scalar(
            select(SplitParticipantModel.id).join(SplitModel).where(
                SplitModel.user_id == user_id,
                SplitParticipantModel.repayment_transaction_id == transaction_id,
            )
        )
        return repayment_id is not None

    async def create(
        self, user_id: uuid.UUID, transaction_id: uuid.UUID, title: str,
        owner_share_paise: int, participants: list[ParticipantShare],
    ) -> SplitModel:
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
            title=title, owner_share_paise=owner_share_paise,
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

    async def list_for_user(self, user_id: uuid.UUID) -> list[SplitModel]:
        rows = await self.session.scalars(
            select(SplitModel).where(SplitModel.user_id == user_id)
            .options(selectinload(SplitModel.participants))
            .order_by(SplitModel.created_at.desc(), SplitModel.id.desc())
        )
        return list(rows.all())

    async def get_for_user(self, user_id: uuid.UUID, split_id: uuid.UUID) -> SplitModel | None:
        return await self.session.scalar(
            select(SplitModel).where(SplitModel.id == split_id, SplitModel.user_id == user_id)
            .options(selectinload(SplitModel.participants))
        )

    async def update(
        self, user_id: uuid.UUID, split_id: uuid.UUID, title: str,
        owner_share_paise: int, participants: list[ParticipantEditShare],
    ) -> SplitModel | None:
        split = await self.get_for_user(user_id, split_id)
        if split is None:
            return None
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
        if participant.settled_paise == participant.share_paise:
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
        if repayment.amount_paise != participant.share_paise:
            raise ValueError('Repayment amount must match this person’s share exactly.')
        already_linked = await self.session.scalar(
            select(SplitParticipantModel.id).where(
                SplitParticipantModel.repayment_transaction_id == repayment_transaction_id,
            )
        )
        if already_linked is not None:
            raise ValueError('That repayment is already linked to a split.')
        participant.settled_paise = participant.share_paise
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
        # Serialize repayments for this user, including first-time category creation.
        await self.session.scalar(select(UserModel.id).where(UserModel.id == user_id).with_for_update())
        split = await self.get_for_user(user_id, split_id)
        if split is None:
            return None
        participant = next((person for person in split.participants if person.id == participant_id), None)
        if participant is None:
            return None
        if participant.settled_paise == participant.share_paise or participant.repayment_transaction_id is not None:
            raise ValueError('This person is already repaid.')
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
            category_id=category.id, type='income', amount_paise=participant.share_paise,
            merchant=participant.name, note=f'Repayment for split: {split.title}',
            occurred_at=now, created_at=now, updated_at=now,
        )
        self.session.add(transaction)
        try:
            # The participant is an existing row. Insert its new FK target before updating the link.
            await self.session.flush()
            account.balance_paise += participant.share_paise
            account.updated_at = now
            participant.settled_paise = participant.share_paise
            participant.repayment_transaction_id = transaction.id
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
        return list(rows.all())
