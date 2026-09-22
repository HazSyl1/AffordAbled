from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Category, CategoryType
from app.infrastructure.database.models import CategoryModel


class SqlAlchemyCategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, category: Category) -> Category:
        model = CategoryModel(
            id=category.id,
            user_id=category.user_id,
            name=category.name,
            icon=category.icon,
            color=category.color,
            type=category.type.value,
        )
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def get_for_user(self, category_id: uuid.UUID, user_id: uuid.UUID) -> Category | None:
        result = await self._session.execute(
            select(CategoryModel).where(CategoryModel.id == category_id, CategoryModel.user_id == user_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_for_user(self, user_id: uuid.UUID) -> list[Category]:
        result = await self._session.execute(
            select(CategoryModel).where(CategoryModel.user_id == user_id).order_by(CategoryModel.created_at)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def update(self, category: Category) -> Category:
        model = await self._session.get(CategoryModel, category.id)
        if model is None or model.user_id != category.user_id:
            raise LookupError(str(category.id))
        model.name = category.name
        model.icon = category.icon
        model.color = category.color
        model.type = category.type.value
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def delete_for_user(self, category_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            delete(CategoryModel).where(CategoryModel.id == category_id, CategoryModel.user_id == user_id)
        )
        await self._session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def _to_entity(model: CategoryModel) -> Category:
        return Category(
            id=model.id,
            user_id=model.user_id,
            name=model.name,
            icon=model.icon,
            color=model.color,
            type=CategoryType(model.type),
            created_at=model.created_at,
        )
