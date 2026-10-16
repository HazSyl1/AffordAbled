from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.services.split_service import ParticipantShare
from app.infrastructure.database.models import SplitModel, SplitParticipantModel, TransactionModel


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
