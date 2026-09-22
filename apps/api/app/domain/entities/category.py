from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class CategoryType(str, Enum):
    EXPENSE = 'expense'
    INCOME = 'income'


@dataclass
class Category:
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    icon: str | None
    color: str | None
    type: CategoryType
    created_at: datetime
