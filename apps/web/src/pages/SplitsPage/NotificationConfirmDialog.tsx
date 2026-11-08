import { useEffect, useState } from 'react';

import { Button } from '../../components/atoms/Button';
import { Card } from '../../components/atoms/Card';
import {
  useLazyGetSplitNotificationStatusQuery,
  useQueueSplitNotificationMutation,
  useRenameSplitMutation,
  useSetSplitContactDetailsMutation,
  type Split,
  type SplitContactDetails,
} from '../../features/splits/splitsApi';
import { formatPaiseAsInr } from '../../lib/money';

const blockedMessages: Record<string, string> = {
  upi_id_required: 'Add your UPI ID in Profile before sending a payment request.',
  cooldown_active: 'This split reminder is in its cooldown period.',
  split_limit_reached: 'This split has received the maximum of three reminder campaigns.',
  daily_limit_reached: 'You have reached today\'s notification limit.',
  request_in_progress: 'A reminder campaign for this split is already being processed.',
  notification_unavailable: 'Payment reminders are not enabled yet.',
  notification_not_supported: 'Reminders are not available for this split type.',
  already_settled: 'Everyone in this split has already repaid their share.',
};

function errorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const detail = (error as { data?: { detail?: { message?: string } | string } }).data?.detail;
    if (typeof detail === 'string') return detail;
    if (detail?.message) return detail.message;
  }
  return 'Could not update or send this reminder. Please try again.';
}

