from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.application.dto import CreateCategoryInput, UpdateCategoryInput
from app.application.services.category_service import CategoryService
from app.core.dependencies import get_category_service, get_current_user
from app.domain.entities import User
from app.presentation.schemas.category import CategoryResponse, CreateCategoryRequest, UpdateCategoryRequest

router = APIRouter(prefix='/categories', tags=['categories'])


@router.post('', response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CreateCategoryRequest,
    current_user: User = Depends(get_current_user),
    category_service: CategoryService = Depends(get_category_service),
) -> CategoryResponse:
    category = await category_service.create_category(
        CreateCategoryInput(
            user_id=current_user.id,
            name=payload.name,
            type=payload.type,
            icon=payload.icon,
            color=payload.color,
        )
    )
    return CategoryResponse.from_entity(category)


@router.get('', response_model=list[CategoryResponse])
async def list_categories(
    current_user: User = Depends(get_current_user),
    category_service: CategoryService = Depends(get_category_service),
) -> list[CategoryResponse]:
    categories = await category_service.list_categories(current_user.id)
    return [CategoryResponse.from_entity(category) for category in categories]


@router.patch('/{category_id}', response_model=CategoryResponse)
async def update_category(
    category_id: uuid.UUID,
    payload: UpdateCategoryRequest,
    current_user: User = Depends(get_current_user),
    category_service: CategoryService = Depends(get_category_service),
) -> CategoryResponse:
    category = await category_service.update_category(
        current_user.id,
        category_id,
        UpdateCategoryInput(name=payload.name, type=payload.type, icon=payload.icon, color=payload.color),
    )
    return CategoryResponse.from_entity(category)


@router.delete('/{category_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    category_service: CategoryService = Depends(get_category_service),
) -> None:
    await category_service.delete_category(current_user.id, category_id)
