from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.entities import Category, CategoryType
from app.domain.repositories import CategoryRepository


@dataclass
class CategoryTools:
    category_repository: CategoryRepository

    async def ensure_category_exists(
        self,
        *,
        user_id: uuid.UUID,
        category_name: str,
        category_type: CategoryType,
        existing_categories: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        normalized_target_name = self._normalize_lookup_text(category_name)
        existing_match = next(
            (
                category
                for category in existing_categories
                if category.get('type') == category_type.value
                and self._normalize_lookup_text(str(category.get('name') or '')) == normalized_target_name
            ),
            None,
        )
        if existing_match is not None:
            return existing_match

        try:
            created_category = await self.category_repository.create(
                Category(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    name=category_name,
                    icon=None,
                    color=None,
                    type=category_type,
                    created_at=datetime.now(UTC),
                )
            )
            return {
                'id': str(created_category.id),
                'name': created_category.name,
                'type': created_category.type.value,
            }
        except Exception:
            refreshed_categories = await self.category_repository.list_for_user(user_id)
            return next(
                (
                    {
                        'id': str(category.id),
                        'name': category.name,
                        'type': category.type.value,
                    }
                    for category in refreshed_categories
                    if category.type == category_type
                    and self._normalize_lookup_text(category.name) == normalized_target_name
                ),
                None,
            )

    @staticmethod
    def _normalize_lookup_text(value: str) -> str:
        return ' '.join(''.join(char if char.isalnum() else ' ' for char in value.lower()).split())
