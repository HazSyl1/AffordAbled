import type { FormEvent } from 'react';
import { Pause, Play, X } from 'lucide-react';

import { useListAccountsQuery } from '../../../features/accounts/accountsApi';
import { useListCategoriesQuery } from '../../../features/categories/categoriesApi';
import { useListMemorySuggestionsQuery } from '../../../features/memory/memoryApi';
import {
  type RecurrenceUnit,
  useCancelRecurringTransactionMutation,
  useCreateRecurringTransactionMutation,
  useListRecurringTransactionsQuery,
  usePauseRecurringTransactionMutation,
  useResumeRecurringTransactionMutation,
  useUpdateRecurringTransactionMutation,
} from '../../../features/transactions/recurringTransactionsApi';
import { formatPaiseAsInr } from '../../../lib/money';
import { Button } from '../../atoms/Button';
import { Card } from '../../atoms/Card';

function cadence(unit: RecurrenceUnit, interval: number): string {
  if (unit === 'weekly' && interval > 1) return `Every ${interval} weeks`;
  return `${unit.charAt(0).toUpperCase()}${unit.slice(1)}`;
}

export function RecurringTransactionsPanel() {
  const { data: rules = [], isLoading } = useListRecurringTransactionsQuery();
  const { data: suggestions = [] } = useListMemorySuggestionsQuery();
  const { data: accounts = [] } = useListAccountsQuery();
  const { data: categories = [] } = useListCategoriesQuery();
  const [pause] = usePauseRecurringTransactionMutation();
  const [resume] = useResumeRecurringTransactionMutation();
  const [cancel] = useCancelRecurringTransactionMutation();
  const [update] = useUpdateRecurringTransactionMutation();
  const [create, { isLoading: activating }] = useCreateRecurringTransactionMutation();
  const accountNames = new Map(accounts.map((item) => [item.id, item.name]));
  const categoryNames = new Map(categories.map((item) => [item.id, item.name]));
  const recurringSuggestions = suggestions.filter((item) => item.memory_type === 'recurring_transaction');

  const activateSuggestion = async (suggestion: (typeof recurringSuggestions)[number]) => {
    const value = suggestion.value;
    if (typeof value.account_id !== 'string' || typeof value.category_id !== 'string' ||
        typeof value.amount_paise !== 'number' || typeof value.anchor_at !== 'string' ||
        typeof value.recurrence_unit !== 'string') return;
    await create({
      account_id: value.account_id,
      category_id: value.category_id,
      type: value.type === 'income' ? 'income' : 'expense',
      amount_paise: value.amount_paise,
      merchant: typeof value.merchant === 'string' ? value.merchant : undefined,
      recurrence_unit: value.recurrence_unit as RecurrenceUnit,
      interval_count: typeof value.interval_count === 'number' ? value.interval_count : 1,
      anchor_at: value.anchor_at,
      timezone: typeof value.timezone === 'string' ? value.timezone : 'UTC',
      create_initial_transaction: false,
      source_memory_id: suggestion.id,
    }).unwrap();
  };

  const updateRule = async (event: FormEvent<HTMLFormElement>, id: string) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const unit = String(data.get('recurrence_unit')) as RecurrenceUnit;
    await update({ id, body: {
      amount_paise: Math.round(Number(data.get('amount_rupees')) * 100),
      recurrence_unit: unit,
      interval_count: unit === 'weekly' ? Number(data.get('interval_count')) : 1,
      end_at: data.get('end_at') ? new Date(`${String(data.get('end_at'))}T23:59:59`).toISOString() : undefined,
    } }).unwrap();
  };

  return (
    <div className='space-y-4'>
      {recurringSuggestions.map((suggestion) => {
        const value = suggestion.value;
        return (
          <Card key={suggestion.id} className='border-[color:rgba(168,85,247,0.35)] p-4'>
            <p className='text-sm font-semibold text-[var(--text-primary)]'>Recurring pattern detected</p>
            <p className='mt-1 text-sm text-[var(--text-secondary)]'>
              {String(value.merchant ?? suggestion.subject_key)} · {formatPaiseAsInr(Number(value.amount_paise ?? 0))}
              {' · '}{cadence((value.recurrence_unit as RecurrenceUnit) ?? 'monthly', Number(value.interval_count ?? 1))}
            </p>
            <p className='mt-1 text-xs text-[var(--text-muted)]'>Based on three matching transactions. Review the details above before activation.</p>
            <Button type='button' className='mt-3 w-auto' isLoading={activating}
              onClick={() => void activateSuggestion(suggestion)}>Use this schedule</Button>
          </Card>
        );
      })}

      {isLoading ? <p className='text-sm text-[var(--text-muted)]'>Loading schedules…</p> : null}
      {!isLoading && rules.length === 0 ? (
        <Card className='p-5'><p className='text-sm text-[var(--text-secondary)]'>
          No recurring transactions yet. Use “Repeat this transaction” in the transaction form or ask in chat.
        </p></Card>
      ) : null}
      {rules.map((rule) => (
        <Card key={rule.id} className='p-4'>
          <div className='flex items-start justify-between gap-3'>
            <div>
              <p className='font-semibold text-[var(--text-primary)]'>{rule.merchant || (rule.type === 'income' ? 'Recurring income' : 'Recurring expense')}</p>
              <p className='text-sm text-[var(--text-secondary)]'>{formatPaiseAsInr(rule.amount_paise)} · {cadence(rule.recurrence_unit, rule.interval_count)}</p>
              <p className='mt-1 text-xs text-[var(--text-muted)]'>
                {rule.account_id ? accountNames.get(rule.account_id) : 'Account needs attention'} · {' '}
                {rule.category_id ? categoryNames.get(rule.category_id) : 'Category needs attention'} · {rule.status.replaceAll('_', ' ')}
              </p>
              {rule.next_occurrence_at ? <p className='mt-1 text-xs text-[var(--text-muted)]'>Next: {new Date(rule.next_occurrence_at).toLocaleString()}</p> : null}
              {rule.last_error ? <p role='alert' className='mt-2 text-xs text-[var(--negative)]'>{rule.last_error}</p> : null}
              {!['cancelled', 'completed'].includes(rule.status) ? (
                <details className='mt-3 text-sm text-[var(--text-secondary)]'>
                  <summary className='cursor-pointer font-semibold text-[var(--brand-primary)]'>Edit future schedule</summary>
                  <form className='mt-3 grid grid-cols-2 gap-2' onSubmit={(event) => void updateRule(event, rule.id)}>
                    <label className='text-xs'>Amount (INR)
                      <input name='amount_rupees' type='number' min='0.01' step='0.01'
                        defaultValue={(rule.amount_paise / 100).toFixed(2)}
                        className='mt-1 min-h-10 w-full rounded-lg border border-[var(--bg-border)] bg-[var(--bg-surface)] px-2' />
                    </label>
                    <label className='text-xs'>Frequency
                      <select name='recurrence_unit' defaultValue={rule.recurrence_unit}
                        className='mt-1 min-h-10 w-full rounded-lg border border-[var(--bg-border)] bg-[var(--bg-surface)] px-2'>
                        <option value='daily'>Daily</option><option value='weekly'>Weekly</option>
                        <option value='monthly'>Monthly</option><option value='yearly'>Yearly</option>
                      </select>
                    </label>
                    <label className='text-xs'>Weekly interval
                      <input name='interval_count' type='number' min='1' max='52' defaultValue={rule.interval_count}
                        className='mt-1 min-h-10 w-full rounded-lg border border-[var(--bg-border)] bg-[var(--bg-surface)] px-2' />
                    </label>
                    <label className='text-xs'>End date
                      <input name='end_at' type='date' defaultValue={rule.end_at?.slice(0, 10) ?? ''}
                        className='mt-1 min-h-10 w-full rounded-lg border border-[var(--bg-border)] bg-[var(--bg-surface)] px-2' />
                    </label>
                    <Button type='submit' className='col-span-2 mt-1'>Save future changes</Button>
                  </form>
                </details>
              ) : null}
            </div>
            <div className='flex shrink-0 gap-2'>
              {rule.status === 'active' ? (
                <Button type='button' variant='secondary' aria-label='Pause schedule' className='w-auto px-3'
                  onClick={() => void pause(rule.id)}><Pause size={15} /></Button>
              ) : rule.status === 'paused' || rule.status === 'needs_attention' ? (
                <Button type='button' variant='secondary' aria-label='Resume schedule' className='w-auto px-3'
                  onClick={() => void resume(rule.id)}><Play size={15} /></Button>
              ) : null}
              {!['cancelled', 'completed'].includes(rule.status) ? (
                <Button type='button' variant='secondary' aria-label='Cancel schedule' className='w-auto px-3'
                  onClick={() => void cancel(rule.id)}><X size={15} /></Button>
              ) : null}
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}
