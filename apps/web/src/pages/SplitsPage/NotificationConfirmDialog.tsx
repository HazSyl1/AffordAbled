import { useEffect, useState } from 'react';

import { Button } from '../../components/atoms/Button';
import { Card } from '../../components/atoms/Card';
import {
  useLazyGetSplitNotificationStatusQuery,
  useQueueSplitNotificationMutation,
  type Split,
  type SplitParticipant,
} from '../../features/splits/splitsApi';
import { formatPaiseAsInr } from '../../lib/money';

const blockedMessages: Record<string, string> = {
  upi_id_required: 'Add your UPI ID in Profile before sending a payment request.',
  phone_required: 'Add this person’s phone number under Manage people first.',
  cooldown_active: 'This reminder is in its cooldown period.',
  participant_limit_reached: 'This person has received the maximum of three reminders.',
  daily_limit_reached: 'You have reached today’s SMS limit.',
  request_in_progress: 'A reminder is already being processed.',
  sms_unavailable: 'SMS reminders are not enabled yet.',
  notification_not_supported: 'Reminders are not available for this split type.',
};

function errorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const detail = (error as { data?: { detail?: { message?: string } | string } }).data?.detail;
    if (typeof detail === 'string') return detail;
    if (detail?.message) return detail.message;
  }
  return 'Could not queue the reminder. Please try again.';
}

export function NotificationConfirmDialog({
  split, participant, onClose, onQueued,
}: {
  split: Split;
  participant: SplitParticipant;
  onClose: () => void;
  onQueued: (message: string) => void;
}) {
  const [loadStatus, { data: notificationStatus, isFetching }] = useLazyGetSplitNotificationStatusQuery();
  const [queueNotification, { isLoading }] = useQueueSplitNotificationMutation();
  const [error, setError] = useState('');
  const [clockMs, setClockMs] = useState(() => Date.now());

  useEffect(() => {
    void loadStatus({ splitId: split.id, participantId: participant.id }, true);
  }, [loadStatus, participant.id, split.id]);

  useEffect(() => {
    if (!notificationStatus?.next_available_at) return;
    const availableAtMs = new Date(notificationStatus.next_available_at).getTime();
    const timer = window.setInterval(() => {
      const nextClock = Date.now();
      setClockMs(nextClock);
      if (nextClock >= availableAtMs) {
        window.clearInterval(timer);
        void loadStatus({ splitId: split.id, participantId: participant.id }, false);
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [loadStatus, notificationStatus?.next_available_at, participant.id, split.id]);

  const remaining = Math.max(0, participant.share_paise - participant.settled_paise);
  const blocked = notificationStatus?.blocked_reason;
  const cooldownRemaining = notificationStatus?.next_available_at
    ? Math.max(0, Math.ceil((new Date(notificationStatus.next_available_at).getTime() - clockMs) / 1000))
    : notificationStatus?.cooldown_remaining_seconds ?? 0;
  const blockedMessage = blocked ? blockedMessages[blocked] ?? 'This reminder cannot be sent right now.' : null;
  const isEmail = notificationStatus?.channel === 'email';

  const send = async () => {
    setError('');
    try {
      await queueNotification({
        splitId: split.id,
        participantId: participant.id,
        idempotencyKey: crypto.randomUUID(),
      }).unwrap();
      onQueued(`Payment reminder queued for ${participant.name}.`);
      onClose();
    } catch (failure) {
      setError(errorMessage(failure));
      void loadStatus({ splitId: split.id, participantId: participant.id }, false);
    }
  };

  return <div className='fixed inset-0 z-[120] flex items-center justify-center bg-black/70 p-4' role='presentation'>
    <Card role='dialog' aria-modal='true' aria-labelledby='notification-confirm-title'
      className='w-full max-w-lg space-y-4 p-5'>
      <div>
        <h2 id='notification-confirm-title' className='text-lg font-semibold text-[var(--text-primary)]'>
          Send payment request to {participant.name}?
        </h2>
        <p className='mt-1 text-sm text-[var(--text-muted)]'>Remaining amount: {formatPaiseAsInr(remaining)}</p>
      </div>
      {isFetching && !notificationStatus ? <p className='text-sm text-[var(--text-muted)]'>Checking reminder availability…</p> : null}
      {notificationStatus?.message_preview ? <div className='rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-3'>
        <p className='text-xs text-[var(--text-muted)]'>{isEmail ? 'Email to' : 'SMS to'} {isEmail ? notificationStatus.recipient_email_masked : notificationStatus.recipient_phone_masked}</p>
        <p className='mt-2 whitespace-pre-wrap text-sm text-[var(--text-primary)]'>{notificationStatus.message_preview}</p>
      </div> : null}
      {notificationStatus ? <p className='text-xs text-[var(--text-muted)]'>
        Sent {notificationStatus.notification_count}/{notificationStatus.max_notifications}
        {cooldownRemaining > 0
          ? ` · Available again in ${Math.ceil(cooldownRemaining / 60)} minutes` : ''}
      </p> : null}
      {blockedMessage ? <p role='alert' className='rounded-lg bg-amber-500/10 p-3 text-sm text-amber-300'>{blockedMessage}</p> : null}
      {error ? <p role='alert' className='text-sm text-[var(--negative)]'>{error}</p> : null}
      <div className='grid grid-cols-1 gap-2 sm:grid-cols-2'>
        <Button type='button' disabled={!notificationStatus?.can_notify} isLoading={isLoading}
          onClick={() => { void send(); }}>{isEmail ? 'Send email' : 'Send SMS'}</Button>
        <Button type='button' variant='secondary' disabled={isLoading} onClick={onClose}>Not now</Button>
      </div>
    </Card>
  </div>;
}