export function NotificationConfirmDialog({
  split, contacts, onClose, onQueued,
}: {
  split: Split;
  contacts: SplitContactDetails[];
  onClose: () => void;
  onQueued: (message: string) => void;
}) {
  const [loadStatus, { data: notificationStatus, isFetching }] = useLazyGetSplitNotificationStatusQuery();
  const [queueNotification, { isLoading }] = useQueueSplitNotificationMutation();
  const [renameSplit, { isLoading: isRenaming }] = useRenameSplitMutation();
  const [description, setDescription] = useState(split.title);
  const [setContactDetails, { isLoading: isSavingEmails }] = useSetSplitContactDetailsMutation();
  const [emails, setEmails] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [clockMs, setClockMs] = useState(() => Date.now());

  useEffect(() => {
    void loadStatus({ splitId: split.id }, true);
  }, [loadStatus, split.id]);

  useEffect(() => {
    if (!notificationStatus?.missing_recipients.length) return;
    setEmails((current) => ({
      ...notificationStatus.missing_recipients.reduce<Record<string, string>>((result, recipient) => {
        result[recipient.participant_id] = current[recipient.participant_id] ?? '';
        return result;
      }, {}),
    }));
  }, [notificationStatus?.missing_recipients]);

  useEffect(() => {
    if (!notificationStatus?.next_available_at) return;
    const availableAtMs = new Date(notificationStatus.next_available_at).getTime();
    const timer = window.setInterval(() => {
      const nextClock = Date.now();
      setClockMs(nextClock);
      if (nextClock >= availableAtMs) {
        window.clearInterval(timer);
        void loadStatus({ splitId: split.id }, false);
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [loadStatus, notificationStatus?.next_available_at, split.id]);

  const cooldownRemaining = notificationStatus?.next_available_at
    ? Math.max(0, Math.ceil((new Date(notificationStatus.next_available_at).getTime() - clockMs) / 1000))
    : notificationStatus?.cooldown_remaining_seconds ?? 0;
  const missing = notificationStatus?.missing_recipients ?? [];
  const blocked = notificationStatus?.blocked_reason;
  const blockedMessage = blocked && blocked !== 'participant_emails_required'
    ? blockedMessages[blocked] ?? 'This reminder cannot be sent right now.' : null;

  const saveEmails = async () => {
    setError('');
    try {
      for (const recipient of missing) {
        const email = emails[recipient.participant_id]?.trim().toLowerCase();
        if (!email) throw new Error('email_required');
        const contact = contacts.find((item) => item.id === recipient.contact_id) ?? contacts.find((item) =>
          item.name.trim().toLowerCase() === recipient.name.trim().toLowerCase());
        await setContactDetails({
          ...(contact?.id ? { contact_id: contact.id } : {}),
          name: recipient.name, email, phone_e164: contact?.phone_e164 ?? null,
        }).unwrap();
      }
      await loadStatus({ splitId: split.id }, false);
    } catch (failure) {
      setError(failure instanceof Error && failure.message === 'email_required'
        ? 'Enter an email address for every person.' : errorMessage(failure));
    }
  };

  const send = async () => {
    setError('');
    try {
      const cleanDescription = description.trim().replace(/\s+/g, ' ');
      if (!cleanDescription) {
        setError('Enter a short description for this payment request.');
        return;
      }
      if (cleanDescription !== split.title) {
        // The email's "For" line comes from the split, so save the edit before queuing.
        await renameSplit({ splitId: split.id, title: cleanDescription }).unwrap();
      }
      const result = await queueNotification({
        splitId: split.id, idempotencyKey: crypto.randomUUID(),
      }).unwrap();
      const count = result.notification_ids.length;
      onQueued(`${count} payment reminder${count === 1 ? '' : 's'} queued for ${cleanDescription}.`);
      onClose();
    } catch (failure) {
      setError(errorMessage(failure));
      void loadStatus({ splitId: split.id }, false);
    }
  };

  return <div className='fixed inset-0 z-[120] flex items-center justify-center overflow-y-auto bg-black/70 p-4'
    role='presentation'>
    <Card role='dialog' aria-modal='true' aria-labelledby='notification-confirm-title'
      className='my-auto w-full max-w-lg space-y-4 p-5'>
      <div>
        <h2 id='notification-confirm-title' className='text-lg font-semibold text-[var(--text-primary)]'>
          Send reminders for {split.title}?
        </h2>
        <p className='mt-1 text-sm text-[var(--text-muted)]'>
          Each unpaid person receives a separate email containing their amount and this split's transaction details.
        </p>
      </div>
      <label className='block space-y-1 text-sm text-[var(--text-secondary)]'>
        <span className='font-medium text-[var(--text-primary)]'>What is this payment for?</span>
        <textarea rows={2} maxLength={255} value={description} onChange={(event) => setDescription(event.target.value)}
          className='w-full resize-none rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] px-3 py-2 text-[var(--text-primary)]' />
        <span className='block text-xs text-[var(--text-muted)]'>
          Shown to everyone in the email. Editing it also renames this split.
        </span>
      </label>
      {isFetching && !notificationStatus && <p className='text-sm text-[var(--text-muted)]'>
        Checking reminder availability...
      </p>}
      {notificationStatus?.recipients.length ? <ul className='space-y-2'>
        {notificationStatus.recipients.map((recipient) => <li key={recipient.participant_id}
          className='flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--bg-border)] p-3 text-sm'>
          <span><strong className='text-[var(--text-primary)]'>{recipient.name}</strong>
            <span className='block text-xs text-[var(--text-muted)]'>{recipient.recipient ?? 'Email required'}</span></span>
          <span className='font-medium text-[var(--text-primary)]'>{formatPaiseAsInr(recipient.amount_paise)}</span>
        </li>)}
      </ul> : null}
      {missing.length > 0 && <form className='space-y-3 rounded-xl border border-amber-400/30 bg-amber-400/10 p-4'
        onSubmit={(event) => { event.preventDefault(); void saveEmails(); }}>
        <div>
          <p className='font-medium text-amber-200'>Add missing email addresses</p>
          <p className='mt-1 text-xs text-amber-100/80'>
            These addresses are saved under Manage people and used only for split reminders you confirm.
          </p>
        </div>
        {missing.map((recipient) => <label key={recipient.participant_id}
          className='block space-y-1 text-sm text-[var(--text-secondary)]'>{recipient.name}
          <input className='w-full rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] px-3 py-2 text-[var(--text-primary)]'
            type='email' required maxLength={320} value={emails[recipient.participant_id] ?? ''}
            placeholder='person@example.com' onChange={(event) => setEmails((current) => ({
              ...current, [recipient.participant_id]: event.target.value,
            }))} />
        </label>)}
        <Button type='submit' isLoading={isSavingEmails}>Save emails</Button>
      </form>}
      {notificationStatus && <p className='text-xs text-[var(--text-muted)]'>
        {notificationStatus.limits_bypassed
          ? `${notificationStatus.notification_count} reminder campaign${notificationStatus.notification_count === 1 ? '' : 's'} sent · Test limits disabled`
          : `Reminder campaigns ${notificationStatus.notification_count}/${notificationStatus.max_notifications}`}
        {!notificationStatus.limits_bypassed && cooldownRemaining > 0 ? ` · Available again in ${Math.ceil(cooldownRemaining / 60)} minutes` : ''}
      </p>}
      {blockedMessage && <p role='alert'
        className='rounded-lg bg-amber-500/10 p-3 text-sm text-amber-300'>{blockedMessage}</p>}
      {error && <p role='alert' className='text-sm text-[var(--negative)]'>{error}</p>}
      <div className='grid grid-cols-1 gap-2 sm:grid-cols-2'>
        <Button type='button' disabled={!notificationStatus?.can_notify || isSavingEmails || !description.trim()} isLoading={isLoading || isRenaming}
          onClick={() => { void send(); }}>
          Send {notificationStatus?.recipients.length ?? 0} email{notificationStatus?.recipients.length === 1 ? '' : 's'}
        </Button>
        <Button type='button' variant='secondary' disabled={isLoading || isSavingEmails} onClick={onClose}>Not now</Button>
      </div>
    </Card>
  </div>;
}
