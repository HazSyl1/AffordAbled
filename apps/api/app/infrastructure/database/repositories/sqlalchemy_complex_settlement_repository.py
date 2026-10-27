from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.services.complex_settlement import SettlementInput, calculate_complex_settlement, net_transfers
from app.infrastructure.database.models import (
    AccountModel,
    CategoryModel,
    SettlementDraftModel,
    SettlementPlanModel,
    SettlementPlanTransactionModel,
    SettlementPlanTransferModel,
    SplitModel,
    TransactionModel,
    UserModel,
)


def _preview(data: SettlementInput, prior_plan: SettlementPlanModel | None = None) -> dict:
    result = calculate_complex_settlement(data)
    balances = result.balances_paise.copy()
    settled: list[dict] = []
    if prior_plan is not None:
        for transfer in prior_plan.transfers:
            if transfer.settled_at is None:
                continue
            if transfer.debtor not in balances or transfer.creditor not in balances:
                raise ValueError('A revision cannot remove a person involved in a settled transfer.')
            balances[transfer.debtor] += transfer.amount_paise
            balances[transfer.creditor] -= transfer.amount_paise
            settled.append({
                'id': str(transfer.id), 'debtor': transfer.debtor,
                'creditor': transfer.creditor, 'amount_paise': transfer.amount_paise,
            })
    return {
        'bills': result.bills, 'shares_paise': result.shares_paise,
        'paid_paise': result.paid_paise, 'balances_paise': balances,
        'transfers': net_transfers(balances), 'settled_transfers': settled,
        'total_paise': result.total_paise,
    }


class SqlAlchemyComplexSettlementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_draft(self, user_id: uuid.UUID, draft_id: uuid.UUID) -> SettlementDraftModel | None:
        return await self.session.scalar(select(SettlementDraftModel).where(
            SettlementDraftModel.id == draft_id, SettlementDraftModel.user_id == user_id,
        ))

    async def create_draft(
        self, user_id: uuid.UUID, request_key: str, data: SettlementInput,
        revision_plan_id: uuid.UUID | None = None,
    ) -> SettlementDraftModel:
        prior_plan = await self.get_plan(user_id, revision_plan_id) if revision_plan_id else None
        if revision_plan_id is not None and prior_plan is None:
            raise LookupError('Settlement plan was not found.')
        existing = await self.session.scalar(select(SettlementDraftModel).where(
            SettlementDraftModel.user_id == user_id, SettlementDraftModel.request_key == request_key,
        ))
        normalized = data.model_dump(mode='json')
        if existing is not None:
            if existing.input_json != normalized or existing.revision_plan_id != revision_plan_id:
                raise ValueError('That request key already belongs to a different draft.')
            return existing
        draft = SettlementDraftModel(
            id=uuid.uuid4(), user_id=user_id, request_key=request_key, version=1, status='draft',
            input_json=normalized, preview_json=_preview(data, prior_plan), revision_plan_id=revision_plan_id,
        )
        self.session.add(draft)
        await self.session.commit()
        return draft

    async def update_draft(
        self, user_id: uuid.UUID, draft_id: uuid.UUID, version: int, data: SettlementInput,
    ) -> SettlementDraftModel:
        draft = await self.session.scalar(select(SettlementDraftModel).where(
            SettlementDraftModel.id == draft_id, SettlementDraftModel.user_id == user_id,
        ).with_for_update())
        if draft is None:
            raise LookupError('Settlement draft was not found.')
        if draft.status != 'draft' or draft.version != version:
            raise ValueError('This preview has changed. Reload it before editing.')
        draft.input_json = data.model_dump(mode='json')
        prior_plan = await self.get_plan(user_id, draft.revision_plan_id) if draft.revision_plan_id else None
        draft.preview_json = _preview(data, prior_plan)
        draft.version += 1
        await self.session.commit()
        return draft

    async def list_plans(self, user_id: uuid.UUID) -> list[SettlementPlanModel]:
        rows = await self.session.scalars(select(SettlementPlanModel).where(
            SettlementPlanModel.user_id == user_id,
        ).options(
            selectinload(SettlementPlanModel.transactions), selectinload(SettlementPlanModel.transfers),
        ).order_by(SettlementPlanModel.created_at.desc()))
        return list(rows.all())

    async def get_plan(self, user_id: uuid.UUID, plan_id: uuid.UUID) -> SettlementPlanModel | None:
        return await self.session.scalar(select(SettlementPlanModel).where(
            SettlementPlanModel.id == plan_id, SettlementPlanModel.user_id == user_id,
        ).options(
            selectinload(SettlementPlanModel.transactions), selectinload(SettlementPlanModel.transfers),
        ))

    async def confirm(self, user_id: uuid.UUID, draft_id: uuid.UUID, version: int) -> SettlementPlanModel:
        # Serialize confirmation and repayment for a wallet owner.
        await self.session.scalar(select(UserModel.id).where(UserModel.id == user_id).with_for_update())
        draft = await self.session.scalar(select(SettlementDraftModel).where(
            SettlementDraftModel.id == draft_id, SettlementDraftModel.user_id == user_id,
        ).with_for_update())
        if draft is None:
            raise LookupError('Settlement draft was not found.')
        if draft.status == 'confirmed' and draft.plan_id:
            plan = await self.get_plan(user_id, draft.plan_id)
            if plan is not None:
                return plan
        if draft.status != 'draft' or draft.version != version:
            raise ValueError('This preview has changed. Reload it before confirming.')
        data = SettlementInput.model_validate(draft.input_json)
        plan = await self.get_plan(user_id, draft.revision_plan_id) if draft.revision_plan_id else None
        if draft.revision_plan_id and plan is None:
            raise LookupError('Settlement plan was not found.')
        preview = _preview(data, plan)
        if preview != draft.preview_json:
            raise ValueError('The saved preview is stale. Review the draft again.')
        prior_linked_ids = {row.transaction_id for row in plan.transactions} if plan else set()
        proposed_linked_ids = {
            uuid.UUID(payment.transaction_id)
            for bill in data.bills for payment in bill.payments
            if payment.person.strip().casefold() == 'you' and payment.transaction_id
        }
        if plan is not None and prior_linked_ids != proposed_linked_ids:
            raise ValueError('A revision must retain the same wallet transactions.')
        persisted_data = data.model_copy(deep=True)
        if plan is None:
            plan = SettlementPlanModel(
                id=uuid.uuid4(), user_id=user_id, title=data.title, total_paise=preview['total_paise'],
                input_json=data.model_dump(mode='json'), preview_json=preview,
            )
            self.session.add(plan)
        else:
            plan.title = data.title
            plan.total_paise = preview['total_paise']
            plan.input_json = data.model_dump(mode='json')
            plan.preview_json = preview
            for transfer in list(plan.transfers):
                if transfer.settled_at is None:
                    plan.transfers.remove(transfer)
            await self.session.flush()
        linked_ids: set[uuid.UUID] = set()
        for bill_index, bill in enumerate(data.bills):
            for payment_index, payment in enumerate(bill.payments):
                payment_amount = (
                    payment.amount_paise if payment.amount_paise is not None
                    else preview['bills'][bill_index]['payment_amounts_paise'][payment_index]
                )
                persisted_data.bills[bill_index].payments[payment_index].amount_paise = payment_amount
                if payment.person.strip().casefold() != 'you':
                    if payment.transaction_id or payment.account_id:
                        raise ValueError('Only your own payments may link to wallet accounts.')
                    continue
                if payment.transaction_id:
                    transaction_id = uuid.UUID(payment.transaction_id)
                    transaction = await self.session.scalar(select(TransactionModel).where(
                        TransactionModel.id == transaction_id, TransactionModel.user_id == user_id,
                        TransactionModel.deleted_at.is_(None), TransactionModel.type == 'expense',
                    ))
                    if transaction is None or transaction.amount_paise != payment_amount:
                        raise ValueError('A linked expense must exist and match the payment amount.')
                    legacy = await self.session.scalar(select(SplitModel.id).where(
                        SplitModel.user_id == user_id, SplitModel.transaction_id == transaction_id,
                    ))
                    if legacy is not None:
                        raise ValueError('That expense already has a split.')
                    linked = await self.session.get(SettlementPlanTransactionModel, transaction_id)
                    if linked is not None and linked.plan_id != plan.id:
                        raise ValueError('That expense already belongs to another settlement plan.')
                else:
                    if not payment.account_id or not payment.category_id:
                        raise ValueError('New wallet payments need an account and expense category.')
                    account = await self.session.scalar(select(AccountModel).where(
                        AccountModel.id == uuid.UUID(payment.account_id),
                        AccountModel.user_id == user_id, AccountModel.is_active.is_(True),
                    ))
                    category = await self.session.scalar(select(CategoryModel).where(
                        CategoryModel.id == uuid.UUID(payment.category_id),
                        CategoryModel.user_id == user_id, CategoryModel.type == 'expense',
                    ))
                    if account is None or category is None:
                        raise ValueError('Choose an active account and expense category that belong to you.')
                    occurred_at = (
                        datetime.fromisoformat(payment.occurred_at)
                        if payment.occurred_at else datetime.now(UTC)
                    )
                    if occurred_at.tzinfo is None:
                        raise ValueError('Transaction dates must include a timezone.')
                    now = datetime.now(UTC)
                    transaction_id = uuid.uuid4()
                    self.session.add(TransactionModel(
                        id=transaction_id, user_id=user_id, account_id=account.id,
                        category_id=category.id, type='expense', amount_paise=payment_amount,
                        merchant=bill.merchant, note=f'Settlement plan: {data.title}',
                        occurred_at=occurred_at, created_at=now, updated_at=now,
                    ))
                    account.balance_paise -= payment_amount
                    account.updated_at = now
                    persisted_data.bills[bill_index].payments[payment_index].transaction_id = str(transaction_id)
                    persisted_data.bills[bill_index].payments[payment_index].occurred_at = occurred_at.isoformat()
                if transaction_id in linked_ids:
                    raise ValueError('A wallet transaction cannot appear twice in one plan.')
                linked_ids.add(transaction_id)
                if await self.session.get(SettlementPlanTransactionModel, transaction_id) is None:
                    self.session.add(SettlementPlanTransactionModel(transaction_id=transaction_id, plan_id=plan.id))
        if draft.revision_plan_id and prior_linked_ids != linked_ids:
            raise ValueError('A plan revision cannot change its linked transactions.')
        await self.session.flush()
        plan.input_json = persisted_data.model_dump(mode='json')
        self.session.add_all([
            SettlementPlanTransferModel(
                id=uuid.uuid4(), plan_id=plan.id, debtor=item['debtor'], creditor=item['creditor'],
                amount_paise=item['amount_paise'],
            ) for item in preview['transfers']
        ])
        draft.status = 'confirmed'
        draft.plan_id = plan.id
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        await self.session.refresh(plan, attribute_names=['transactions', 'transfers'])
        return await self.get_plan(user_id, plan.id)

    async def settle_transfer(
        self, user_id: uuid.UUID, plan_id: uuid.UUID, transfer_id: uuid.UUID,
        account_id: uuid.UUID | None,
    ) -> SettlementPlanModel:
        await self.session.scalar(select(UserModel.id).where(UserModel.id == user_id).with_for_update())
        plan = await self.get_plan(user_id, plan_id)
        if plan is None:
            raise LookupError('Settlement plan was not found.')
        transfer = next((item for item in plan.transfers if item.id == transfer_id), None)
        if transfer is None:
            raise LookupError('Settlement transfer was not found.')
        if transfer.settled_at is not None:
            return plan
        owner_involved = transfer.debtor == 'You' or transfer.creditor == 'You'
        if owner_involved and account_id is None:
            raise ValueError('Choose the wallet account used for this payment.')
        if not owner_involved and account_id is not None:
            raise ValueError('Friend-to-friend payments do not change your wallet.')
        now = datetime.now(UTC)
        if owner_involved:
            account = await self.session.scalar(select(AccountModel).where(
                AccountModel.id == account_id, AccountModel.user_id == user_id,
                AccountModel.is_active.is_(True),
            ))
            if account is None:
                raise LookupError('Wallet account was not found.')
            incoming = transfer.creditor == 'You'
            category_name = 'Split'
            category_type = 'income' if incoming else 'expense'
            category = await self.session.scalar(select(CategoryModel).where(
                CategoryModel.user_id == user_id, CategoryModel.name == category_name,
                CategoryModel.type == category_type,
            ))
            if category is None:
                category = CategoryModel(
                    id=uuid.uuid4(), user_id=user_id, name=category_name, type=category_type,
                )
                self.session.add(category)
                await self.session.flush()
            transaction_id = uuid.uuid4()
            self.session.add(TransactionModel(
                id=transaction_id, user_id=user_id, account_id=account.id,
                category_id=category.id, type=category_type, amount_paise=transfer.amount_paise,
                merchant=transfer.debtor if incoming else transfer.creditor,
                note=f'Settlement for {plan.title}', occurred_at=now, created_at=now, updated_at=now,
            ))
            # The transfer is an existing row: insert its new FK target before linking it.
            await self.session.flush()
            account.balance_paise += transfer.amount_paise if incoming else -transfer.amount_paise
            account.updated_at = now
            transfer.repayment_transaction_id = transaction_id
        transfer.settled_at = now
        await self.session.commit()
        return await self.get_plan(user_id, plan_id)
