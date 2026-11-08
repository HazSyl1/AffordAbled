from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.entities import UserTier
from app.infrastructure.database.repositories.sqlalchemy_user_usage_repository import utc_day_window

CHAT_TURN = 'chat_turn'
AI_TRANSACTION = 'ai_transaction'
MEDIA_REQUEST = 'media_request'


class UsageLimitExceeded(ValueError):
    def __init__(self, metric: str, limit: int, used: int, reset_at: datetime) -> None:
        self.metric = metric
        self.limit = limit
        self.used = used
        self.reset_at = reset_at
        label = {
            CHAT_TURN: 'chat messages', MEDIA_REQUEST: 'voice and image uploads',
        }.get(metric, 'AI-created transactions')
        super().__init__(
            f'You have reached today\'s limit of {limit} {label}. '
            f'Try again after {reset_at.strftime("%Y-%m-%d %H:%M UTC")}.'
        )

    def detail(self) -> dict:
        return {
            'code': f'{self.metric}_daily_limit_reached',
            'message': str(self),
            'metric': self.metric,
            'limit': self.limit,
            'used': self.used,
            'remaining': 0,
            'reset_at': self.reset_at.isoformat(),
        }


@dataclass(frozen=True)
class UsageMetricSnapshot:
    used: int
    limit: int | None

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(0, self.limit - self.used)

    def as_dict(self) -> dict:
        return {
            'used': self.used,
            'limit': self.limit,
            'remaining': self.remaining,
            'unlimited': self.limit is None,
        }


@dataclass
class UserUsageService:
    repository: object
    free_chat_turns: int = 50
    free_ai_transactions: int = 20
    subscribed_chat_turns: int = 250
    subscribed_ai_transactions: int = 100
    free_media_requests: int = 30
    subscribed_media_requests: int = 150

    def limit_for(self, tier: UserTier, metric: str) -> int | None:
        if tier == UserTier.TEST:
            return None
        if metric == CHAT_TURN:
            return self.subscribed_chat_turns if tier == UserTier.SUBSCRIBED else self.free_chat_turns
        if metric == AI_TRANSACTION:
            return self.subscribed_ai_transactions if tier == UserTier.SUBSCRIBED else self.free_ai_transactions
        if metric == MEDIA_REQUEST:
            return self.subscribed_media_requests if tier == UserTier.SUBSCRIBED else self.free_media_requests
        raise ValueError(f'Unknown usage metric: {metric}')

    async def consume(
        self,
        user_id: uuid.UUID,
        metric: str,
        key: str,
        *,
        quantity: int = 1,
        now: datetime | None = None,
        commit: bool = True,
    ) -> UsageMetricSnapshot:
        if quantity < 1:
            raise ValueError('Usage quantity must be positive.')
        now = now or datetime.now(UTC)
        tier = await self.repository.tier_for_user(user_id, lock=True)
        existing = await self.repository.get_by_key(user_id, metric, key)
        limit = self.limit_for(tier, metric)
        used = await self.repository.count(user_id, metric, now=now)
        if existing is not None:
            return UsageMetricSnapshot(used, limit)
        _, reset_at = utc_day_window(now)
        if limit is not None and used + quantity > limit:
            raise UsageLimitExceeded(metric, limit, used, reset_at)
        await self.repository.add(user_id, metric, key, quantity, now=now, commit=commit)
        return UsageMetricSnapshot(used + quantity, limit)

    async def refund(self, user_id: uuid.UUID, metric: str, key: str) -> None:
        """Release a reservation, e.g. when a queued chat turn permanently failed."""
        await self.repository.remove(user_id, metric, key)

    async def ensure_capacity(
        self, user_id: uuid.UUID, metric: str, quantity: int, *, now: datetime | None = None,
        keys: list[str] | None = None,
    ) -> UsageMetricSnapshot:
        now = now or datetime.now(UTC)
        if keys is not None:
            # Keys already recorded (a retried batch) were counted earlier and need no new capacity.
            existing = [await self.repository.get_by_key(user_id, metric, key) for key in keys]
            quantity = sum(1 for item in existing if item is None)
        tier = await self.repository.tier_for_user(user_id, lock=True)
        limit = self.limit_for(tier, metric)
        used = await self.repository.count(user_id, metric, now=now)
        _, reset_at = utc_day_window(now)
        if limit is not None and used + quantity > limit:
            raise UsageLimitExceeded(metric, limit, used, reset_at)
        return UsageMetricSnapshot(used, limit)

    async def summary(self, user_id: uuid.UUID, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        tier = await self.repository.tier_for_user(user_id)
        chat_used = await self.repository.count(user_id, CHAT_TURN, now=now)
        ai_used = await self.repository.count(user_id, AI_TRANSACTION, now=now)
        _, reset_at = utc_day_window(now)
        return {
            'account_tier': tier.value,
            'reset_at': reset_at,
            'chat_turns': UsageMetricSnapshot(chat_used, self.limit_for(tier, CHAT_TURN)).as_dict(),
            'ai_transactions': UsageMetricSnapshot(ai_used, self.limit_for(tier, AI_TRANSACTION)).as_dict(),
            'notification_limits_bypassed': tier == UserTier.TEST,
        }
