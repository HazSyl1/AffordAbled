from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.dto import CreateTransactionInput, UpdateTransactionInput
from app.domain.entities import Account, CategoryType, Transaction, TransactionType
from app.domain.exceptions import (
    AccountNotFoundError,
    CategoryNotFoundError,
    InvalidTransactionError,
    TransactionNotFoundError,
)
from app.domain.repositories import AccountRepository, CategoryRepository, TransactionRepository


@dataclass
class TransactionService:
    transaction_repository: TransactionRepository
    account_repository: AccountRepository
    category_repository: CategoryRepository

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
        return await self.transaction_repository.create(transaction)

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
        await self._revert_balance_effect(transaction)

        account_id = data.account_id if data.account_id is not None else transaction.account_id
        transaction_type = data.type if data.type is not None else transaction.type
        amount_paise = data.amount_paise if data.amount_paise is not None else transaction.amount_paise
        category_id = data.category_id if data.category_id is not None else transaction.category_id
        to_account_id = data.to_account_id if data.to_account_id is not None else transaction.to_account_id

        await self._validate_transaction(
            user_id=user_id,
            account_id=account_id,
            transaction_type=transaction_type,
            amount_paise=amount_paise,
            category_id=category_id,
            to_account_id=to_account_id,
        )

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
        return await self.transaction_repository.update(transaction)

    async def soft_delete_transaction(self, user_id: uuid.UUID, transaction_id: uuid.UUID) -> None:
        transaction = await self.get_transaction(user_id, transaction_id)
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
