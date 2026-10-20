from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.application.dto import CreateTransactionInput, UpdateTransactionInput
from app.domain.entities import Account, CategoryType, Transaction, TransactionType
from app.domain.exceptions import (
    AccountNotFoundError,
    CategoryNotFoundError,
    InvalidTransactionError,
    TransactionNotFoundError,
)
from app.domain.repositories import AccountRepository, CategoryRepository, TransactionRepository

logger = logging.getLogger(__name__)


class LinkedSplitLookup(Protocol):
    async def is_linked(self, user_id: uuid.UUID, transaction_id: uuid.UUID) -> bool: ...


class MemoryEventWriter(Protocol):
    async def add_review_event(self, **kwargs): ...
    async def add_chat_analysis(self, **kwargs) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


@dataclass
class TransactionService:
    transaction_repository: TransactionRepository
    account_repository: AccountRepository
    category_repository: CategoryRepository
    split_repository: LinkedSplitLookup | None = None
    memory_event_writer: MemoryEventWriter | None = None

    async def create_transaction(self, data: CreateTransactionInput) -> Transaction:
        await self._validate_transaction(
            user_id=data.user_id,
            account_id=data.account_id,
            transaction_type=data.type,
            amount_paise=data.amount_paise,
            category_id=data.category_id,
            to_account_id=data.to_account_id,
        )

        now = datetime.now(UTC)
        transaction = Transaction(
            id=uuid.uuid4(),
            user_id=data.user_id,
            account_id=data.account_id,
            to_account_id=data.to_account_id,
            category_id=data.category_id,
            type=data.type,
            amount_paise=data.amount_paise,
            merchant=data.merchant,
            note=data.note,
            occurred_at=data.occurred_at,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )

        await self._apply_balance_effect(transaction)
        created = await self.transaction_repository.create(transaction)
        if self.memory_event_writer is not None and (data.review_event or data.memory_review_context):
            # Transaction, explicit review evidence, and opt-in conversation
            # analysis job share one commit. The worker cannot see a job for a
            # transaction that was not saved.
            try:
                if data.review_event:
                    await self.memory_event_writer.add_review_event(
                        user_id=data.user_id,
                        transaction_id=transaction.id,
                        action=data.review_event['action'],
                        source=data.review_event.get('source', 'manual'),
                        before=data.review_event.get('before') or {},
                        after=data.review_event.get('after') or {},
                    )
                if data.memory_review_context:
                    await self.memory_event_writer.add_chat_analysis(
                        user_id=data.user_id,
                        transaction_id=transaction.id,
                        signal_type=data.memory_review_context['signal_type'],
                        payload=data.memory_review_context['payload'],
                    )
                await self.memory_event_writer.commit()
            except Exception:  # noqa: BLE001 - transaction is already committed
                await self.memory_event_writer.rollback()
                logger.exception('memory.review_event.capture_failed', extra={
                    'source': (data.review_event or {}).get('source', 'manual'),
                    'transaction_id': str(transaction.id),
                })
                # The transaction itself is still important. Re-stage and
                # commit it without optional memory work after rolling back.
                await self.transaction_repository.create(transaction)
                commit = getattr(self.transaction_repository, 'commit', None)
                if commit is not None:
                    await commit()
        else:
            commit = getattr(self.transaction_repository, 'commit', None)
            if commit is not None:
                await commit()
        return created

    async def list_transactions(self, user_id: uuid.UUID) -> list[Transaction]:
        return await self.transaction_repository.list_for_user(user_id, include_deleted=False)

    async def get_transaction(self, user_id: uuid.UUID, transaction_id: uuid.UUID) -> Transaction:
        transaction = await self.transaction_repository.get_for_user(
            transaction_id,
            user_id,
            include_deleted=False,
        )
        if transaction is None:
            raise TransactionNotFoundError(str(transaction_id))
        return transaction

    async def update_transaction(
        self,
        user_id: uuid.UUID,
        transaction_id: uuid.UUID,
        data: UpdateTransactionInput,
    ) -> Transaction:
        transaction = await self.get_transaction(user_id, transaction_id)
        before_review = {
            'account_id': str(transaction.account_id),
            'category_id': str(transaction.category_id) if transaction.category_id else None,
            'merchant': transaction.merchant,
        }
        account_id = data.account_id if data.account_id is not None else transaction.account_id
        transaction_type = data.type if data.type is not None else transaction.type
        amount_paise = data.amount_paise if data.amount_paise is not None else transaction.amount_paise
        category_id = data.category_id if data.category_id is not None else transaction.category_id
        to_account_id = data.to_account_id if data.to_account_id is not None else transaction.to_account_id

        if self.split_repository is not None and await self.split_repository.is_linked(user_id, transaction_id):
            if (account_id != transaction.account_id or transaction_type != transaction.type or
                    amount_paise != transaction.amount_paise or category_id != transaction.category_id):
                raise InvalidTransactionError(
                    'Remove the split before changing its linked transaction amount, type, account, or category.'
                )

        await self._validate_transaction(
            user_id=user_id,
            account_id=account_id,
            transaction_type=transaction_type,
            amount_paise=amount_paise,
            category_id=category_id,
            to_account_id=to_account_id,
        )

        # Validate the complete replacement before touching any persisted balance. This is
        # especially important for chat-driven edits, where model output is untrusted input.
        await self._revert_balance_effect(transaction)

        transaction.account_id = account_id
        transaction.type = transaction_type
        transaction.amount_paise = amount_paise
        transaction.category_id = category_id
        transaction.to_account_id = to_account_id

        if data.occurred_at is not None:
            transaction.occurred_at = data.occurred_at
        if data.merchant is not None:
            transaction.merchant = data.merchant
        if data.note is not None:
            transaction.note = data.note

        transaction.updated_at = datetime.now(UTC)
        await self._apply_balance_effect(transaction)
        review_event = data.review_event
        if review_event is None and (
            account_id != uuid.UUID(before_review['account_id'])
            or (str(category_id) if category_id else None) != before_review['category_id']
        ):
            # User edits from clients predating the explicit review_event field,
            # or clients that omit it, must still feed preference learning.
            review_event = {
                'action': 'edited',
                'source': 'transaction_edit',
                'before': before_review,
                'after': {
                    'account_id': str(transaction.account_id),
                    'category_id': str(transaction.category_id) if transaction.category_id else None,
                    'merchant': transaction.merchant,
                },
            }
        if self.memory_event_writer is not None and review_event:
            await self.memory_event_writer.add_review_event(
                user_id=user_id,
                transaction_id=transaction.id,
                action=review_event['action'],
                source=review_event.get('source', 'manual'),
                before=review_event.get('before') or {},
                after=review_event.get('after') or {},
            )
        return await self.transaction_repository.update(transaction)

    async def soft_delete_transaction(self, user_id: uuid.UUID, transaction_id: uuid.UUID) -> None:
        transaction = await self.get_transaction(user_id, transaction_id)
        if self.split_repository is not None and await self.split_repository.is_linked(user_id, transaction_id):
            raise InvalidTransactionError('Remove the split before deleting its linked transaction.')
        await self._revert_balance_effect(transaction)

        deleted = await self.transaction_repository.soft_delete_for_user(transaction_id, user_id)
        if not deleted:
            raise TransactionNotFoundError(str(transaction_id))

    async def restore_transaction(self, user_id: uuid.UUID, transaction_id: uuid.UUID) -> None:
        transaction = await self.transaction_repository.get_for_user(
            transaction_id,
            user_id,
            include_deleted=True,
        )
        if transaction is None or transaction.deleted_at is None:
            raise TransactionNotFoundError(str(transaction_id))

        await self._validate_transaction(
            user_id=user_id,
            account_id=transaction.account_id,
            transaction_type=transaction.type,
            amount_paise=transaction.amount_paise,
            category_id=transaction.category_id,
            to_account_id=transaction.to_account_id,
        )
        await self._apply_balance_effect(transaction)

        restored = await self.transaction_repository.restore_for_user(transaction_id, user_id)
        if not restored:
            raise TransactionNotFoundError(str(transaction_id))

    async def _validate_transaction(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        transaction_type: TransactionType,
        amount_paise: int,
        category_id: uuid.UUID | None,
        to_account_id: uuid.UUID | None,
    ) -> None:
        if amount_paise <= 0:
            raise InvalidTransactionError('amount_paise must be greater than zero')

        source_account = await self.account_repository.get_for_user(account_id, user_id)
        if source_account is None:
            raise AccountNotFoundError(str(account_id))

        if transaction_type == TransactionType.TRANSFER:
            if category_id is not None:
                raise InvalidTransactionError('transfer transactions cannot have a category')
            if to_account_id is None:
                raise InvalidTransactionError('transfer transactions require to_account_id')
            if to_account_id == account_id:
                raise InvalidTransactionError('transfer source and destination accounts must be different')

            destination_account = await self.account_repository.get_for_user(to_account_id, user_id)
            if destination_account is None:
                raise AccountNotFoundError(str(to_account_id))

            if source_account.balance_paise < amount_paise:
                raise InvalidTransactionError('insufficient source account balance for transfer')
            return

        if to_account_id is not None:
            raise InvalidTransactionError('only transfer transactions can define to_account_id')
        if category_id is None:
            raise InvalidTransactionError('non-transfer transactions require a category')

        category = await self.category_repository.get_for_user(category_id, user_id)
        if category is None:
            raise CategoryNotFoundError(str(category_id))

        if transaction_type == TransactionType.EXPENSE and category.type != CategoryType.EXPENSE:
            raise InvalidTransactionError('expense transactions require an expense category')

        if (
            transaction_type in {TransactionType.INCOME, TransactionType.REFUND}
            and category.type != CategoryType.INCOME
        ):
            raise InvalidTransactionError('income and refund transactions require an income category')

    async def _apply_balance_effect(self, transaction: Transaction) -> None:
        if transaction.type == TransactionType.TRANSFER:
            source_account = await self._get_account_for_user(transaction.user_id, transaction.account_id)
            destination_account_id = transaction.to_account_id
            if destination_account_id is None:
                raise InvalidTransactionError('transfer transactions require to_account_id')
            destination_account = await self._get_account_for_user(transaction.user_id, destination_account_id)

            if source_account.balance_paise < transaction.amount_paise:
                raise InvalidTransactionError('insufficient source account balance for transfer')

            source_account.balance_paise -= transaction.amount_paise
            destination_account.balance_paise += transaction.amount_paise
            await self._save_account(source_account)
            await self._save_account(destination_account)
            return

        source_account = await self._get_account_for_user(transaction.user_id, transaction.account_id)
        if transaction.type == TransactionType.EXPENSE:
            source_account.balance_paise -= transaction.amount_paise
        else:
            source_account.balance_paise += transaction.amount_paise
        await self._save_account(source_account)

    async def _revert_balance_effect(self, transaction: Transaction) -> None:
        if transaction.type == TransactionType.TRANSFER:
            source_account = await self._get_account_for_user(transaction.user_id, transaction.account_id)
            destination_account_id = transaction.to_account_id
            if destination_account_id is None:
                raise InvalidTransactionError('transfer transactions require to_account_id')
            destination_account = await self._get_account_for_user(transaction.user_id, destination_account_id)

            source_account.balance_paise += transaction.amount_paise
            destination_account.balance_paise -= transaction.amount_paise
            await self._save_account(source_account)
            await self._save_account(destination_account)
            return

        source_account = await self._get_account_for_user(transaction.user_id, transaction.account_id)
        if transaction.type == TransactionType.EXPENSE:
            source_account.balance_paise += transaction.amount_paise
        else:
            source_account.balance_paise -= transaction.amount_paise
        await self._save_account(source_account)

    async def _get_account_for_user(self, user_id: uuid.UUID, account_id: uuid.UUID) -> Account:
        account = await self.account_repository.get_for_user(account_id, user_id)
        if account is None:
            raise AccountNotFoundError(str(account_id))
        return account

    async def _save_account(self, account: Account) -> None:
        account.updated_at = datetime.now(UTC)
        await self.account_repository.update(account)
