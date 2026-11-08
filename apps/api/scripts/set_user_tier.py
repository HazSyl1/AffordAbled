from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.domain.entities import UserTier  # noqa: E402
from app.infrastructure.database.models import UserModel  # noqa: E402
from app.infrastructure.database.session import SessionLocal  # noqa: E402


async def set_user_tier(user_id: uuid.UUID, tier: UserTier) -> int:
    async with SessionLocal() as session:
        user = await session.scalar(select(UserModel).where(UserModel.id == user_id).with_for_update())
        if user is None:
            print(f'User {user_id} was not found.', file=sys.stderr)
            return 1
        previous = user.account_tier
        user.account_tier = tier.value
        await session.commit()
        print(f'Updated {user_id}: {previous} -> {tier.value}')
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Change an AffordAbled user account tier.')
    parser.add_argument('--user-id', required=True, type=uuid.UUID)
    parser.add_argument('--tier', required=True, choices=[item.value for item in UserTier])
    args = parser.parse_args()
    return asyncio.run(set_user_tier(args.user_id, UserTier(args.tier)))


if __name__ == '__main__':
    raise SystemExit(main())
