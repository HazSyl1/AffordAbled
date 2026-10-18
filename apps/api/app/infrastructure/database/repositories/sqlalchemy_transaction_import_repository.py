from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto import ImportTransactionInput
from app.domain.entities import CategoryType, TransactionType
from app.domain.exceptions import ImportAlreadyExistsError, InvalidImportError
from app.infrastructure.database.models import (
    AccountModel,
    CategoryModel,
    ExportArtifactModel,
    TransactionImportModel,
    TransactionModel,
)


class SqlAlchemyTransactionImportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def already_imported(self, user_id: uuid.UUID, file_hash: str) -> bool:
        exported = await self._session.execute(
            select(ExportArtifactModel.id).where(
                ExportArtifactModel.user_id == user_id,
                ExportArtifactModel.file_sha256 == file_hash,
            ).limit(1)
        )
        if exported.scalar_one_or_none() is not None:
            return True
        result = await self._session.execute(
            select(TransactionImportModel.id).where(
                TransactionImportModel.user_id == user_id,
                TransactionImportModel.file_hash == file_hash,
            )
        )
        return result.scalar_one_or_none() is not None

    async def create_batch(self, user_id: uuid.UUID, file_hash: str, rows: list[ImportTransactionInput]) -> int:
        if await self.already_imported(user_id, file_hash):
            raise ImportAlreadyExistsError('This file already exists in your account.')
        try:
            account_result = await self._session.execute(
                select(AccountModel).where(AccountModel.user_id == user_id).with_for_update()
            )
            accounts = {account.id: account for account in account_result.scalars().all()}
            category_result = await self._session.execute(select(CategoryModel).where(CategoryModel.user_id == user_id))
            categories = {category.id: category for category in category_result.scalars().all()}
            now = datetime.now(UTC)

            # Reports are newest first; apply historical credits before later transfers.
            for row in sorted(rows, key=lambda item: item.occurred_at):
                account = accounts.get(row.account_id)
                if account is None:
                    raise InvalidImportError('An account used by this file is no longer available.')
                if row.type == TransactionType.TRANSFER:
                    destination = accounts.get(row.to_account_id)
                    if destination is None or destination.id == account.id or row.category_id is not None:
                        raise InvalidImportError('A transfer needs two different owned accounts and no category.')
                    if account.balance_paise < row.amount_paise:
                        raise InvalidImportError('Insufficient source account balance for an imported transfer.')
                    account.balance_paise -= row.amount_paise
                    destination.balance_paise += row.amount_paise
                    destination.updated_at = now
                else:
                    if row.to_account_id is not None or row.category_id not in categories:
                        raise InvalidImportError('A non-transfer transaction needs an owned category.')
                    category = categories[row.category_id]
                    required_type = (
                        CategoryType.EXPENSE.value if row.type == TransactionType.EXPENSE else CategoryType.INCOME.value
                    )
                    if category.type != required_type:
                        raise InvalidImportError('An imported transaction uses a category of the wrong type.')
                    account.balance_paise += (
                        -row.amount_paise if row.type == TransactionType.EXPENSE else row.amount_paise
                    )
                account.updated_at = now
                self._session.add(
                    TransactionModel(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        account_id=row.account_id,
                        to_account_id=row.to_account_id,
                        category_id=row.category_id,
                        type=row.type.value,
                        amount_paise=row.amount_paise,
                        occurred_at=row.occurred_at,
                        merchant=row.merchant,
                        note=row.note,
                        created_at=now,
                        updated_at=now,
                    )
                )
            self._session.add(
                TransactionImportModel(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    file_hash=file_hash,
                    row_count=len(rows),
                    created_at=now,
                )
            )
            await self._session.commit()
            return len(rows)
        except IntegrityError as exc:
            await self._session.rollback()
            cause = getattr(exc.orig, '__cause__', None)
            constraint_name = getattr(cause, 'constraint_name', None)
            if constraint_name == 'uq_transaction_import_user_hash' or (
                'UNIQUE constraint failed: transaction_imports.user_id, transaction_imports.file_hash'
                in str(exc.orig)
            ):
                raise ImportAlreadyExistsError('This file already exists in your account.') from exc
            raise InvalidImportError('The import could not be saved. Please preview the file again.') from exc
        except Exception:
            await self._session.rollback()
            raise
