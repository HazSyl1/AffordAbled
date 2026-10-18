from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.dto import ImportTransactionInput
from app.domain.entities import Account, Category, CategoryType, TransactionType
from app.domain.exceptions import InvalidImportError
from app.domain.repositories import (
    AccountRepository,
    CategoryRepository,
    TransactionImportRepository,
    TransactionRepository,
)
from app.infrastructure.files.transaction_import import parse_amount_paise, parse_occurred_at, parse_transaction_file


@dataclass
class ImportValidation:
    file_hash: str
    row_count: int
    valid_count: int
    already_imported: bool
    preview_rows: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    rows: list[ImportTransactionInput]


@dataclass
class TransactionImportService:
    account_repository: AccountRepository
    category_repository: CategoryRepository
    transaction_repository: TransactionRepository
    import_repository: TransactionImportRepository

    async def preview(self, *, user_id: uuid.UUID, filename: str, content: bytes, timezone: str) -> ImportValidation:
        try:
            user_timezone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise InvalidImportError('Invalid timezone.') from exc
        source_rows = parse_transaction_file(filename, content)
        file_hash = hashlib.sha256(content).hexdigest()
        accounts = await self.account_repository.list_for_user(user_id)
        categories = await self.category_repository.list_for_user(user_id)
        source_ids: set[uuid.UUID] = set()
        for source in source_rows:
            identifier = source.values.get('transaction_id', '')
            if identifier:
                try:
                    source_ids.add(uuid.UUID(identifier))
                except ValueError:
                    pass  # This row receives a precise validation error below.
        existing_ids = await self.transaction_repository.existing_ids_for_user(user_id, source_ids)
        parsed_rows: list[ImportTransactionInput] = []
        preview_rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for source in source_rows:
            values = source.values
            display: dict[str, Any] = {
                'row_number': source.row_number,
                'type': values.get('type', ''),
                'amount': values.get('amount_paise') or values.get('amount_rupees', ''),
                'account': values.get('account', ''),
                'category': values.get('category', ''),
                'merchant': values.get('merchant', ''),
            }
            try:
                transaction_type = self._transaction_type(values.get('type', ''))
                amount_paise = parse_amount_paise(values)
                occurred_at = parse_occurred_at(values.get('occurred_at', ''), user_timezone)
                account = self._resolve_account(accounts, values.get('account', ''), values.get('account_id', ''))
                to_account = None
                category = None
                if transaction_type == TransactionType.TRANSFER:
                    to_account = self._resolve_account(
                        accounts, values.get('to_account', ''), values.get('to_account_id', '')
                    )
                    if to_account.id == account.id:
                        raise ValueError('transfer source and destination must differ')
                    if values.get('category') or values.get('category_id'):
                        raise ValueError('transfers cannot have a category')
                else:
                    expected_type = (
                        CategoryType.EXPENSE if transaction_type == TransactionType.EXPENSE else CategoryType.INCOME
                    )
                    category = self._resolve_category(
                        categories, values.get('category', ''), values.get('category_id', ''), expected_type
                    )
                    if values.get('to_account') or values.get('to_account_id'):
                        raise ValueError('only transfers can have a destination account')
                source_id = values.get('transaction_id', '')
                if source_id:
                    try:
                        parsed_source_id = uuid.UUID(source_id)
                    except ValueError as exc:
                        raise ValueError('transaction_id must be a UUID') from exc
                    if parsed_source_id in existing_ids:
                        raise ValueError('this transaction already exists in your account')
                merchant = values.get('merchant', '').strip() or None
                note = values.get('note', '').strip() or None
                if merchant and len(merchant) > 255:
                    raise ValueError('merchant must be 255 characters or fewer')
                if note and len(note) > 4_000:
                    raise ValueError('note must be 4,000 characters or fewer')
                parsed_rows.append(
                    ImportTransactionInput(
                        account_id=account.id,
                        type=transaction_type,
                        amount_paise=amount_paise,
                        occurred_at=occurred_at,
                        category_id=category.id if category else None,
                        to_account_id=to_account.id if to_account else None,
                        merchant=merchant,
                        note=note,
                    )
                )
                display.update(
                    type=transaction_type.value,
                    amount_paise=amount_paise,
                    account=account.name,
                    category=category.name if category else '',
                    to_account=to_account.name if to_account else '',
                    occurred_at=occurred_at.isoformat(),
                )
            except ValueError as exc:
                error = {'row_number': source.row_number, 'message': str(exc)}
                errors.append(error)
                display['error'] = str(exc)
            if len(preview_rows) < 20:
                preview_rows.append(display)
        return ImportValidation(
            file_hash=file_hash,
            row_count=len(source_rows),
            valid_count=len(parsed_rows),
            already_imported=await self.import_repository.already_imported(user_id, file_hash),
            preview_rows=preview_rows,
            errors=errors[:100],
            rows=parsed_rows,
        )

    async def commit(
        self, *, user_id: uuid.UUID, filename: str, content: bytes, timezone: str, preview_hash: str
    ) -> int:
        if hashlib.sha256(content).hexdigest() != preview_hash:
            raise InvalidImportError('The file changed since preview. Preview it again.')
        validation = await self.preview(user_id=user_id, filename=filename, content=content, timezone=timezone)
        if validation.errors or validation.valid_count != validation.row_count:
            raise InvalidImportError('Fix the highlighted rows and preview the file again before importing.')
        return await self.import_repository.create_batch(user_id, validation.file_hash, validation.rows)

    @staticmethod
    def _transaction_type(raw: str) -> TransactionType:
        normalized = raw.strip().casefold()
        normalized = {'debit': 'expense', 'credit': 'income'}.get(normalized, normalized)
        try:
            return TransactionType(normalized)
        except ValueError as exc:
            raise ValueError('type must be expense, income, transfer, or refund') from exc

    @staticmethod
    def _resolve_account(accounts: list[Account], name: str, identifier: str) -> Account:
        if identifier:
            try:
                matching_id = uuid.UUID(identifier)
            except ValueError:
                raise ValueError('account_id must be a UUID') from None
            owned = next((account for account in accounts if account.id == matching_id), None)
            if owned is not None:
                return owned
            if not name:
                raise ValueError('account_id is not available to you')
        matches = [
            account for account in accounts if name and account.name.strip().casefold() == name.strip().casefold()
        ]
        if len(matches) != 1:
            raise ValueError(f'account "{name or identifier}" is missing or ambiguous')
        return matches[0]

    @staticmethod
    def _resolve_category(categories: list[Category], name: str, identifier: str, expected: CategoryType) -> Category:
        if identifier:
            try:
                matching_id = uuid.UUID(identifier)
            except ValueError:
                raise ValueError('category_id must be a UUID') from None
            owned = next((category for category in categories if category.id == matching_id), None)
            if owned is not None:
                if owned.type != expected:
                    raise ValueError(f'category "{owned.name}" must be {expected.value}')
                return owned
            if not name:
                raise ValueError('category_id is not available to you')
        matches = [
            category for category in categories
            if name and category.name.strip().casefold() == name.strip().casefold() and category.type == expected
        ]
        if len(matches) != 1:
            raise ValueError(f'{expected.value} category "{name or identifier}" is missing or ambiguous')
        return matches[0]
