from __future__ import annotations

import uuid
from typing import Any

from app.application.dto import CreateCategoryInput, UpdateCategoryInput
from app.application.services.category_service import CategoryService
from app.domain.entities import CategoryType
from app.infrastructure.ai.agents.contracts import HandoffContext


class CategoryToolset:
    """Authorization-safe category capabilities exposed only to the category brain."""

    def __init__(self, service: CategoryService) -> None:
        self._service = service

    def registry(self) -> dict[str, Any]:
        return {
            "list_categories": self.list_categories,
            "create_category": self.create_category,
            "update_category": self.update_category,
            "delete_category": self.delete_category,
        }

    async def list_categories(self, context: HandoffContext, _arguments: dict[str, Any]) -> dict[str, Any]:
        categories = await self._service.list_categories(context.user_id)
        return {"categories": [self._serialize(category) for category in categories]}

    async def create_category(self, context: HandoffContext, arguments: dict[str, Any]) -> dict[str, Any]:
        name = str(arguments.get("name") or "").strip()
        category_type = CategoryType(str(arguments.get("type") or "").strip().lower())
        if not name:
            raise ValueError("category name is required")
        existing = await self._service.list_categories(context.user_id)
        duplicate = next(
            (item for item in existing if item.name.casefold() == name.casefold() and item.type == category_type),
            None,
        )
        if duplicate is not None:
            return {"category": self._serialize(duplicate), "created": False}
        category = await self._service.create_category(
            CreateCategoryInput(user_id=context.user_id, name=name, type=category_type)
        )
        return {"category": self._serialize(category), "created": True}

    async def update_category(self, context: HandoffContext, arguments: dict[str, Any]) -> dict[str, Any]:
        category_id = uuid.UUID(str(arguments["category_id"]))
        category_type = arguments.get("type")
        category = await self._service.update_category(
            context.user_id,
            category_id,
            UpdateCategoryInput(
                name=str(arguments["name"]).strip() if arguments.get("name") else None,
                type=CategoryType(str(category_type).lower()) if category_type else None,
            ),
        )
        return {"category": self._serialize(category)}

    async def delete_category(self, context: HandoffContext, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments.get("confirmed") is not True:
            raise ValueError("explicit confirmation is required to delete a category")
        category_id = uuid.UUID(str(arguments["category_id"]))
        category = next(
            (item for item in await self._service.list_categories(context.user_id) if item.id == category_id), None
        )
        await self._service.delete_category(context.user_id, category_id)
        return {
            "deleted_category_id": str(category_id),
            "category": self._serialize(category) if category is not None else None,
        }

    @staticmethod
    def _serialize(category: Any) -> dict[str, Any]:
        return {"id": str(category.id), "name": category.name, "type": category.type.value}
