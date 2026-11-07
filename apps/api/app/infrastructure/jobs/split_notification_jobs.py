from __future__ import annotations

import asyncio
import logging

from app.application.services.split_notification_service import (
    SplitNotificationError,
    SplitNotificationService,
    build_email_message,
    build_sms_message,
    build_upi_link,
)
from app.infrastructure.database.repositories.sqlalchemy_split_notification_repository import (
    SqlAlchemySplitNotificationRepository,
)
from app.infrastructure.database.session import SessionLocal
from app.infrastructure.sms_scheduler_signal import clear_sms_scheduler_wakeup, install_sms_scheduler_wakeup

logger = logging.getLogger(__name__)


async def run_split_notification_batch_once(
    provider, *, batch_size: int, stale_after_seconds: int, channel: str = 'sms', session_factory=SessionLocal,
) -> int:
    async with session_factory() as session:
        repository = SqlAlchemySplitNotificationRepository(session)
        claimed = await repository.claim_queued(
            batch_size=max(1, batch_size), stale_after_seconds=max(30, stale_after_seconds), channel=channel,
        )
        for notification in claimed:
            if notification.split_id is None or notification.split_participant_id is None:
                await repository.complete(
                    notification.id, status='cancelled', error_code='split_removed',
                    error_message='The split or participant was removed before the reminder was sent.',
                )
                continue
            context = await repository.get_context(
                notification.sent_by_user_id, notification.split_id, notification.split_participant_id,
            )
            try:
                SplitNotificationService.validate_context(context, channel=channel)
            except SplitNotificationError as error:
                await repository.complete(
                    notification.id, status='cancelled', error_code=error.code, error_message=error.message,
                )
                continue
            current_amount = context.participant.share_paise - context.participant.settled_paise
            current_link = build_upi_link(
                context.user.upi_id, context.user.name, current_amount, context.split.title,
            )
            current_message = build_email_message(
                context.participant.name, context.user.name, current_amount, context.split.title, current_link,
            ) if channel == 'email' else build_sms_message(
                context.participant.name, context.user.name, current_amount, context.split.title, current_link,
            )
            recipient_changed = (
                notification.recipient_email != context.contact.email
                if channel == 'email' else notification.recipient_phone_e164 != context.contact.phone_e164
            )
            if (
                recipient_changed
                or notification.amount_paise != current_amount
                or notification.upi_link != current_link
                or notification.message_body != current_message
            ):
                await repository.complete(
                    notification.id, status='cancelled', error_code='reminder_details_changed',
                    error_message='The payment request changed after confirmation. Confirm a new reminder.',
                )
                continue
            try:
                send_kwargs = (
                    {
                        'recipient_email': notification.recipient_email,
                        'subject': notification.email_subject or 'Payment request',
                        'body': notification.message_body,
                    }
                    if channel == 'email' else
                    {'recipient_phone': notification.recipient_phone_e164, 'message': notification.message_body}
                )
                result = await provider.send(**send_kwargs, notification_id=notification.id)
                if result.successful:
                    await repository.complete(notification.id, status='sent', message_id=result.message_id)
                else:
                    ambiguous = result.error_code == 'provider_timeout'
                    await repository.complete(
                        notification.id, status='uncertain' if ambiguous else 'failed',
                        message_id=result.message_id, error_code=result.error_code,
                        error_message=result.error_message,
                    )
            except Exception as error:
                logger.exception('split_notification.dispatch.failed', extra={'notification_id': str(notification.id)})
                await repository.complete(
                    notification.id, status='uncertain', error_code='provider_exception',
                    error_message=type(error).__name__,
                )
        return len(claimed)


async def run_split_notification_loop(
    provider, *, poll_interval_seconds: int = 5, batch_size: int = 20,
    stale_after_seconds: int = 120, channel: str = 'sms',
) -> None:
    wakeup = asyncio.Event()
    install_sms_scheduler_wakeup(wakeup)
    try:
        while True:
            processed = await run_split_notification_batch_once(
                provider, batch_size=batch_size, stale_after_seconds=stale_after_seconds, channel=channel,
            )
            if processed:
                await asyncio.sleep(0)
                continue
            wakeup.clear()
            try:
                await asyncio.wait_for(wakeup.wait(), timeout=max(1, poll_interval_seconds))
            except TimeoutError:
                pass
    finally:
        clear_sms_scheduler_wakeup(wakeup)
