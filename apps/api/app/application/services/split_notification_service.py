from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

COUNTED_STATUSES = {'queued', 'processing', 'sent', 'uncertain'}
COOLDOWN_STATUSES = {'sent', 'uncertain'}


class SplitNotificationError(Exception):
    def __init__(
        self, code: str, message: str, *, status_code: int,
        retry_after_seconds: int | None = None, next_available_at: datetime | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.next_available_at = next_available_at


def build_upi_link(upi_id: str, payee_name: str, amount_paise: int, note: str) -> str:
    amount = Decimal(amount_paise) / Decimal(100)
    params = {
        'pa': upi_id,
        'pn': payee_name,
        'am': f'{amount:.2f}',
        'cu': 'INR',
        'tn': ' '.join(note.split())[:50],
    }
    return f"upi://pay?{urlencode(params)}"


def build_sms_message(contact_name: str, creator_name: str, amount_paise: int, note: str, upi_link: str) -> str:
    amount = Decimal(amount_paise) / Decimal(100)
    short_note = ' '.join(note.split())[:50]
    return f'Hi {contact_name}, {creator_name} requested Rs.{amount:.2f} for "{short_note}". Pay via UPI: {upi_link}'


def build_email_subject(creator_name: str, note: str) -> str:
    return f'Payment request from {creator_name}: {" ".join(note.split())[:80]}'


def build_email_message(contact_name: str, creator_name: str, amount_paise: int, note: str, upi_link: str) -> str:
    return build_sms_message(contact_name, creator_name, amount_paise, note, upi_link)


def mask_phone(phone: str) -> str:
    if len(phone) <= 6:
        return '*' * len(phone)
    return f'{phone[:3]}{"*" * (len(phone) - 7)}{phone[-4:]}'


def mask_email(email: str) -> str:
    local, _, domain = email.partition('@')
    return f'{local[:1]}***@{domain}' if local and domain else '***'


@dataclass
class SplitNotificationService:
    repository: object
    enabled: bool
    provider_name: str
    cooldown_hours: int
    max_per_participant: int
    max_per_user_daily: int
    channel: str = 'sms'

    async def queue(
        self, user_id: uuid.UUID, split_id: uuid.UUID, participant_id: uuid.UUID,
        idempotency_key: uuid.UUID, *, now: datetime | None = None,
    ):
        if not self.enabled:
            raise SplitNotificationError(
                'notification_unavailable', 'Payment reminders are not configured.', status_code=503,
            )
        now = now or datetime.now(UTC)
        existing = await self.repository.get_by_idempotency(user_id, idempotency_key)
        if existing is not None:
            if existing.status == 'rate_limited':
                raise SplitNotificationError(
                    existing.blocked_reason or 'rate_limited', 'This reminder request was rate limited.',
                    status_code=429,
                )
            return existing
        context = await self.repository.get_context(user_id, split_id, participant_id)
        self.validate_context(context, channel=self.channel)
        amount_paise = context.participant.share_paise - context.participant.settled_paise
        upi_link = build_upi_link(context.user.upi_id, context.user.name, amount_paise, context.split.title)
        message = build_email_message(
            context.participant.name, context.user.name, amount_paise, context.split.title, upi_link,
        ) if self.channel == 'email' else build_sms_message(
            context.participant.name, context.user.name, amount_paise, context.split.title, upi_link,
        )
        result = await self.repository.reserve(
            user_id=user_id,
            split_id=split_id,
            participant_id=participant_id,
            idempotency_key=idempotency_key,
            channel=self.channel, provider=self.provider_name,
            recipient_name=context.participant.name,
            recipient_phone_e164=context.contact.phone_e164 if self.channel == 'sms' else None,
            recipient_email=context.contact.email if self.channel == 'email' else None,
            email_subject=(
                build_email_subject(context.user.name, context.split.title) if self.channel == 'email' else None
            ),
            amount_paise=amount_paise,
            message_body=message,
            upi_link=upi_link,
            now=now,
            cooldown=timedelta(hours=self.cooldown_hours),
            max_per_participant=self.max_per_participant,
            max_per_user_daily=self.max_per_user_daily,
        )
        if result.blocked_reason:
            next_at = result.next_available_at
            retry = max(0, int((next_at - now).total_seconds())) if next_at else None
            messages = {
                'request_in_progress': 'A reminder for this person is already being processed.',
                'cooldown_active': 'Wait before sending another reminder.',
                'participant_limit_reached': 'This person has already received the maximum number of reminders.',
                'daily_limit_reached': 'Your daily notification limit has been reached.',
            }
            raise SplitNotificationError(
                result.blocked_reason, messages[result.blocked_reason],
                status_code=409 if result.blocked_reason == 'request_in_progress' else 429,
                retry_after_seconds=retry, next_available_at=next_at,
            )
        return result.notification

    async def status(
        self, user_id: uuid.UUID, split_id: uuid.UUID, participant_id: uuid.UUID,
        *, now: datetime | None = None,
    ) -> dict:
        now = now or datetime.now(UTC)
        context = await self.repository.get_context(user_id, split_id, participant_id)
        if context is None:
            raise SplitNotificationError(
                'participant_not_found', 'Split participant was not found.', status_code=404,
            )
        history_rows = await self.repository.history(user_id, participant_id, limit=20)
        history = [
            {
                'id': item.id, 'status': item.status, 'channel': item.channel,
                'blocked_reason': item.blocked_reason,
                'provider_error_message': item.provider_error_message,
                'created_at': item.created_at, 'completed_at': item.completed_at,
            }
            for item in history_rows
        ]
        summary = await self.repository.summary(
            user_id, participant_id, now=now, cooldown=timedelta(hours=self.cooldown_hours),
            max_per_participant=self.max_per_participant,
            max_per_user_daily=self.max_per_user_daily,
        )
        blocked_reason = None
        preview = None
        masked = None
        try:
            self.validate_context(context, channel=self.channel)
            amount = context.participant.share_paise - context.participant.settled_paise
            link = build_upi_link(context.user.upi_id, context.user.name, amount, context.split.title)
            preview = (
                build_email_message(context.participant.name, context.user.name, amount, context.split.title, link)
                if self.channel == 'email' else
                build_sms_message(context.participant.name, context.user.name, amount, context.split.title, link)
            )
            masked = mask_phone(context.contact.phone_e164) if self.channel == 'sms' else None
        except SplitNotificationError as error:
            blocked_reason = error.code
        blocked_reason = summary.get('blocked_reason') or blocked_reason
        return {
            **summary,
            'server_now': now,
            'can_notify': self.enabled and blocked_reason is None,
            'blocked_reason': blocked_reason if self.enabled else 'notification_unavailable',
            'channel': self.channel,
            'message_preview': preview,
            'recipient_phone_masked': masked,
            'recipient_email_masked': (
                mask_email(context.contact.email)
                if self.channel == 'email' and context.contact and context.contact.email else None
            ),
            'history': history,
        }

    @staticmethod
    def validate_context(context, *, channel: str = 'sms') -> None:
        if context is None:
            raise SplitNotificationError('participant_not_found', 'Split participant was not found.', status_code=404)
        if context.split.settlement_breakdown is not None:
            raise SplitNotificationError(
                'notification_not_supported', 'Reminders are not available for settlement plans.', status_code=409,
            )
        if context.split.transaction_id is None and context.split.direction != 'to_you':
            raise SplitNotificationError(
                'notification_not_supported', 'This entry records money that you owe.', status_code=409,
            )
        if context.participant.share_paise <= context.participant.settled_paise:
            raise SplitNotificationError(
                'already_settled', 'This person has already repaid their share.', status_code=409,
            )
        if not context.user.upi_id:
            raise SplitNotificationError('upi_id_required', 'Add your UPI ID in Profile first.', status_code=422)
        if context.contact is None:
            raise SplitNotificationError(
                'contact_required', 'Add contact details for this person first.', status_code=422,
            )
        if channel == 'email' and not context.contact.email:
            raise SplitNotificationError(
                'email_required', 'Add an email address for this person first.', status_code=422,
            )
        if channel != 'email' and not context.contact.phone_e164:
            raise SplitNotificationError('phone_required', 'Add a phone number for this person first.', status_code=422)
