import { useEffect, useState } from 'react';
import { useGetBalanceEmailStatusQuery, useQueueBalanceStatementMutation } from '../../features/splits/splitsApi';

export function BalanceEmailButton({ contactId, name, onFeedback }: {
  contactId: string; name: string; onFeedback: (message: string) => void;
}) {
  const { data: status, refetch, isError } = useGetBalanceEmailStatusQuery(contactId);
  const [send, { isLoading }] = useQueueBalanceStatementMutation();
  const [clock, setClock] = useState(Date.now());
  useEffect(() => {
    if (!status?.next_available_at && !status?.request_in_progress) return;
    const timer = window.setInterval(() => {
      setClock(Date.now());
      if (status.request_in_progress || (status.next_available_at && Date.now() >= Date.parse(status.next_available_at))) {
        void refetch();
      }
    }, status.request_in_progress ? 10000 : 1000);
    return () => window.clearInterval(timer);
  }, [status, refetch]);
  const minutes = status?.next_available_at
    ? Math.max(0, Math.ceil((Date.parse(status.next_available_at) - clock) / 60000)) : 0;
  const label = isLoading ? 'Queuing reminder…' : status?.request_in_progress ? 'Reminder queued'
    : !status?.limits_bypassed && status?.blocked_reason === 'cooldown_active' ? `Available in ${Math.floor(minutes / 60)}h ${minutes % 60}m`
      : status?.blocked_reason === 'person_limit_reached' ? 'Reminder limit reached'
        : status?.blocked_reason === 'daily_limit_reached' ? 'Daily email limit reached'
          : 'Email balance summary';
  return <div className='mt-2 space-y-1'>
    <button type='button' disabled={isLoading || !status?.can_notify}
      className='w-full rounded-lg border border-[var(--brand-primary)]/40 px-3 py-1.5 text-xs font-semibold text-[var(--brand-primary)] disabled:opacity-50'
      onClick={() => { void send({ contactId, idempotencyKey: crypto.randomUUID() }).unwrap()
        .then(() => onFeedback(`Current balance summary queued for ${name}.`))
        .catch((error: unknown) => {
          const failure = error as { data?: { detail?: { message?: string } } };
          onFeedback(failure.data?.detail?.message ?? 'Could not send the balance summary. Please try again.');
        }); }}>{label}</button>
    {status && <p className='text-xs text-[var(--text-muted)]'>{status.limits_bypassed
      ? `${status.notification_count} reminders sent · Test limits disabled`
      : `Reminders sent: ${status.notification_count} of ${status.max_notifications}`}</p>}
    {isError && <button type='button' className='text-xs text-red-400' onClick={() => { void refetch(); }}>Could not check reminder availability. Retry</button>}
  </div>;
}
