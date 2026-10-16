import { useMemo, useState, type FormEvent } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { Button } from '../../components/atoms/Button';
import { Card } from '../../components/atoms/Card';
import { ThemedSelect } from '../../components/molecules/ThemedSelect';
import {
  useCreateSplitMutation, useListSplitContactsQuery, useListSplitsQuery,
  useSettleSplitParticipantMutation, useDeleteSplitMutation, type CreateSplitRequest,
} from '../../features/splits/splitsApi';
import { useListTransactionsQuery } from '../../features/transactions/transactionsApi';
import { formatPaiseAsInr } from '../../lib/money';

type Person = { name: string; amount: string | null; isNew: boolean };
const NEW_PERSON = '__new_person__';
const newPerson = (): Person => ({ name: '', amount: null, isNew: false });
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
  const [searchParams] = useSearchParams();
  const { data: splits = [], isLoading } = useListSplitsQuery();
  const { data: transactions = [] } = useListTransactionsQuery();
  const { data: contacts = [] } = useListSplitContactsQuery();
  const [createSplit, { isLoading: creating }] = useCreateSplitMutation();
  const [settle, { isLoading: settling }] = useSettleSplitParticipantMutation();
  const [deleteSplit, { isLoading: deleting }] = useDeleteSplitMutation();
  const [open, setOpen] = useState(location.pathname.endsWith('/new'));
  const [transactionId, setTransactionId] = useState(searchParams.get('transactionId') ?? '');
  const [title, setTitle] = useState('');
  const [mode, setMode] = useState<'equal' | 'custom'>('equal');
  const [ownerAmount, setOwnerAmount] = useState<string | null>(null);
  const [people, setPeople] = useState<Person[]>([newPerson()]);
  const [review, setReview] = useState<CreateSplitRequest | null>(null);
  const [error, setError] = useState('');
  const [showValidation, setShowValidation] = useState(false);
  const [repayments, setRepayments] = useState<Record<string, string>>({});

  const expenses = useMemo(() => transactions.filter((transaction) =>
    transaction.type === 'expense' && !transaction.deleted_at &&
    !splits.some((split) => split.transaction_id === transaction.id)), [transactions, splits]);
  const expense = expenses.find((item) => item.id === transactionId);
  const recentExpenses = expenses.slice(0, 5);
  const selectedOlderExpense = expense && !recentExpenses.some((item) => item.id === expense.id);
  const displayedExpenses = selectedOlderExpense
    ? [expense, ...recentExpenses.slice(0, 4)] : recentExpenses;
  const equalShare = expense ? Math.floor(expense.amount_paise / (people.length + 1)) : 0;
  const ownerEqualShare = expense ? equalShare + expense.amount_paise % (people.length + 1) : 0;
  const displayedOwnerAmount = ownerAmount ?? (expense ? (ownerEqualShare / 100).toFixed(2) : '');
  const ownCustomShare = paise(displayedOwnerAmount);
  const displayedPersonAmount = (person: Person) => person.amount ?? (expense ? (equalShare / 100).toFixed(2) : '');
  const customShares = people.map((person) => paise(displayedPersonAmount(person)));
  const amountsValid = ownCustomShare !== null && ownCustomShare >= 0 &&
    customShares.every((share) => share !== null && share > 0);
  const allocatedPaise = (ownCustomShare ?? 0) + customShares.reduce<number>((sum, share) => sum + (share ?? 0), 0);
  const remainingPaise = expense ? expense.amount_paise - allocatedPaise : 0;
  const allocationError = mode === 'custom' && Boolean(expense) && (!amountsValid || remainingPaise !== 0);
  const names = people.map((person) => person.name.trim());
  const invalidNames = names.map((name, index) => !name || names.some((other, row) => row !== index && other.toLowerCase() === name.toLowerCase()));

  function updatePerson(index: number, change: Partial<Person>) {
    setPeople((current) => current.map((person, row) => row === index ? { ...person, ...change } : person));
    setReview(null);
    setError('');
  }

  function addPerson() {
    if (mode === 'custom' && (ownerAmount !== null || people.some((person) => person.amount !== null))) {
      setOwnerAmount(displayedOwnerAmount);
      setPeople([
        ...people.map((person) => ({ ...person, amount: displayedPersonAmount(person) })),
        { ...newPerson(), amount: amountsValid && remainingPaise > 0 ? (remainingPaise / 100).toFixed(2) : '' },
      ]);
    } else {
      setPeople((current) => [...current, newPerson()]);
    }
    setReview(null);
    setError('');
  }

  function prepare(event: FormEvent) {
    event.preventDefault();
    setError('');
    setShowValidation(true);
    if (!expense) { setError('Choose an expense.'); return; }
    if (invalidNames.some(Boolean)) {
      setError('Enter a different name for each person.'); return;
    }
    if (allocationError) {
      setError('Custom shares, including yours, must add up to the expense exactly.'); return;
    }
    setReview({
      transaction_id: expense.id, title: title.trim() || expense.merchant || 'Shared expense',
      amount_paise: expense.amount_paise, mode,
      owner_share_paise: mode === 'equal' ? ownerEqualShare : ownCustomShare ?? 0,
      participants: people.map((person, index) => ({
        name: person.name.trim(), share_paise: mode === 'equal' ? equalShare : customShares[index] ?? 0,
      })),
    });
  }

  async function confirm() {
    if (!review) return;
    try {
      await createSplit(review).unwrap();
      setOpen(false); setReview(null); setTransactionId(''); setTitle('');
      setPeople([newPerson()]); setOwnerAmount(null); setShowValidation(false); setError(''); navigate('/splits');
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
      <form onSubmit={prepare} noValidate className='space-y-4'>
        <div className='space-y-1 text-sm text-[var(--text-secondary)]'>
          <label htmlFor='split-expense'>Expense</label>
          <ThemedSelect id='split-expense' value={transactionId} placeholder='Choose an expense'
            invalid={showValidation && !expense}
            options={displayedExpenses.map((item) => ({
              value: item.id,
              label: `${item.merchant || item.note || 'Expense'} · ${formatPaiseAsInr(item.amount_paise)} · ${new Date(item.occurred_at).toLocaleDateString()}`,
            }))}
            onChange={(value) => { setTransactionId(value); setReview(null); setError(''); }} />
        </div>
        {expenses.length > 0 && <p className='text-xs text-[var(--text-muted)]'>{selectedOlderExpense ? 'Showing the selected expense and up to 4 recent expenses.' : 'Showing up to 5 recent expenses.'} To see more, <button type='button' className='text-[var(--brand-primary)] hover:underline' onClick={() => navigate('/transactions')}>go to Transactions</button> and select an expense to split.</p>}
        {expenses.length === 0 && <p className='text-sm text-[var(--text-muted)]'>Record an expense first to split it.</p>}
        <label className='block space-y-1 text-sm text-[var(--text-secondary)]'>Title
          <input className={inputClass} maxLength={255} value={title} onChange={(event) => { setTitle(event.target.value); setReview(null); }} placeholder='Dinner with friends' />
        </label>
        <div className='flex gap-4 text-sm text-[var(--text-primary)]'>
          <label><input type='radio' checked={mode === 'equal'} onChange={() => { setMode('equal'); setReview(null); setError(''); }} /> Equal</label>
          <label><input type='radio' checked={mode === 'custom'} onChange={() => { setMode('custom'); setReview(null); setError(''); }} /> Custom</label>
        </div>
        {mode === 'custom' && <p className='text-xs text-[var(--text-muted)]'>Shares start equally divided. After you edit a share, new people receive the remaining amount.</p>}
        <div className='space-y-3 rounded-xl border border-[var(--bg-border)] p-3'>
          {mode === 'custom' && <label className='block space-y-1 text-sm text-[var(--text-secondary)]'>Your share (₹)
            <input className={`${inputClass} ${ownCustomShare === null ? 'border-red-400/70' : ''}`}
              inputMode='decimal' aria-invalid={ownCustomShare === null} value={displayedOwnerAmount}
              onFocus={(event) => { if (ownerAmount === null) event.currentTarget.select(); }}
              onChange={(event) => { setOwnerAmount(event.target.value); setReview(null); setError(''); }} />
          </label>}
          <div className='space-y-2'>
            <p className='text-sm text-[var(--text-secondary)]'>People who owe you</p>
            {people.map((person, index) => <div key={index} className='space-y-2 rounded-lg border border-[var(--bg-border)] p-2'>
              <div className='flex items-center gap-2'>
                <div className='min-w-0 flex-1'>
                  <ThemedSelect id={`split-person-${index}`} value={person.isNew ? NEW_PERSON : person.name}
                    placeholder='Choose a person'
                    invalid={showValidation && invalidNames[index]}
                    options={[
                      { value: NEW_PERSON, label: person.isNew && person.name ? `New: ${person.name}` : '+ Add new person' },
                      ...contacts.filter((contact) => !people.some((other, row) => row !== index && other.name.toLowerCase() === contact.toLowerCase()))
                        .map((contact) => ({ value: contact, label: contact })),
                    ]}
                    onChange={(value) => updatePerson(index, value === NEW_PERSON
                      ? { name: '', isNew: true } : { name: value, isNew: false })} />
                </div>
                {people.length > 1 && <button type='button' className='text-sm text-[var(--text-muted)]' onClick={() => { setPeople((current) => current.filter((_, row) => row !== index)); setReview(null); setError(''); }}>Remove</button>}
              </div>
              {person.isNew && <input className={`${inputClass} ${showValidation && invalidNames[index] ? 'border-red-400/70' : ''}`}
                aria-label={`New person ${index + 1} name`} aria-invalid={showValidation && invalidNames[index]}
                placeholder='Person name' maxLength={100} value={person.name}
                onChange={(event) => updatePerson(index, { name: event.target.value })} />}
              {mode === 'custom' && <label className='block space-y-1 text-xs text-[var(--text-secondary)]'>Share (₹)
                <input className={`${inputClass} ${customShares[index] === null || (customShares[index] ?? 0) <= 0 ? 'border-red-400/70' : ''}`}
                  inputMode='decimal' aria-label={`Amount for person ${index + 1} in rupees`}
                  aria-invalid={customShares[index] === null || (customShares[index] ?? 0) <= 0}
                  value={displayedPersonAmount(person)}
                  onFocus={(event) => { if (person.amount === null) event.currentTarget.select(); }}
                  onChange={(event) => updatePerson(index, { amount: event.target.value })} />
              </label>}
            </div>)}
            {people.length < 20 && <button type='button' className='text-sm text-[var(--brand-primary)]' onClick={addPerson}>+ Add person</button>}
          </div>
          {mode === 'equal' && expense && <p className='text-sm text-[var(--text-secondary)]'>Each person owes {formatPaiseAsInr(equalShare)}. Your share is {formatPaiseAsInr(ownerEqualShare)}.</p>}
          {mode === 'custom' && expense && <div role='status' className='rounded-lg border border-[var(--bg-border)] p-3 text-sm text-[var(--text-secondary)]'>
            <p>Total: {formatPaiseAsInr(expense.amount_paise)}</p>
            <p>Allocated: {formatPaiseAsInr(allocatedPaise)}</p>
            <p className={`font-semibold ${allocationError ? 'text-red-400' : ''}`}>Remaining: {formatPaiseAsInr(remainingPaise)}</p>
            {allocationError && <p className='mt-1 text-xs text-red-400'>Enter valid shares that add up to the total.</p>}
          </div>}
        </div>
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
