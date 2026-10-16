import { useMemo, useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { Button } from '../../components/atoms/Button';
import { Card } from '../../components/atoms/Card';
import {
  useCreateSplitMutation, useListSplitContactsQuery, useListSplitsQuery,
  useSettleSplitParticipantMutation, useDeleteSplitMutation, type CreateSplitRequest,
} from '../../features/splits/splitsApi';
import { useListTransactionsQuery } from '../../features/transactions/transactionsApi';
import { formatPaiseAsInr } from '../../lib/money';

type Person = { name: string; amount: string };
const inputClass = 'w-full rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] px-3 py-2 text-[var(--text-primary)]';

function paise(value: string): number | null {
  return /^\d+(?:\.\d{1,2})?$/.test(value.trim()) ? Math.round(Number(value) * 100) : null;
}

function detail(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const data = (error as { data?: { detail?: string } }).data;
    if (typeof data?.detail === 'string') return data.detail;
  }
  return 'Please try again.';
}

export function SplitsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { data: splits = [], isLoading } = useListSplitsQuery();
  const { data: transactions = [] } = useListTransactionsQuery();
  const { data: contacts = [] } = useListSplitContactsQuery();
  const [createSplit, { isLoading: creating }] = useCreateSplitMutation();
  const [settle, { isLoading: settling }] = useSettleSplitParticipantMutation();
  const [deleteSplit, { isLoading: deleting }] = useDeleteSplitMutation();
  const [open, setOpen] = useState(location.pathname.endsWith('/new'));
  const [transactionId, setTransactionId] = useState('');
  const [title, setTitle] = useState('');
  const [mode, setMode] = useState<'equal' | 'custom'>('equal');
  const [ownerAmount, setOwnerAmount] = useState('');
  const [people, setPeople] = useState<Person[]>([{ name: '', amount: '' }]);
  const [review, setReview] = useState<CreateSplitRequest | null>(null);
  const [error, setError] = useState('');
  const [repayments, setRepayments] = useState<Record<string, string>>({});

  const expenses = useMemo(() => transactions.filter((transaction) =>
    transaction.type === 'expense' && !transaction.deleted_at &&
    !splits.some((split) => split.transaction_id === transaction.id)), [transactions, splits]);
  const expense = expenses.find((item) => item.id === transactionId);
  const equalShare = expense ? Math.floor(expense.amount_paise / (people.length + 1)) : 0;
  const ownerEqualShare = expense ? equalShare + expense.amount_paise % (people.length + 1) : 0;

  function updatePerson(index: number, change: Partial<Person>) {
    setPeople((current) => current.map((person, row) => row === index ? { ...person, ...change } : person));
    setReview(null);
  }

  function prepare(event: FormEvent) {
    event.preventDefault();
    setError('');
    if (!expense) { setError('Choose an expense.'); return; }
    const names = people.map((person) => person.name.trim());
    if (names.some((name) => !name) || new Set(names.map((name) => name.toLowerCase())).size !== names.length) {
      setError('Enter a different name for each person.'); return;
    }
    const shares = people.map((person) => paise(person.amount));
    const own = paise(ownerAmount);
    if (mode === 'custom' && (own === null || shares.some((share) => share === null || share <= 0) ||
      own + shares.reduce<number>((sum, share) => sum + (share ?? 0), 0) !== expense.amount_paise)) {
      setError('Custom shares, including yours, must add up to the expense exactly.'); return;
    }
    setReview({
      transaction_id: expense.id, title: title.trim() || expense.merchant || 'Shared expense',
      amount_paise: expense.amount_paise, mode,
      owner_share_paise: mode === 'equal' ? ownerEqualShare : own ?? 0,
      participants: people.map((person, index) => ({
        name: person.name.trim(), share_paise: mode === 'equal' ? equalShare : shares[index] ?? 0,
      })),
    });
  }

  async function confirm() {
    if (!review) return;
    try {
      await createSplit(review).unwrap();
      setOpen(false); setReview(null); setTransactionId(''); setTitle('');
      setPeople([{ name: '', amount: '' }]); setError(''); navigate('/splits');
    } catch (failure) { setError(detail(failure)); }
  }

  async function markRepaid(splitId: string, participantId: string) {
    const repaymentTransactionId = repayments[participantId];
    if (!repaymentTransactionId) { setError('Choose a recorded repayment first.'); return; }
    setError('');
    try { await settle({ splitId, participantId, repaymentTransactionId }).unwrap(); }
    catch (failure) { setError(detail(failure)); }
  }

  async function removeSplit(splitId: string) {
    if (!window.confirm('Remove this split? The original expense will stay in your transactions.')) return;
    setError('');
    try { await deleteSplit(splitId).unwrap(); }
    catch (failure) { setError(detail(failure)); }
  }

  return <div className='mx-auto w-full max-w-[900px] space-y-5 px-4 py-4 md:px-6 md:py-6'>
    <header className='flex items-start justify-between gap-4'>
      <div><h1 className='text-xl font-bold text-[var(--text-primary)]'>Splits</h1>
        <p className='text-sm text-[var(--text-muted)]'>Track who owes you for shared expenses.</p></div>
      <Button className='w-auto' onClick={() => { setOpen(true); setReview(null); }}>New split</Button>
    </header>
    {error && <p role='alert' className='rounded-xl bg-red-500/10 p-3 text-sm text-red-300'>{error}</p>}
    {open && <Card className='space-y-4 p-5'>
      <h2 className='font-semibold text-[var(--text-primary)]'>Share a recorded expense</h2>
      <p className='text-xs text-[var(--text-muted)]'>The purchase is already in your account. Link each repayment to a recorded income or refund when it arrives.</p>
      <form onSubmit={prepare} className='space-y-4'>
        <label className='block space-y-1 text-sm text-[var(--text-secondary)]'>Expense
          <select className={inputClass} value={transactionId} onChange={(event) => { setTransactionId(event.target.value); setReview(null); }} required>
            <option value=''>Choose an expense</option>
            {expenses.map((item) => <option key={item.id} value={item.id}>
              {item.merchant || item.note || 'Expense'} · {formatPaiseAsInr(item.amount_paise)} · {new Date(item.occurred_at).toLocaleDateString()}
            </option>)}
          </select>
        </label>
        {expenses.length === 0 && <p className='text-sm text-[var(--text-muted)]'>Record an expense first to split it.</p>}
        <label className='block space-y-1 text-sm text-[var(--text-secondary)]'>Title
          <input className={inputClass} maxLength={255} value={title} onChange={(event) => { setTitle(event.target.value); setReview(null); }} placeholder='Dinner with friends' />
        </label>
        <div className='flex gap-4 text-sm text-[var(--text-primary)]'>
          <label><input type='radio' checked={mode === 'equal'} onChange={() => { setMode('equal'); setReview(null); }} /> Equal</label>
          <label><input type='radio' checked={mode === 'custom'} onChange={() => { setMode('custom'); setReview(null); }} /> Custom</label>
        </div>
        {mode === 'custom' && <label className='block space-y-1 text-sm text-[var(--text-secondary)]'>Your share (₹)
          <input className={inputClass} inputMode='decimal' value={ownerAmount} onChange={(event) => { setOwnerAmount(event.target.value); setReview(null); }} required />
        </label>}
        <div className='space-y-2'>
          <p className='text-sm text-[var(--text-secondary)]'>People who owe you</p>
          {people.map((person, index) => <div key={index} className='flex gap-2'>
            <input className={inputClass} list='split-contacts' aria-label={`Person ${index + 1}`} placeholder='Name' value={person.name} onChange={(event) => updatePerson(index, { name: event.target.value })} required />
            {mode === 'custom' && <input className={inputClass} inputMode='decimal' aria-label={`Amount for person ${index + 1} in rupees`} placeholder='₹' value={person.amount} onChange={(event) => updatePerson(index, { amount: event.target.value })} required />}
            {people.length > 1 && <button type='button' className='text-sm text-[var(--text-muted)]' onClick={() => { setPeople((current) => current.filter((_, row) => row !== index)); setReview(null); }}>Remove</button>}
          </div>)}
          <datalist id='split-contacts'>{contacts.map((contact) => <option key={contact} value={contact} />)}</datalist>
          {people.length < 20 && <button type='button' className='text-sm text-[var(--brand-primary)]' onClick={() => { setPeople((current) => [...current, { name: '', amount: '' }]); setReview(null); }}>+ Add person</button>}
        </div>
        {mode === 'equal' && expense && <p className='text-sm text-[var(--text-secondary)]'>Each person owes {formatPaiseAsInr(equalShare)}. Your share is {formatPaiseAsInr(ownerEqualShare)}.</p>}
        <div className='flex gap-2'><Button type='submit' disabled={!expense}>Review split</Button>
          <Button type='button' variant='secondary' onClick={() => { setOpen(false); setReview(null); navigate('/splits'); }}>Cancel</Button></div>
      </form>
      {review && <div className='space-y-2 rounded-xl border border-[var(--bg-border)] p-4 text-sm text-[var(--text-primary)]'>
        <h3 className='font-semibold'>Confirm {review.title}</h3>
        <p>Total {formatPaiseAsInr(review.amount_paise)} · Your share {formatPaiseAsInr(review.owner_share_paise ?? 0)}</p>
        {review.participants.map((person) => <p key={person.name}>{person.name}: {formatPaiseAsInr(person.share_paise)}</p>)}
        <Button isLoading={creating} onClick={confirm}>Create split</Button>
      </div>}
    </Card>}
    <section className='space-y-3'><h2 className='font-semibold text-[var(--text-primary)]'>Your split tracker</h2>
      {isLoading ? <p className='text-sm text-[var(--text-muted)]'>Loading splits…</p> : splits.length === 0 ?
        <Card className='p-5 text-sm text-[var(--text-muted)]'>No splits yet.</Card> : splits.map((split) =>
          <Card key={split.id} className='space-y-3 p-5'>
            <div className='flex justify-between gap-3'><div><h3 className='font-semibold text-[var(--text-primary)]'>{split.title}</h3>
              <p className='text-xs text-[var(--text-muted)]'>Total {formatPaiseAsInr(split.total_paise)} · Your share {formatPaiseAsInr(split.owner_share_paise)}</p></div>
              <div className='text-right'><span className='text-sm font-semibold text-[var(--text-primary)]'>{formatPaiseAsInr(split.outstanding_paise)} due</span>
                <button className='block text-xs text-[var(--text-muted)]' disabled={deleting} onClick={() => removeSplit(split.id)}>Remove split</button></div></div>
            {split.participants.map((person) => <div key={person.id} className='flex items-center justify-between gap-3 border-t border-[var(--bg-border)] pt-2 text-sm'>
              <span className='text-[var(--text-primary)]'>{person.name} · {formatPaiseAsInr(person.share_paise)}</span>
              {person.settled_paise === person.share_paise ? <span className='text-green-400'>Settled</span> :
                <div className='flex flex-col items-end gap-1'>
                  <select aria-label={`Repayment for ${person.name}`} className='max-w-40 rounded-lg border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-1 text-xs text-[var(--text-primary)]'
                    value={repayments[person.id] ?? ''} onChange={(event) => setRepayments((current) => ({ ...current, [person.id]: event.target.value }))}>
                    <option value=''>Choose repayment</option>
                    {transactions.filter((transaction) =>
                      (transaction.type === 'income' || transaction.type === 'refund') &&
                      !transaction.deleted_at && transaction.amount_paise === person.share_paise &&
                      !splits.some((item) => item.participants.some((linked) => linked.repayment_transaction_id === transaction.id)))
                      .map((transaction) => <option key={transaction.id} value={transaction.id}>
                        {transaction.merchant || transaction.note || 'Repayment'} · {new Date(transaction.occurred_at).toLocaleDateString()}
                      </option>)}
                  </select>
                  <button disabled={settling || !repayments[person.id]} className='text-[var(--brand-primary)] disabled:opacity-50' onClick={() => markRepaid(split.id, person.id)}>Link repayment</button>
                </div>}
            </div>)}
            {split.outstanding_paise > 0 && <button className='text-xs text-[var(--text-muted)]' onClick={() => navigate('/transactions')}>Record a repayment in Transactions first</button>}
          </Card>)}
    </section>
  </div>;
}
