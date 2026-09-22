from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.dto import CreateCategoryInput, UpdateCategoryInput
from app.domain.entities import Category
from app.domain.exceptions import CategoryNotFoundError
from app.domain.repositories import CategoryRepository


@dataclass
class CategoryService:
    category_repository: CategoryRepository

    async def create_category(self, data: CreateCategoryInput) -> Category:
        category = Category(
            id=uuid.uuid4(),
            user_id=data.user_id,
            name=data.name,
            icon=data.icon,
            color=data.color,
            type=data.type,
            created_at=datetime.now(UTC),
        )
        return await self.category_repository.create(category)

    async def list_categories(self, user_id: uuid.UUID) -> list[Category]:
        return await self.category_repository.list_for_user(user_id)

    async def update_category(
        self,
        user_id: uuid.UUID,
        category_id: uuid.UUID,
        data: UpdateCategoryInput,
    ) -> Category:
        category = await self._get_category(user_id, category_id)
        if data.name is not None:
            category.name = data.name
        if data.icon is not None:
            category.icon = data.icon
        if data.color is not None:
            category.color = data.color
        if data.type is not None:
            category.type = data.type
        return await self.category_repository.update(category)

    async def delete_category(self, user_id: uuid.UUID, category_id: uuid.UUID) -> None:
        deleted = await self.category_repository.delete_for_user(category_id, user_id)
        if not deleted:
            raise CategoryNotFoundError(str(category_id))

    async def _get_category(self, user_id: uuid.UUID, category_id: uuid.UUID) -> Category:
        category = await self.category_repository.get_for_user(category_id, user_id)
        if category is None:
            raise CategoryNotFoundError(str(category_id))
        return category
