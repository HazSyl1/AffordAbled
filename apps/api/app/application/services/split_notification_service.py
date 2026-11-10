from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qsl, urlencode, urlsplit

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


@dataclass(frozen=True)
class SplitNotificationQueueResult:
    notifications: list
    skipped_recipients: list[dict]


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


def build_email_subject(creator_name: str, amount_paise: int) -> str:
    amount = Decimal(amount_paise) / Decimal(100)
    return f'AffordAbled: {creator_name} requested ₹{amount:,.2f} from you'


def build_email_message(
    contact_name: str, creator_name: str, amount_paise: int, note: str, upi_id: str, upi_link: str,
) -> str:
    amount = Decimal(amount_paise) / Decimal(100)
    short_note = ' '.join(note.split())[:80]
    return (
        f'Hi {contact_name},\n\n'
        f'{creator_name} sent you a payment request through AffordAbled.\n\n'
        f'Amount: ₹{amount:,.2f}\n'
        f'For: {short_note}\n'
        f'Requested by: {creator_name}\n'
        f'Pay to UPI ID: {upi_id}\n\n'
        f'Pay with UPI: {upi_link}\n\n'
        'Before paying, verify the payee UPI ID and amount in your UPI app.\n\n'
        'This is an automated message from AffordAbled. Please do not reply to this email.'
    )


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
    max_per_split: int
    max_per_user_daily: int
    channel: str = 'sms'

    async def queue_balance_statement(
        self, user_id: uuid.UUID, contact_id: uuid.UUID, balance: dict, idempotency_key: uuid.UUID,
        *, now: datetime | None = None,
    ):
        if not self.enabled or self.channel != 'email':
            raise SplitNotificationError(
                'notification_unavailable', 'Email reminders are not configured.', status_code=503,
            )
        context = await self.repository.get_contact_with_user(user_id, contact_id)
        if context is None:
            raise SplitNotificationError('contact_not_found', 'Saved person was not found.', status_code=404)
        if not context.contact.email:
            raise SplitNotificationError(
                'email_required', 'Add this person\'s email before sending a balance summary.', status_code=422,
            )
        owed = int(balance['owed_to_you_paise'])
        you_owe = int(balance['you_owe_paise'])
        net = owed - you_owe
        settlement = 'You are settled.' if net == 0 else (
            f'{context.contact.name} owes you Rs.{Decimal(net) / Decimal(100):.2f}.' if net > 0 else
            f'You owe {context.contact.name} Rs.{Decimal(-net) / Decimal(100):.2f}.'
        )
        message = (
            f'Hi {context.contact.name},\n\n{context.user.name} shared your current AffordAbled balance summary.\n\n'
            f'You owe {context.user.name}: Rs.{Decimal(owed) / Decimal(100):.2f}\n'
            f'{context.user.name} owes you: Rs.{Decimal(you_owe) / Decimal(100):.2f}\n'
            f'Net settlement: {settlement}\n\n'
            'This summary includes only currently outstanding split records; paid records are not included.\n\n'
            'This is an automated message from AffordAbled. Please do not reply to this email.'
        )
        now = now or datetime.now(UTC)
        result = await self.repository.reserve_balance_statement(
            user_id=user_id, contact_id=contact_id, idempotency_key=idempotency_key,
            recipient_name=context.contact.name, recipient_email=context.contact.email,
            amount_paise=abs(net), message_body=message,
            upi_link='', provider=self.provider_name, now=now, max_per_user_daily=self.max_per_user_daily,
        )
        if result.blocked_reason:
            raise SplitNotificationError(
                'daily_limit_reached', 'Your daily notification limit has been reached.', status_code=429,
            )
        return result.notification

    async def queue_split(
        self, user_id: uuid.UUID, split_id: uuid.UUID, idempotency_key: uuid.UUID,
        participant_ids: list[uuid.UUID] | None = None,
        *, now: datetime | None = None,
    ):
        if not self.enabled:
            raise SplitNotificationError(
                'notification_unavailable', 'Payment reminders are not configured.', status_code=503,
            )
        now = now or datetime.now(UTC)
        existing = await self.repository.get_campaign(user_id, split_id, idempotency_key)
        if existing:
            if existing[0].status == 'rate_limited':
                raise SplitNotificationError(
                    existing[0].blocked_reason or 'rate_limited', 'This reminder request was rate limited.',
                    status_code=429,
                )
            return SplitNotificationQueueResult(existing, [])
        contexts = await self.repository.get_split_contexts(user_id, split_id)
        if not contexts:
            raise SplitNotificationError('split_not_found', 'Split was not found.', status_code=404)
        self.validate_split_context(contexts[0])
        unpaid = [item for item in contexts if item.participant.share_paise > item.participant.settled_paise]
        if not unpaid:
            raise SplitNotificationError('already_settled', 'This split is already settled.', status_code=409)
        requested_ids = set(participant_ids or [item.participant.id for item in unpaid])
        known_ids = {item.participant.id for item in contexts}
        if requested_ids - known_ids:
            raise SplitNotificationError(
                'participant_not_found', 'A selected participant does not belong to this split.', status_code=404,
            )
        selected = [item for item in unpaid if item.participant.id in requested_ids]
        if not selected:
            raise SplitNotificationError(
                'already_settled', 'The selected people have already repaid their shares.', status_code=409,
            )
        eligible = [item for item in selected if self._recipient(item)]
        skipped = [
            {
                'participant_id': item.participant.id,
                'contact_id': item.contact.id if item.contact else None,
                'name': item.participant.name,
                'amount_paise': item.participant.share_paise - item.participant.settled_paise,
                'reason': 'email_required' if self.channel == 'email' else 'phone_required',
            }
            for item in selected if not self._recipient(item)
        ]
        if not eligible:
            raise SplitNotificationError(
                'participant_emails_required' if self.channel == 'email' else 'participant_phones_required',
                'Add contact details for at least one selected person.', status_code=422,
            )
        notifications = []
        for context in eligible:
            amount = context.participant.share_paise - context.participant.settled_paise
            link = build_upi_link(context.user.upi_id, context.user.name, amount, context.split.title)
            message = (
                build_email_message(
                    context.participant.name, context.user.name, amount, context.split.title,
                    context.user.upi_id, link,
                )
                if self.channel == 'email' else
                build_sms_message(context.participant.name, context.user.name, amount, context.split.title, link)
            )
            notifications.append({
                'participant_id': context.participant.id,
                'recipient_name': context.participant.name,
                'recipient_phone_e164': context.contact.phone_e164 if self.channel == 'sms' else None,
                'recipient_email': context.contact.email if self.channel == 'email' else None,
                'email_subject': (
                    build_email_subject(context.user.name, amount) if self.channel == 'email' else None
                ),
                'amount_paise': amount, 'message_body': message, 'upi_link': link,
            })
        result = await self.repository.reserve_split_batch(
            user_id=user_id, split_id=split_id, idempotency_key=idempotency_key,
            notifications=notifications, channel=self.channel, provider=self.provider_name,
            now=now, cooldown=timedelta(hours=self.cooldown_hours),
            max_per_split=self.max_per_split, max_per_user_daily=self.max_per_user_daily,
            bypass_limits=contexts[0].user.account_tier == 'test',
        )
        if result.blocked_reason:
            next_at = result.next_available_at
            retry = max(0, int((next_at - now).total_seconds())) if next_at else None
            messages = {
                'request_in_progress': 'A reminder for this split is already being processed.',
                'cooldown_active': 'Wait before sending another reminder for this split.',
                'split_limit_reached': 'This split has reached its reminder limit.',
                'daily_limit_reached': 'Your daily notification limit has been reached.',
            }
            raise SplitNotificationError(
                result.blocked_reason, messages[result.blocked_reason],
                status_code=409 if result.blocked_reason == 'request_in_progress' else 429,
                retry_after_seconds=retry, next_available_at=next_at,
            )
        return SplitNotificationQueueResult(result.notifications, skipped)

    async def payment_page_data(self, notification_id: uuid.UUID) -> dict | None:
        """Details for the public pay page opened from a reminder email; None when it should not be shown."""
        notification = await self.repository.get_by_id(notification_id)
        if notification is None or notification.status in {'cancelled', 'failed', 'rate_limited'}:
            return None
        parsed = urlsplit(notification.upi_link)
        if parsed.scheme != 'upi' or parsed.netloc != 'pay':
            return None
        params = dict(parse_qsl(parsed.query))
        return {
            'upi_link': notification.upi_link,
            'amount_paise': notification.amount_paise,
            'payee_upi_id': params.get('pa', ''),
            'payee_name': params.get('pn', ''),
            'recipient_name': notification.recipient_name,
        }

    async def status_split(
        self, user_id: uuid.UUID, split_id: uuid.UUID, *, now: datetime | None = None,
    ) -> dict:
        now = now or datetime.now(UTC)
        contexts = await self.repository.get_split_contexts(user_id, split_id)
        if not contexts:
            raise SplitNotificationError('split_not_found', 'Split was not found.', status_code=404)
        history_rows = await self.repository.history_split(user_id, split_id, limit=100)
        summary = await self.repository.summary_split(
            user_id, split_id, now=now, cooldown=timedelta(hours=self.cooldown_hours),
            max_per_split=self.max_per_split, max_per_user_daily=self.max_per_user_daily,
            bypass_limits=contexts[0].user.account_tier == 'test',
        )
        blocked_reason = None
        try:
            self.validate_split_context(contexts[0])
        except SplitNotificationError as error:
            blocked_reason = error.code
        unpaid = [item for item in contexts if item.participant.share_paise > item.participant.settled_paise]
        recipients = []
        missing_recipients = []
        for context in unpaid:
            recipient = self._recipient(context)
            item = {
                'participant_id': context.participant.id,
                'contact_id': context.contact.id if context.contact else None,
                'name': context.participant.name,
                'amount_paise': context.participant.share_paise - context.participant.settled_paise,
                'recipient': mask_email(recipient) if self.channel == 'email' and recipient else (
                    mask_phone(recipient) if recipient else None
                ),
            }
            recipients.append(item)
            if not recipient:
                missing_recipients.append(item)
        if not unpaid:
            blocked_reason = 'already_settled'
        blocked_reason = summary.get('blocked_reason') or blocked_reason
        history = [{
            'id': item.id, 'status': item.status, 'channel': item.channel,
            'recipient_name': item.recipient_name, 'blocked_reason': item.blocked_reason,
            'provider_error_message': item.provider_error_message,
            'created_at': item.created_at, 'completed_at': item.completed_at,
        } for item in history_rows]
        return {
            **summary, 'server_now': now, 'channel': self.channel,
            'can_notify': self.enabled and blocked_reason is None,
            'blocked_reason': blocked_reason if self.enabled else 'notification_unavailable',
            'recipients': recipients, 'missing_recipients': missing_recipients, 'history': history,
        }

    def _recipient(self, context) -> str | None:
        if context.contact is None:
            return None
        return context.contact.email if self.channel == 'email' else context.contact.phone_e164

    @staticmethod
    def validate_split_context(context) -> None:
        if context.split.settlement_breakdown is not None:
            raise SplitNotificationError(
                'notification_not_supported', 'Reminders are not available for settlement plans.', status_code=409,
            )
        if context.split.transaction_id is None and context.split.direction != 'to_you':
            raise SplitNotificationError(
                'notification_not_supported', 'This entry records money that you owe.', status_code=409,
            )
        if not context.user.upi_id:
            raise SplitNotificationError('upi_id_required', 'Add your UPI ID in Profile first.', status_code=422)

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
            context.participant.name, context.user.name, amount_paise, context.split.title,
            context.user.upi_id, upi_link,
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
                build_email_subject(context.user.name, amount_paise) if self.channel == 'email' else None
            ),
            amount_paise=amount_paise,
            message_body=message,
            upi_link=upi_link,
            now=now,
            cooldown=timedelta(hours=self.cooldown_hours),
            max_per_participant=self.max_per_split,
            max_per_user_daily=self.max_per_user_daily,
            bypass_limits=context.user.account_tier == 'test',
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
            max_per_participant=self.max_per_split,
            max_per_user_daily=self.max_per_user_daily,
            bypass_limits=context.user.account_tier == 'test',
        )
        blocked_reason = None
        preview = None
        masked = None
        try:
            self.validate_context(context, channel=self.channel)
            amount = context.participant.share_paise - context.participant.settled_paise
            link = build_upi_link(context.user.upi_id, context.user.name, amount, context.split.title)
            preview = (
                build_email_message(
                    context.participant.name, context.user.name, amount, context.split.title,
                    context.user.upi_id, link,
                )
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
