from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class AccountType(str, Enum):
    CASH = "cash"
    BANK = "bank"
    CARD = "card"
    WALLET = "wallet"


@dataclass
class Account:
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    type: AccountType
    balance_paise: int
    currency: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
