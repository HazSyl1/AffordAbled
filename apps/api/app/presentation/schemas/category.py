from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from app.domain.entities import Category, CategoryType


class CreateCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: CategoryType
    icon: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=32)


class UpdateCategoryRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: CategoryType | None = None
    icon: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=32)


class CategoryResponse(BaseModel):
    id: str
    name: str
    type: CategoryType
    icon: str | None
    color: str | None
    created_at: datetime

    @classmethod
    def from_entity(cls, category: Category) -> Self:
        return cls(
            id=str(category.id),
            name=category.name,
            type=category.type,
            icon=category.icon,
            color=category.color,
            created_at=category.created_at,
        )
