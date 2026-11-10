from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.split_notification_service import COOLDOWN_STATUSES, COUNTED_STATUSES
from app.infrastructure.database.models import (
    SplitContactModel,
    SplitModel,
    SplitNotificationModel,
    SplitParticipantModel,
    UserModel,
)


def _as_utc(value: datetime) -> datetime:
    """Normalize database timestamps across PostgreSQL and SQLite."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass
class ReservationResult:
    notification: SplitNotificationModel
    blocked_reason: str | None = None
    next_available_at: datetime | None = None


@dataclass
class BatchReservationResult:
    notifications: list[SplitNotificationModel]
    blocked_reason: str | None = None
    next_available_at: datetime | None = None


class SqlAlchemySplitNotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_context(
        self, user_id: uuid.UUID, split_id: uuid.UUID, participant_id: uuid.UUID,
    ):
        row = (await self.session.execute(
            select(SplitModel, SplitParticipantModel, SplitContactModel, UserModel)
            .join(SplitParticipantModel, SplitParticipantModel.split_id == SplitModel.id)
            .outerjoin(SplitContactModel, SplitContactModel.id == SplitParticipantModel.contact_id)
            .join(UserModel, UserModel.id == SplitModel.user_id)
            .where(
                SplitModel.id == split_id, SplitModel.user_id == user_id,
                SplitModel.deleted_at.is_(None),
                SplitParticipantModel.id == participant_id,
            )
        )).first()
        if row is None:
            return None
        split, participant, contact, user = row
        return SimpleNamespace(split=split, participant=participant, contact=contact, user=user)

    async def get_split_contexts(self, user_id: uuid.UUID, split_id: uuid.UUID):
        rows = (await self.session.execute(
            select(SplitModel, SplitParticipantModel, SplitContactModel, UserModel)
            .join(SplitParticipantModel, SplitParticipantModel.split_id == SplitModel.id)
            .outerjoin(SplitContactModel, SplitContactModel.id == SplitParticipantModel.contact_id)
            .join(UserModel, UserModel.id == SplitModel.user_id)
            .where(
                SplitModel.id == split_id, SplitModel.user_id == user_id,
                SplitModel.deleted_at.is_(None),
            )
            .order_by(SplitParticipantModel.name)
        )).all()
        return [SimpleNamespace(split=split, participant=participant, contact=contact, user=user)
                for split, participant, contact, user in rows]

    async def get_by_id(self, notification_id: uuid.UUID):
        return await self.session.get(SplitNotificationModel, notification_id)

    async def get_contact_with_user(self, user_id: uuid.UUID, contact_id: uuid.UUID):
        row = (await self.session.execute(
            select(SplitContactModel, UserModel)
            .join(UserModel, UserModel.id == SplitContactModel.user_id)
            .where(SplitContactModel.id == contact_id, SplitContactModel.user_id == user_id)
        )).first()
        return None if row is None else SimpleNamespace(contact=row[0], user=row[1])

    async def balance_statement_status(self, user_id: uuid.UUID, recipient_email: str, *, now: datetime,
                                       cooldown: timedelta, max_notifications: int, max_daily: int,
                                       bypass_limits: bool = False) -> dict:
        rows = list((await self.session.scalars(select(SplitNotificationModel).where(
            SplitNotificationModel.sent_by_user_id == user_id,
            SplitNotificationModel.split_id.is_(None), SplitNotificationModel.split_participant_id.is_(None),
            SplitNotificationModel.recipient_email == recipient_email,
            SplitNotificationModel.status.in_(COUNTED_STATUSES),
        ).order_by(SplitNotificationModel.created_at.desc()))).all())
        day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        daily_count = int(await self.session.scalar(select(func.count()).select_from(SplitNotificationModel).where(
            SplitNotificationModel.sent_by_user_id == user_id,
            SplitNotificationModel.status.in_(COUNTED_STATUSES), SplitNotificationModel.created_at >= day_start,
        )) or 0)
        in_progress = any(row.status in {'queued', 'processing'} for row in rows)
        next_at = _as_utc(rows[0].created_at) + cooldown if rows else None
        reason = None
        if in_progress:
            reason = 'request_in_progress'
        elif next_at and next_at > now and not bypass_limits:
            reason = 'cooldown_active'
        elif len(rows) >= max_notifications and not bypass_limits:
            reason = 'person_limit_reached'
            next_at = None
        elif daily_count >= max_daily and not bypass_limits:
            reason = 'daily_limit_reached'
            next_at = day_start + timedelta(days=1)
        else:
            next_at = None
        return {'can_notify': reason is None, 'blocked_reason': reason, 'next_available_at': next_at,
                'notification_count': len(rows), 'max_notifications': max_notifications,
                'request_in_progress': in_progress, 'limits_bypassed': bypass_limits,
                'server_now': now}

    async def reserve_balance_statement(self, *, user_id: uuid.UUID, contact_id: uuid.UUID,
                                        idempotency_key: uuid.UUID, recipient_name: str, recipient_email: str,
                                        amount_paise: int, message_body: str, upi_link: str, provider: str,
                                        settlement_details: str | None = None,
                                        now: datetime, max_per_user_daily: int,
                                        cooldown: timedelta, max_notifications: int,
                                        bypass_limits: bool = False) -> ReservationResult:
        await self.session.scalar(select(UserModel.id).where(UserModel.id == user_id).with_for_update())
        existing = await self.get_by_idempotency(user_id, idempotency_key)
        if existing is not None:
            return ReservationResult(existing, existing.blocked_reason)
        summary = await self.balance_statement_status(
            user_id, recipient_email, now=now, cooldown=cooldown,
            max_notifications=max_notifications, max_daily=max_per_user_daily,
            bypass_limits=bypass_limits,
        )
        blocked_reason = summary['blocked_reason']
        notification = SplitNotificationModel(
            id=uuid.uuid4(), split_id=None, split_participant_id=None, sent_by_user_id=user_id,
            idempotency_key=idempotency_key, channel='email', provider=provider,
            recipient_name=recipient_name, recipient_email=recipient_email, recipient_phone_e164=None,
            email_subject='AffordAbled: your current balance summary', amount_paise=amount_paise,
            currency='INR', message_body=message_body, upi_link=upi_link,
            settlement_details=settlement_details,
            status='rate_limited' if blocked_reason else 'queued', blocked_reason=blocked_reason,
            created_at=now, completed_at=now if blocked_reason else None,
        )
        self.session.add(notification)
        await self.session.commit()
        next_available_at = summary['next_available_at']
        return ReservationResult(notification, blocked_reason, next_available_at)

    async def get_by_idempotency(self, user_id: uuid.UUID, key: uuid.UUID):
        return await self.session.scalar(select(SplitNotificationModel).where(
            SplitNotificationModel.sent_by_user_id == user_id,
            SplitNotificationModel.idempotency_key == key,
        ))

    async def get_campaign(self, user_id: uuid.UUID, split_id: uuid.UUID, key: uuid.UUID):
        rows = await self.session.scalars(select(SplitNotificationModel).where(
            SplitNotificationModel.sent_by_user_id == user_id,
            SplitNotificationModel.split_id == split_id,
            SplitNotificationModel.idempotency_key == key,
        ).order_by(SplitNotificationModel.recipient_name))
        return list(rows.all())

    async def reserve_split_batch(self, *, notifications: list[dict], **values) -> BatchReservationResult:
        user_id = values['user_id']
        split_id = values['split_id']
        key = values['idempotency_key']
        now = values['now']
        cooldown = values['cooldown']
        max_per_split = values['max_per_split']
        max_per_user_daily = values['max_per_user_daily']
        bypass_limits = bool(values.get('bypass_limits'))
        await self.session.scalar(select(UserModel.id).where(UserModel.id == user_id).with_for_update())
        split = await self.session.scalar(select(SplitModel).where(
            SplitModel.id == split_id, SplitModel.user_id == user_id,
            SplitModel.deleted_at.is_(None),
        ).with_for_update())
        if split is None:
            raise LookupError('Split was not found.')
        existing = await self.get_campaign(user_id, split_id, key)
        if existing:
            return BatchReservationResult(existing)
        latest_in_progress = await self.session.scalar(select(SplitNotificationModel).where(
            SplitNotificationModel.split_id == split_id,
            SplitNotificationModel.status.in_({'queued', 'processing'}),
        ).order_by(SplitNotificationModel.created_at.desc()))
        latest_sent = await self.session.scalar(select(SplitNotificationModel).where(
            SplitNotificationModel.split_id == split_id,
            SplitNotificationModel.status.in_(COOLDOWN_STATUSES),
        ).order_by(SplitNotificationModel.created_at.desc()))
        campaign_count = int(await self.session.scalar(select(
            func.count(func.distinct(SplitNotificationModel.idempotency_key)),
        ).where(
            SplitNotificationModel.split_id == split_id,
            SplitNotificationModel.status.in_(COUNTED_STATUSES),
        )) or 0)
        day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        daily_count = int(await self.session.scalar(select(func.count()).select_from(
            SplitNotificationModel,
        ).where(
            SplitNotificationModel.sent_by_user_id == user_id,
            SplitNotificationModel.status.in_(COUNTED_STATUSES),
            SplitNotificationModel.created_at >= day_start,
        )) or 0)
        reason = None
        next_at = None
        if latest_in_progress is not None:
            reason = 'request_in_progress'
        elif not bypass_limits and latest_sent is not None and _as_utc(latest_sent.created_at) + cooldown > now:
            reason = 'cooldown_active'
            next_at = _as_utc(latest_sent.created_at) + cooldown
        elif not bypass_limits and campaign_count >= max_per_split:
            reason = 'split_limit_reached'
        elif not bypass_limits and daily_count + len(notifications) > max_per_user_daily:
            reason = 'daily_limit_reached'
            next_at = day_start + timedelta(days=1)
        rows = [SplitNotificationModel(
            id=uuid.uuid4(), split_id=split_id, split_participant_id=item['participant_id'],
            sent_by_user_id=user_id, idempotency_key=key,
            channel=values['channel'], provider=values['provider'], recipient_name=item['recipient_name'],
            recipient_phone_e164=item.get('recipient_phone_e164'), recipient_email=item.get('recipient_email'),
            email_subject=item.get('email_subject'), amount_paise=item['amount_paise'], currency='INR',
            message_body=item['message_body'], upi_link=item['upi_link'],
            status='rate_limited' if reason else 'queued', blocked_reason=reason,
            created_at=now, completed_at=now if reason else None,
        ) for item in notifications]
        self.session.add_all(rows)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get_campaign(user_id, split_id, key)
            if not existing:
                raise
            return BatchReservationResult(existing)
        return BatchReservationResult(rows, reason, next_at)

    async def reserve(self, **values) -> ReservationResult:
        user_id = values['user_id']
        participant_id = values['participant_id']
        now = values['now']
        cooldown = values.pop('cooldown')
        max_per_participant = values.pop('max_per_participant')
        max_per_user_daily = values.pop('max_per_user_daily')
        bypass_limits = bool(values.pop('bypass_limits', False))
        await self.session.scalar(select(UserModel.id).where(UserModel.id == user_id).with_for_update())
        participant = await self.session.scalar(
            select(SplitParticipantModel).where(SplitParticipantModel.id == participant_id).with_for_update()
        )
        if participant is None:
            raise LookupError('Split participant was not found.')
        existing = await self.get_by_idempotency(user_id, values['idempotency_key'])
        if existing is not None:
            return ReservationResult(existing)
        latest_in_progress = await self.session.scalar(
            select(SplitNotificationModel).where(
                SplitNotificationModel.split_participant_id == participant_id,
                SplitNotificationModel.status.in_({'queued', 'processing'}),
            ).order_by(SplitNotificationModel.created_at.desc())
        )
        latest_sent = await self.session.scalar(
            select(SplitNotificationModel).where(
                SplitNotificationModel.split_participant_id == participant_id,
                SplitNotificationModel.status.in_(COOLDOWN_STATUSES),
            ).order_by(SplitNotificationModel.created_at.desc())
        )
        participant_count = int(await self.session.scalar(
            select(func.count()).select_from(SplitNotificationModel).where(
                SplitNotificationModel.split_participant_id == participant_id,
                SplitNotificationModel.status.in_(COUNTED_STATUSES),
            )
        ) or 0)
        day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        daily_count = int(await self.session.scalar(select(func.count()).select_from(SplitNotificationModel).where(
            SplitNotificationModel.sent_by_user_id == user_id,
            SplitNotificationModel.status.in_(COUNTED_STATUSES),
            SplitNotificationModel.created_at >= day_start,
        )) or 0)
        reason = None
        next_at = None
        if latest_in_progress is not None:
            reason = 'request_in_progress'
        elif not bypass_limits and latest_sent is not None and _as_utc(latest_sent.created_at) + cooldown > now:
            reason = 'cooldown_active'
            next_at = _as_utc(latest_sent.created_at) + cooldown
        elif not bypass_limits and participant_count >= max_per_participant:
            reason = 'participant_limit_reached'
        elif not bypass_limits and daily_count >= max_per_user_daily:
            reason = 'daily_limit_reached'
            next_at = day_start + timedelta(days=1)
        notification = SplitNotificationModel(
            id=uuid.uuid4(), split_id=values['split_id'], split_participant_id=participant_id,
            sent_by_user_id=user_id, idempotency_key=values['idempotency_key'],
            channel=values.get('channel', 'sms'), provider=values['provider'], recipient_name=values['recipient_name'],
            recipient_phone_e164=values['recipient_phone_e164'], amount_paise=values['amount_paise'],
            recipient_email=values.get('recipient_email'), email_subject=values.get('email_subject'),
            currency='INR', message_body=values['message_body'], upi_link=values['upi_link'],
            status='rate_limited' if reason else 'queued', blocked_reason=reason,
            created_at=now, completed_at=now if reason else None,
        )
        self.session.add(notification)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get_by_idempotency(user_id, values['idempotency_key'])
            if existing is None:
                raise
            return ReservationResult(existing)
        return ReservationResult(notification, reason, next_at)

    async def history(self, user_id: uuid.UUID, participant_id: uuid.UUID, *, limit: int):
        rows = await self.session.scalars(select(SplitNotificationModel).where(
            SplitNotificationModel.sent_by_user_id == user_id,
            SplitNotificationModel.split_participant_id == participant_id,
        ).order_by(SplitNotificationModel.created_at.desc()).limit(limit))
        return list(rows.all())

    async def history_split(self, user_id: uuid.UUID, split_id: uuid.UUID, *, limit: int):
        rows = await self.session.scalars(select(SplitNotificationModel).where(
            SplitNotificationModel.sent_by_user_id == user_id,
            SplitNotificationModel.split_id == split_id,
        ).order_by(SplitNotificationModel.created_at.desc()).limit(limit))
        return list(rows.all())

    async def summary_split(
        self, user_id: uuid.UUID, split_id: uuid.UUID, *, now: datetime,
        cooldown: timedelta, max_per_split: int, max_per_user_daily: int,
        bypass_limits: bool = False,
    ) -> dict:
        history = await self.history_split(user_id, split_id, limit=200)
        counted_campaigns = {
            item.idempotency_key for item in history if item.status in COUNTED_STATUSES
        }
        latest_sent = next((item for item in history if item.status in COOLDOWN_STATUSES), None)
        in_progress = any(item.status in {'queued', 'processing'} for item in history)
        day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        daily_count = int(await self.session.scalar(select(func.count()).select_from(
            SplitNotificationModel,
        ).where(
            SplitNotificationModel.sent_by_user_id == user_id,
            SplitNotificationModel.status.in_(COUNTED_STATUSES),
            SplitNotificationModel.created_at >= day_start,
        )) or 0)
        next_at = _as_utc(latest_sent.created_at) + cooldown if latest_sent else None
        blocked = None
        if in_progress:
            blocked = 'request_in_progress'
        elif not bypass_limits and next_at and next_at > now:
            blocked = 'cooldown_active'
        elif not bypass_limits and len(counted_campaigns) >= max_per_split:
            blocked = 'split_limit_reached'
        elif not bypass_limits and daily_count >= max_per_user_daily:
            blocked = 'daily_limit_reached'
        return {
            'notification_count': len(counted_campaigns), 'max_notifications': max_per_split,
            'last_sent_at': latest_sent.created_at if latest_sent else None,
            'next_available_at': next_at if not bypass_limits and next_at and next_at > now else None,
            'cooldown_remaining_seconds': (
                max(0, int((next_at - now).total_seconds())) if not bypass_limits and next_at else 0
            ),
            'request_in_progress': in_progress, 'blocked_reason': blocked,
            'limits_bypassed': bypass_limits,
        }

    async def summary(
        self, user_id: uuid.UUID, participant_id: uuid.UUID, *, now: datetime,
        cooldown: timedelta, max_per_participant: int, max_per_user_daily: int,
        bypass_limits: bool = False,
    ) -> dict:
        history = await self.history(user_id, participant_id, limit=100)
        counted = [item for item in history if item.status in COUNTED_STATUSES]
        latest_sent = next((item for item in history if item.status in COOLDOWN_STATUSES), None)
        in_progress = any(item.status in {'queued', 'processing'} for item in history)
        day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        daily_count = int(await self.session.scalar(select(func.count()).select_from(SplitNotificationModel).where(
            SplitNotificationModel.sent_by_user_id == user_id,
            SplitNotificationModel.status.in_(COUNTED_STATUSES),
            SplitNotificationModel.created_at >= day_start,
        )) or 0)
        next_at = _as_utc(latest_sent.created_at) + cooldown if latest_sent else None
        blocked = None
        if in_progress:
            blocked = 'request_in_progress'
        elif not bypass_limits and next_at and next_at > now:
            blocked = 'cooldown_active'
        elif not bypass_limits and len(counted) >= max_per_participant:
            blocked = 'participant_limit_reached'
        elif not bypass_limits and daily_count >= max_per_user_daily:
            blocked = 'daily_limit_reached'
        return {
            'notification_count': len(counted), 'max_notifications': max_per_participant,
            'last_sent_at': latest_sent.created_at if latest_sent else None,
            'next_available_at': next_at if not bypass_limits and next_at and next_at > now else None,
            'cooldown_remaining_seconds': (
                max(0, int((next_at - now).total_seconds())) if not bypass_limits and next_at else 0
            ),
            'request_in_progress': in_progress, 'blocked_reason': blocked,
            'limits_bypassed': bypass_limits,
        }

    async def claim_queued(
        self, *, batch_size: int, stale_after_seconds: int, channel: str | None = None,
    ) -> list[SplitNotificationModel]:
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=stale_after_seconds)
        stale = await self.session.scalars(select(SplitNotificationModel).where(
            SplitNotificationModel.status == 'processing', SplitNotificationModel.claimed_at < stale_before,
        ).where(*( [SplitNotificationModel.channel == channel] if channel else [] )).with_for_update(skip_locked=True))
        for item in stale.all():
            item.status = 'uncertain'
            item.provider_error_code = 'worker_interrupted'
            item.provider_error_message = 'The worker stopped after dispatch began; delivery status is uncertain.'
            item.completed_at = now
        rows = await self.session.scalars(select(SplitNotificationModel).where(
            SplitNotificationModel.status == 'queued',
            *( [SplitNotificationModel.channel == channel] if channel else [] ),
        ).order_by(SplitNotificationModel.created_at).limit(batch_size).with_for_update(skip_locked=True))
        claimed = list(rows.all())
        for item in claimed:
            item.status = 'processing'
            item.claimed_at = now
            item.attempt_count += 1
        await self.session.commit()
        return claimed

    async def complete(
        self, notification_id: uuid.UUID, *, status: str, message_id: str | None = None,
        error_code: str | None = None, error_message: str | None = None,
    ) -> None:
        item = await self.session.get(SplitNotificationModel, notification_id)
        if item is None:
            return
        item.status = status
        item.provider_message_id = message_id
        item.provider_error_code = error_code
        item.provider_error_message = error_message[:500] if error_message else None
        item.completed_at = datetime.now(UTC)
        await self.session.commit()
