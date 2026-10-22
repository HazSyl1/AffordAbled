import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { Button } from '../../components/atoms/Button';
import { Card } from '../../components/atoms/Card';
import { ThemedSelect } from '../../components/molecules/ThemedSelect';
import { useListAccountsQuery } from '../../features/accounts/accountsApi';
import {
  useCreateSplitMutation, useListSplitContactsQuery, useListSplitsQuery,
  useCreateOwedMutation,
  useRepaySplitParticipantMutation, useRepaySettlementTransferMutation,
  useDeleteSplitMutation, useUpdateSplitMutation,
  type CreateSplitRequest, type Split,
} from '../../features/splits/splitsApi';
import { useListSettlementPlansQuery, useSettleSettlementPlanTransferMutation,
  type SettlementPlan } from '../../features/splits/settlementPlansApi';
import { useListTransactionsQuery } from '../../features/transactions/transactionsApi';
import { formatPaiseAsInr } from '../../lib/money';
import { ComplexSettlementPlanner } from './ComplexSettlementPlanner';

type Person = { name: string; amount: string | null; isNew: boolean };
const NEW_PERSON = '__new_person__';
const newPerson = (): Person => ({ name: '', amount: null, isNew: false });
const inputClass = 'min-w-0 w-full rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] px-3 py-2 text-[var(--text-primary)]';

function paise(value: string): number | null {
  return /^\d+(?:\.\d{1,2})?$/.test(value.trim()) ? Math.round(Number(value) * 100) : null;
}

function detail(error: unknown): string {
  if (typeof error === 'object' && error !== null) {
    if ('data' in error) {
      const data = (error as { data?: { detail?: string } }).data;
      if (typeof data?.detail === 'string') return data.detail;
    }
    if ('status' in error) {
      const status = (error as { status: unknown }).status;
      if (status === 'FETCH_ERROR') return 'Could not reach the API. Check that the server is running.';
      if (typeof status === 'number') return `Request failed (${status}). Check the API logs for details.`;
    }
  }
  return 'Could not complete the request. Please try again.';
}

function unpaidCount(split: Split): number {
  return split.settlement_breakdown
    ? split.settlement_breakdown.transfers.filter((transfer) =>
      transfer.creditor.trim().toLowerCase() === 'you' && !transfer.repayment_transaction_id).length
    : split.participants.filter((person) =>
      person.settled_paise < person.share_paise && !person.repayment_transaction_id).length;
}

type EditPerson = { id?: string; name: string; amount: string; hasRepayment: boolean };

function EditSplitForm({ split, onCancel }: { split: Split; onCancel: () => void }) {
  const [updateSplit, { isLoading: saving }] = useUpdateSplitMutation();
  const [title, setTitle] = useState(split.title);
  const [ownerAmount, setOwnerAmount] = useState((split.owner_share_paise / 100).toFixed(2));
  const [people, setPeople] = useState<EditPerson[]>(() => split.participants.map((person) => ({
    id: person.id, name: person.name, amount: (person.share_paise / 100).toFixed(2),
    hasRepayment: person.repayment_transaction_id !== null || person.settled_paise > 0,
  })));
  const [showValidation, setShowValidation] = useState(false);
  const [error, setError] = useState('');
  const ownShare = paise(ownerAmount);
  const shares = people.map((person) => paise(person.amount));
  const allocatedPaise = (ownShare ?? 0) + shares.reduce<number>((sum, share) => sum + (share ?? 0), 0);
  const remainingPaise = split.total_paise - allocatedPaise;
  const invalidAmounts = ownShare === null || shares.some((share) => share === null || share <= 0) || remainingPaise !== 0;
  const names = people.map((person) => person.name.trim());
  const invalidNames = names.map((name, index) => !name ||
    names.some((other, row) => row !== index && other.toLowerCase() === name.toLowerCase()));

  function updatePerson(index: number, change: Partial<EditPerson>) {
    setPeople((current) => current.map((person, row) => row === index ? { ...person, ...change } : person));
    setError('');
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setShowValidation(true);
    setError('');
    if (!title.trim()) { setError('Enter a split title.'); return; }
    if (invalidNames.some(Boolean)) { setError('Enter a different name for each person.'); return; }
    if (invalidAmounts) { setError('Shares, including yours, must add up to the expense exactly.'); return; }
    try {
      await updateSplit({
        splitId: split.id,
        body: {
          title: title.trim(), owner_share_paise: ownShare!,
          participants: people.map((person, index) => ({
            ...(person.id ? { id: person.id } : {}), name: person.name.trim(), share_paise: shares[index]!,
          })),
        },
      }).unwrap();
      onCancel();
    } catch (failure) { setError(detail(failure)); }
  }

  return <form onSubmit={save} noValidate className='space-y-3 border-t border-[var(--bg-border)] pt-3'>
    <p className='text-xs text-[var(--text-muted)]'>Adjust unpaid shares before saving. Shares with linked repayments stay fixed.</p>
    <label className='block space-y-1 text-sm text-[var(--text-secondary)]'>Title
      <input className={`${inputClass} ${showValidation && !title.trim() ? 'border-red-400/70' : ''}`}
        maxLength={255} value={title} onChange={(event) => { setTitle(event.target.value); setError(''); }} />
    </label>
    <label className='block space-y-1 text-sm text-[var(--text-secondary)]'>Your share (₹)
      <input className={`${inputClass} ${showValidation && ownShare === null ? 'border-red-400/70' : ''}`}
        inputMode='decimal' aria-invalid={showValidation && ownShare === null}
        value={ownerAmount} onChange={(event) => { setOwnerAmount(event.target.value); setError(''); }} />
    </label>
    <div className='space-y-2'>
      <p className='text-sm text-[var(--text-secondary)]'>People who owe you</p>
      {people.map((person, index) => <div key={person.id ?? `new-${index}`}
        className='grid gap-2 rounded-lg border border-[var(--bg-border)] p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end'>
        <label className='block space-y-1 text-xs text-[var(--text-secondary)]'>Name
          <input className={`${inputClass} ${showValidation && invalidNames[index] ? 'border-red-400/70' : ''}`}
            maxLength={100} aria-invalid={showValidation && invalidNames[index]}
            value={person.name} onChange={(event) => updatePerson(index, { name: event.target.value })} />
        </label>
        <label className='block space-y-1 text-xs text-[var(--text-secondary)]'>Share (₹)
          <input className={`${inputClass} ${showValidation && (shares[index] === null || shares[index] <= 0) ? 'border-red-400/70' : ''}`}
            inputMode='decimal' disabled={person.hasRepayment}
            aria-invalid={showValidation && (shares[index] === null || shares[index] <= 0)}
            value={person.amount} onChange={(event) => updatePerson(index, { amount: event.target.value })} />
        </label>
        {person.hasRepayment ? <span className='text-xs text-[var(--text-muted)]'>Repayment linked</span> :
          <button type='button' disabled={people.length === 1}
            className='text-left text-xs text-[var(--text-muted)] disabled:opacity-50 sm:pb-3'
            onClick={() => { setPeople((current) => current.filter((_, row) => row !== index)); setError(''); }}>Remove</button>}
      </div>)}
      {people.length < 20 && <button type='button' className='text-sm text-[var(--brand-primary)]'
        onClick={() => {
          setPeople((current) => [...current, {
            name: '', amount: remainingPaise > 0 ? (remainingPaise / 100).toFixed(2) : '', hasRepayment: false,
          }]);
          setError('');
        }}>+ Add person</button>}
    </div>
    <div role='status' className='rounded-lg border border-[var(--bg-border)] p-3 text-sm text-[var(--text-secondary)]'>
      <p>Total: {formatPaiseAsInr(split.total_paise)}</p>
      <p>Allocated: {formatPaiseAsInr(allocatedPaise)}</p>
      <p className={`font-semibold ${invalidAmounts ? 'text-red-400' : ''}`}>Remaining: {formatPaiseAsInr(remainingPaise)}</p>
      {invalidAmounts && <p className='mt-1 text-xs text-red-400'>Enter valid shares that add up to the total.</p>}
    </div>
    {error && <p role='alert' className='text-sm text-red-400'>{error}</p>}
    <div className='grid grid-cols-1 gap-2 sm:grid-cols-2'><Button type='submit' isLoading={saving}>Save split</Button>
      <Button type='button' variant='secondary' onClick={onCancel}>Cancel</Button></div>
  </form>;
}

export function SplitsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const focusedSplitId = searchParams.get('splitId');
  const focusedPlanId = searchParams.get('planId');
  const { data: splits = [], isLoading } = useListSplitsQuery();
  const { data: settlementPlans = [], isLoading: loadingSettlementPlans,
    isError: settlementPlansError } = useListSettlementPlansQuery();
  const { data: transactions = [] } = useListTransactionsQuery();
  const { data: accounts = [] } = useListAccountsQuery();
  const { data: contacts = [] } = useListSplitContactsQuery();
  const [createSplit, { isLoading: creating }] = useCreateSplitMutation();
  const [createOwed, { isLoading: creatingOwed }] = useCreateOwedMutation();
  const [repay, { isLoading: repaying }] = useRepaySplitParticipantMutation();
  const [repaySettlementTransfer, { isLoading: repayingTransfer }] = useRepaySettlementTransferMutation();
  const [settlePlanTransfer] = useSettleSettlementPlanTransferMutation();
  const [deleteSplit, { isLoading: deleting }] = useDeleteSplitMutation();
  const [open, setOpen] = useState(location.pathname.endsWith('/new'));
  const [transactionId, setTransactionId] = useState(searchParams.get('transactionId') ?? '');
  const [title, setTitle] = useState('');
  const [titleManuallyEdited, setTitleManuallyEdited] = useState(false);
  const [mode, setMode] = useState<'equal' | 'custom'>('equal');
  const [ownerAmount, setOwnerAmount] = useState<string | null>(null);
  const [people, setPeople] = useState<Person[]>([newPerson()]);
  const [review, setReview] = useState<CreateSplitRequest | null>(null);
  const [error, setError] = useState('');
  const [showValidation, setShowValidation] = useState(false);
  const [repaymentAccounts, setRepaymentAccounts] = useState<Record<string, string>>({});
  const [settlementAccounts, setSettlementAccounts] = useState<Record<string, string>>({});
  const [settlingPlanTransferId, setSettlingPlanTransferId] = useState<string | null>(null);
  const [settlementFeedback, setSettlementFeedback] = useState<Record<string, string>>({});
  const [repayingAllSplitId, setRepayingAllSplitId] = useState<string | null>(null);
  const [editingSplitId, setEditingSplitId] = useState<string | null>(null);
  const [owedOpen, setOwedOpen] = useState(false);
  const [complexOpen, setComplexOpen] = useState(Boolean(searchParams.get('draft')));
  const [owedName, setOwedName] = useState('');
  const [owedAmount, setOwedAmount] = useState('');
  const [owedTitle, setOwedTitle] = useState('');
  const totalOwedPaise = splits.reduce((total, split) => total + split.outstanding_paise, 0);
  const expenseSplitOwedPaise = splits.filter((split) => split.kind === 'expense_split')
    .reduce((total, split) => total + split.outstanding_paise, 0);
  const standaloneOwedPaise = splits.filter((split) => split.kind === 'money_owed')
    .reduce((total, split) => total + split.outstanding_paise, 0);
  const orderedSplits = [...splits].sort((a, b) => Number(b.outstanding_paise > 0) - Number(a.outstanding_paise > 0));
  const activeAccounts = accounts.filter((account) => account.is_active);
  const defaultAccountId = activeAccounts.find((account) => account.is_default)?.id ?? activeAccounts[0]?.id ?? '';

  useEffect(() => {
    if (focusedSplitId && splits.some((split) => split.id === focusedSplitId)) {
      document.getElementById(`split-${focusedSplitId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [focusedSplitId, splits]);

  useEffect(() => {
    if (focusedPlanId && settlementPlans.some((plan) => plan.id === focusedPlanId)) {
      document.getElementById(`group-settlement-${focusedPlanId}`)?.scrollIntoView({
        behavior: 'smooth', block: 'center',
      });
    }
  }, [focusedPlanId, settlementPlans]);

  const expenses = useMemo(() => transactions.filter((transaction) =>
    transaction.type === 'expense' && !transaction.deleted_at &&
    !splits.some((split) => split.transaction_id === transaction.id) &&
    !settlementPlans.some((plan) => plan.transaction_ids.includes(transaction.id))),
  [transactions, splits, settlementPlans]);
  const expense = expenses.find((item) => item.id === transactionId);
  const expenseLabel = expense?.merchant || expense?.note || 'Expense';
  const recentExpenses = expenses.slice(0, 5);
  const selectedOlderExpense = expense && !recentExpenses.some((item) => item.id === expense.id);
  const displayedExpenses = selectedOlderExpense
    ? [expense, ...recentExpenses.slice(0, 4)] : recentExpenses;

  const displayedTitle = !titleManuallyEdited && expense ? expenseLabel : title;
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

  function finishNewPerson(index: number, name: string) {
    const trimmedName = name.trim();
    if (trimmedName) updatePerson(index, { name: trimmedName, isNew: false });
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
      transaction_id: expense.id, title: displayedTitle.trim() || expense.merchant || 'Shared expense',
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
      setOpen(false); setReview(null); setTransactionId(''); setTitle(''); setTitleManuallyEdited(false);
      setPeople([newPerson()]); setOwnerAmount(null); setShowValidation(false); setError(''); navigate('/splits');
    } catch (failure) { setError(detail(failure)); }
  }

  async function saveOwed(event: FormEvent) {
    event.preventDefault();
    setError('');
    const amount = paise(owedAmount);
    if (!owedName.trim() || amount === null || amount <= 0) {
      setError('Enter who owes you and a positive amount.');
      return;
    }
    try {
      await createOwed({ name: owedName.trim(), title: owedTitle.trim(), amount_paise: amount }).unwrap();
      setOwedName(''); setOwedAmount(''); setOwedTitle(''); setOwedOpen(false);
    } catch (failure) { setError(detail(failure)); }
  }

  async function markRepaid(splitId: string, participantId: string) {
    const accountId = repaymentAccounts[participantId] ?? defaultAccountId;
    if (!accountId) { setError('Choose the account that received the repayment.'); return; }
    setError('');
    try { await repay({ splitId, participantId, accountId }).unwrap(); }
    catch (failure) { setError(detail(failure)); }
  }

  async function markSettlementTransferRepaid(splitId: string, debtor: string) {
    const accountId = repaymentAccounts[`${splitId}:${debtor}`] ?? defaultAccountId;
    if (!accountId) { setError('Choose the account that received the repayment.'); return; }
    setError('');
    try { await repaySettlementTransfer({ splitId, debtor, accountId }).unwrap(); }
    catch (failure) { setError(detail(failure)); }
  }

  async function markAllRepaid(split: Split) {
    const targets = split.settlement_breakdown
      ? split.settlement_breakdown.transfers.filter((transfer) =>
        transfer.creditor.trim().toLowerCase() === 'you' && !transfer.repayment_transaction_id)
        .map((transfer) => ({ id: transfer.debtor, name: transfer.debtor,
          accountId: repaymentAccounts[`${split.id}:${transfer.debtor}`] ?? defaultAccountId,
          amountPaise: transfer.amount_paise }))
      : split.participants.filter((person) => person.settled_paise < person.share_paise && !person.repayment_transaction_id)
        .map((person) => ({ id: person.id, name: person.name,
          accountId: repaymentAccounts[person.id] ?? defaultAccountId,
          amountPaise: person.share_paise }));
    if (targets.length === 0) return;
    if (targets.some((target) => !activeAccounts.some((account) => account.id === target.accountId))) {
      setError('Choose an active receiving account for every unpaid person.');
      return;
    }
    const totalPaise = targets.reduce((total, target) => total + target.amountPaise, 0);
    if (!window.confirm(`Mark all ${targets.length} repayments for “${split.title}” as received (${formatPaiseAsInr(totalPaise)})? This records one income transaction per person in the selected accounts.`)) return;
    setError('');
    setRepayingAllSplitId(split.id);
    let completed = 0;
    try {
      for (const target of targets) {
        if (split.settlement_breakdown) {
          await repaySettlementTransfer({ splitId: split.id, debtor: target.id, accountId: target.accountId }).unwrap();
        } else {
          await repay({ splitId: split.id, participantId: target.id, accountId: target.accountId }).unwrap();
        }
        completed += 1;
      }
    } catch (failure) {
      setError(`${completed} of ${targets.length} repayments were recorded. ${detail(failure)} The remaining people are still unpaid.`);
    } finally {
      setRepayingAllSplitId(null);
    }
  }

  async function markPlanTransferSettled(planId: string, transfer: SettlementPlan['transfers'][number]) {
    const ownerInvolved = transfer.creditor === 'You' || transfer.debtor === 'You';
    const accountId = settlementAccounts[transfer.id] ?? defaultAccountId;
    if (ownerInvolved && !activeAccounts.some((account) => account.id === accountId)) {
      setSettlementFeedback((current) => ({ ...current, [transfer.id]: 'Choose the wallet account used for this repayment.' }));
      return;
    }
    setSettlementFeedback((current) => ({ ...current, [transfer.id]: '' }));
    setSettlingPlanTransferId(transfer.id);
    try {
      await settlePlanTransfer({ planId, transferId: transfer.id,
        accountId: ownerInvolved ? accountId : undefined }).unwrap();
      setSettlementFeedback((current) => ({ ...current, [transfer.id]: 'Repayment recorded.' }));
    } catch (failure) {
      setSettlementFeedback((current) => ({ ...current, [transfer.id]: detail(failure) }));
    } finally {
      setSettlingPlanTransferId(null);
    }
  }

  async function removeSplit(splitId: string) {
    if (!window.confirm('Remove this split? The original expense will stay in your transactions.')) return;
    setError('');
    try { await deleteSplit(splitId).unwrap(); }
    catch (failure) { setError(detail(failure)); }
  }

  return <div className='mx-auto w-full max-w-[900px] space-y-5 px-4 py-4 md:px-6 md:py-6'>
    <header>
      <h1 className='text-xl font-bold text-[var(--text-primary)]'>Splits</h1>
      <p className='text-sm text-[var(--text-muted)]'>Track expense shares and other money people owe you.</p>
    </header>
    <div className='min-w-0 space-y-4 rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4'>
      <div className='min-w-0' aria-live='polite'>
        <p className='text-xs text-[var(--text-muted)]'>Outstanding from regular splits and IOUs</p>
        <p className='break-words text-2xl font-bold text-[var(--positive)]'>{isLoading ? '…' : formatPaiseAsInr(totalOwedPaise)}</p>
        <p className='text-xs text-[var(--text-muted)]'>Expense shares {formatPaiseAsInr(expenseSplitOwedPaise)} · Other IOUs {formatPaiseAsInr(standaloneOwedPaise)}</p>
        <p className='mt-1 text-xs text-[var(--text-muted)]'>Group settlement plans are listed separately below and are not included in this total.</p>
      </div>
      <div className='grid min-w-0 grid-cols-1 gap-2 min-[480px]:grid-cols-2 md:grid-cols-3'>
        <Button className='min-w-0 whitespace-normal text-center text-sm' onClick={() => { setOpen(true); setReview(null); }}>Split an expense</Button>
        <Button variant='secondary' className='min-w-0 whitespace-normal text-center text-sm' onClick={() => setOwedOpen((value) => !value)}>Record money owed</Button>
        <Button variant='secondary' className='min-w-0 whitespace-normal text-center text-sm'
          onClick={() => setComplexOpen((value) => !value)}>Plan group settlement</Button>
      </div>
    </div>
    {error && <p role='alert' className='rounded-xl bg-red-500/10 p-3 text-sm text-red-300'>{error}</p>}
    <section className='space-y-3' aria-labelledby='group-settlements-heading'>
      <div>
        <h2 id='group-settlements-heading' className='font-semibold text-[var(--text-primary)]'>Group settlements</h2>
        <p className='text-xs text-[var(--text-muted)]'>Confirmed plans stay here. Only payments you made or received appear in Transactions.</p>
      </div>
      {loadingSettlementPlans ? <p className='text-sm text-[var(--text-muted)]'>Loading group settlements…</p>
        : settlementPlansError ? <p role='alert' className='text-sm text-red-400'>Could not load group settlements. Try refreshing this page.</p>
          : settlementPlans.length === 0 ? <Card className='p-4 text-sm text-[var(--text-muted)]'>
            No saved group settlements yet. Review a plan, then select “Save plan and wallet expenses” to add it here.
          </Card> : settlementPlans.map((plan) => {
            const incoming = plan.transfers.filter((transfer) => transfer.creditor === 'You');
            const dueToYou = incoming.reduce((total, transfer) => total + transfer.amount_paise, 0);
            const received = incoming.filter((transfer) => transfer.settled_at)
              .reduce((total, transfer) => total + transfer.amount_paise, 0);
            const remaining = dueToYou - received;
            const status = dueToYou === 0 ? 'No repayments due to you'
              : remaining === 0 ? 'Received in full'
                : received > 0 ? 'Partially received' : 'Awaiting repayments';
            return <Card key={plan.id} id={`group-settlement-${plan.id}`}
              className={`min-w-0 scroll-mt-6 space-y-3 p-4 ${focusedPlanId === plan.id ? 'ring-2 ring-[var(--brand-primary)]' : ''}`}>
              <div className='flex min-w-0 flex-col gap-1 sm:flex-row sm:items-start sm:justify-between'>
                <h3 className='min-w-0 break-words font-semibold text-[var(--text-primary)]'>{plan.title}</h3>
                <span className='text-xs font-semibold text-[var(--brand-primary)]'>{status}</span>
              </div>
              <div className='grid grid-cols-2 gap-2 text-sm sm:grid-cols-4'>
                <div className='min-w-0 rounded-lg bg-[var(--bg-elevated)] p-2'><p className='text-xs text-[var(--text-muted)]'>Total plan</p>
                  <p className='break-words font-semibold text-[var(--text-primary)]'>{formatPaiseAsInr(plan.total_paise)}</p></div>
                <div className='min-w-0 rounded-lg bg-[var(--bg-elevated)] p-2'><p className='text-xs text-[var(--text-muted)]'>Due to you</p>
                  <p className='break-words font-semibold text-[var(--text-primary)]'>{formatPaiseAsInr(dueToYou)}</p></div>
                <div className='min-w-0 rounded-lg bg-[var(--bg-elevated)] p-2'><p className='text-xs text-[var(--text-muted)]'>Received</p>
                  <p className='break-words font-semibold text-[var(--positive)]'>{formatPaiseAsInr(received)}</p></div>
                <div className='min-w-0 rounded-lg bg-[var(--bg-elevated)] p-2'><p className='text-xs text-[var(--text-muted)]'>Left to receive</p>
                  <p className='break-words font-semibold text-[var(--text-primary)]'>{formatPaiseAsInr(remaining)}</p></div>
              </div>
              <p className='text-xs text-[var(--text-muted)]'>Total plan includes all bills. Repayment amounts include only transfers payable to you.</p>
              <details className='rounded-lg border border-[var(--bg-border)] p-3'>
                <summary className='cursor-pointer text-sm font-semibold text-[var(--brand-primary)]'>Repayments</summary>
                <div className='mt-3 space-y-3'>
                  {plan.transfers.length === 0 ? <p className='text-xs text-[var(--text-muted)]'>No repayments are needed.</p> : <>
                    {[...plan.transfers].sort((a, b) => Number(Boolean(a.settled_at)) - Number(Boolean(b.settled_at)))
                      .map((transfer) => <div key={transfer.id} className='flex min-w-0 flex-col gap-2 border-t border-[var(--bg-border)] pt-2 text-xs sm:flex-row sm:items-center sm:justify-between'>
                        <span className='min-w-0 break-words text-[var(--text-primary)]'>{transfer.debtor} pays {transfer.creditor} · {formatPaiseAsInr(transfer.amount_paise)}</span>
                        <div className='flex flex-col items-start gap-1 sm:items-end'>
                          {transfer.settled_at ? <span className='text-[var(--positive)]'>Repaid</span> : <>
                            {(transfer.creditor === 'You' || transfer.debtor === 'You') &&
                              <label className='space-y-1 text-xs text-[var(--text-muted)]'>
                                {transfer.creditor === 'You' ? 'Received in' : 'Paid from'}
                                <select aria-label={`Account for repayment from ${transfer.debtor} to ${transfer.creditor}`}
                                  className='block w-full max-w-40 rounded-lg border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-1 text-xs text-[var(--text-primary)]'
                                  value={settlementAccounts[transfer.id] ?? defaultAccountId}
                                  onChange={(event) => setSettlementAccounts((current) => ({
                                    ...current, [transfer.id]: event.target.value,
                                  }))}>
                                  {activeAccounts.length === 0 && <option value=''>Choose account</option>}
                                  {activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                                </select>
                              </label>}
                            <button type='button' disabled={settlingPlanTransferId !== null ||
                              ((transfer.creditor === 'You' || transfer.debtor === 'You') &&
                                !(settlementAccounts[transfer.id] ?? defaultAccountId))}
                              className='rounded-lg bg-[var(--brand-primary)] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[var(--brand-hover)] disabled:opacity-50'
                              onClick={() => void markPlanTransferSettled(plan.id, transfer)}>
                              {settlingPlanTransferId === transfer.id ? 'Recording…' : 'Mark repaid'}
                            </button>
                          </>}
                          {settlementFeedback[transfer.id] && <p
                            role={settlementFeedback[transfer.id] === 'Repayment recorded.' ? 'status' : 'alert'}
                            className={`max-w-64 text-xs ${settlementFeedback[transfer.id] === 'Repayment recorded.'
                              ? 'text-[var(--positive)]' : 'text-red-400'}`}>
                            {settlementFeedback[transfer.id]}
                          </p>}
                        </div>
                      </div>)}
                  </>}
                </div>
              </details>
              {plan.transaction_ids.length > 0 && <div className='flex flex-wrap gap-2'>
                {plan.transaction_ids.map((id, index) => {
                  const transaction = transactions.find((item) => item.id === id);
                  return <button key={id} type='button'
                    className='max-w-full rounded-lg border border-[var(--bg-border)] px-3 py-2 text-left text-xs text-[var(--brand-primary)]'
                    onClick={() => navigate(`/transactions?transactionId=${id}`)}>
                    View {transaction?.merchant || `wallet expense ${index + 1}`}
                  </button>;
                })}
              </div>}
            </Card>;
          })}
    </section>
    {complexOpen && <ComplexSettlementPlanner />}
    {owedOpen && <Card className='space-y-3 p-5'>
      <div><h2 className='font-semibold text-[var(--text-primary)]'>Record money someone owes you</h2>
        <p className='text-xs text-[var(--text-muted)]'>For a loan, tickets, or another amount that is not tied to a recorded purchase.</p></div>
      <form onSubmit={saveOwed} className='grid gap-3 sm:grid-cols-2'>
        <label className='space-y-1 text-sm text-[var(--text-secondary)]'>Person
          {contacts.length > 0 && <ThemedSelect id='owed-person' value={contacts.includes(owedName) ? owedName : ''}
            placeholder='Choose a saved person' options={contacts.map((name) => ({ value: name, label: name }))}
            onChange={setOwedName} />}
          <input className={inputClass} maxLength={100} value={owedName} placeholder='Name (e.g. Isha)'
            onChange={(event) => setOwedName(event.target.value)} />
        </label>
        <label className='space-y-1 text-sm text-[var(--text-secondary)]'>Amount (₹)
          <input className={inputClass} inputMode='decimal' value={owedAmount} placeholder='500.00'
            onChange={(event) => setOwedAmount(event.target.value)} />
        </label>
        <label className='space-y-1 text-sm text-[var(--text-secondary)] sm:col-span-2'>Reason
          <input className={inputClass} maxLength={255} value={owedTitle} placeholder='Tickets I paid for'
            onChange={(event) => setOwedTitle(event.target.value)} />
        </label>
        <div className='grid grid-cols-1 gap-2 sm:col-span-2 sm:grid-cols-2'><Button type='submit' isLoading={creatingOwed}>Save amount owed</Button>
          <Button type='button' variant='secondary' onClick={() => setOwedOpen(false)}>Cancel</Button></div>
      </form>
    </Card>}
    {open && <Card className='space-y-4 p-5'>
      <h2 className='font-semibold text-[var(--text-primary)]'>
        {expense ? `Create a split for ${expenseLabel}` : 'Share a recorded expense'}
      </h2>
      <p className='text-xs text-[var(--text-muted)]'>The purchase is already in your account. Mark each person repaid when their share reaches you.</p>
      {expense && <div className='rounded-lg border border-[var(--brand-primary)]/25 bg-[var(--brand-subtle)] px-3 py-2 text-sm text-[var(--text-primary)]'>
        <span className='font-medium'>Splitting:</span> {expenseLabel} · {formatPaiseAsInr(expense.amount_paise)}
      </div>}
      <form onSubmit={prepare} noValidate className='space-y-4'>
        <div className='space-y-1 text-sm text-[var(--text-secondary)]'>
          <label htmlFor='split-expense'>Expense</label>
          <ThemedSelect id='split-expense' value={transactionId}
            placeholder={expenses.length ? 'Choose an expense' : 'No unshared expense transactions'}
            invalid={showValidation && !expense}
            options={displayedExpenses.map((item) => ({
              value: item.id,
              label: `${item.merchant || item.note || 'Expense'} · ${formatPaiseAsInr(item.amount_paise)} · ${new Date(item.occurred_at).toLocaleDateString()}`,
            }))}
            onChange={(value) => { setTransactionId(value); setTitle(''); setTitleManuallyEdited(false); setReview(null); setError(''); }} />
        </div>
        {expenses.length > 0 && <p className='text-xs text-[var(--text-muted)]'>{selectedOlderExpense ? 'Showing the selected expense and up to 4 recent expenses.' : 'Showing up to 5 recent expenses.'} To see more, <button type='button' className='text-[var(--brand-primary)] hover:underline' onClick={() => navigate('/transactions')}>go to Transactions</button> and select an expense to split.</p>}
        {expenses.length === 0 && <p className='text-sm text-[var(--text-muted)]'>There are no unshared expenses to split. You can still use “Record money owed” above for an IOU without a transaction.</p>}
        <label className='block space-y-1 text-sm text-[var(--text-secondary)]'>Title
          <input className={inputClass} maxLength={255} value={displayedTitle} onChange={(event) => { setTitle(event.target.value); setTitleManuallyEdited(true); setReview(null); }} placeholder='Dinner with friends' />
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
                      { value: NEW_PERSON, label: person.isNew && person.name ? person.name : '+ Add new person' },
                      ...(!person.isNew && person.name && !contacts.some((contact) => contact.toLowerCase() === person.name.toLowerCase())
                        ? [{ value: person.name, label: person.name }]
                        : []),
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
                onChange={(event) => updatePerson(index, { name: event.target.value })}
                onBlur={(event) => finishNewPerson(index, event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    finishNewPerson(index, event.currentTarget.value);
                    event.currentTarget.blur();
                  }
                }} />}
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
        <div className='grid grid-cols-1 gap-2 sm:grid-cols-2'><Button type='submit' disabled={!expense}>Review expense split</Button>
          <Button type='button' variant='secondary' onClick={() => { setOpen(false); setReview(null); navigate('/splits'); }}>Cancel</Button></div>
      </form>
      {review && <div className='space-y-2 rounded-xl border border-[var(--bg-border)] p-4 text-sm text-[var(--text-primary)]'>
        <h3 className='font-semibold'>Confirm {review.title}</h3>
        <p>Total {formatPaiseAsInr(review.amount_paise)} · Your share {formatPaiseAsInr(review.owner_share_paise ?? 0)}</p>
        {review.participants.map((person) => <p key={person.name}>{person.name}: {formatPaiseAsInr(person.share_paise)}</p>)}
        <Button isLoading={creating} onClick={confirm}>Create split</Button>
      </div>}
    </Card>}
    <section className='space-y-3'><h2 className='font-semibold text-[var(--text-primary)]'>Your split and IOU tracker</h2>
      {isLoading ? <p className='text-sm text-[var(--text-muted)]'>Loading splits…</p> : splits.length === 0 ?
        <Card className='p-5 text-sm text-[var(--text-muted)]'>No splits yet.</Card> : orderedSplits.map((split) =>
          <Card key={split.id} id={`split-${split.id}`}
            className={`scroll-mt-6 space-y-3 p-5 ${focusedSplitId === split.id ? 'ring-2 ring-[var(--brand-primary)]' : ''}`}>
            <div className='flex min-w-0 flex-col gap-3 sm:flex-row sm:justify-between'><div className='min-w-0'><h3 className='break-words font-semibold text-[var(--text-primary)]'>{split.title}</h3>
              <span className='mb-1 inline-flex rounded-full bg-[var(--brand-subtle)] px-2 py-0.5 text-[10px] font-semibold text-[var(--brand-primary)]'>
                {split.kind === 'money_owed' ? 'Money owed to you' : 'Expense split'}
              </span>
              <p className='text-xs text-[var(--text-muted)]'>Total {formatPaiseAsInr(split.total_paise)}{split.kind === 'expense_split' ? ` · Your share ${formatPaiseAsInr(split.owner_share_paise)}` : ''}</p></div>
              <div className='min-w-0 text-left sm:text-right'><span className='break-words text-sm font-semibold text-[var(--text-primary)]'>{formatPaiseAsInr(split.outstanding_paise)} {split.settlement_breakdown ? 'due to you' : 'due'}</span>
                <div className='flex flex-wrap gap-2 sm:justify-end'>
                  {split.transaction_id && <button type='button' className='rounded-lg border border-[var(--bg-border)] px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:border-[var(--brand-primary)] hover:bg-[var(--brand-subtle)] hover:text-[var(--brand-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)] focus-visible:ring-offset-2'
                    onClick={() => navigate(`/transactions?transactionId=${split.transaction_id}`)}>View transaction</button>}
                  {split.kind === 'expense_split' && <button type='button' className='rounded-lg border border-[var(--brand-primary)]/30 bg-[var(--brand-subtle)] px-3 py-1.5 text-xs font-semibold text-[var(--brand-primary)] transition-colors hover:border-[var(--brand-primary)] hover:bg-[var(--brand-primary)] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)] focus-visible:ring-offset-2'
                    onClick={() => setEditingSplitId(editingSplitId === split.id ? null : split.id)}>
                    {editingSplitId === split.id ? 'Close edit' : 'Edit split'}
                  </button>}
                  {unpaidCount(split) > 1 && <button type='button'
                    className='max-w-full rounded-lg border border-[var(--brand-primary)]/30 bg-[var(--brand-subtle)] px-3 py-1.5 text-center text-xs font-semibold whitespace-normal text-[var(--brand-primary)] disabled:opacity-50'
                    disabled={repayingAllSplitId !== null || repaying || repayingTransfer || activeAccounts.length === 0}
                    onClick={() => void markAllRepaid(split)}>
                    {repayingAllSplitId === split.id ? 'Recording repayments…' : 'Mark all as repaid'}
                  </button>}
                  <button type='button' className='text-xs text-[var(--text-muted)]' disabled={deleting}
                    onClick={() => removeSplit(split.id)}>Remove split</button>
                </div></div></div>
            {editingSplitId === split.id ? <EditSplitForm key={split.id} split={split} onCancel={() => setEditingSplitId(null)} /> : <>
            {split.item_breakdown && <details className='border-t border-[var(--bg-border)] pt-2 text-xs text-[var(--text-secondary)]'>
              <summary className='cursor-pointer text-[var(--brand-primary)]'>View item breakdown</summary>
              <ul className='mt-2 space-y-2'>
                {split.item_breakdown.map((item, index) => <li key={`${item.name}-${index}`}>
                  <span className='font-medium text-[var(--text-primary)]'>{item.name} · {formatPaiseAsInr(item.amount_paise)}</span>
                  <span className='block'>{item.allocations.map((share) =>
                    `${share.person === 'me' ? 'You' : share.person} ${formatPaiseAsInr(share.amount_paise)}`).join(', ')}</span>
                </li>)}
              </ul>
            </details>}
            {split.settlement_breakdown && <details className='border-t border-[var(--bg-border)] pt-2 text-xs text-[var(--text-secondary)]'>
              <summary className='cursor-pointer text-[var(--brand-primary)]'>View settlement plan</summary>
              {split.settlement_breakdown.quantity_allocations.length > 0 && <p className='mt-2'>Priced items: {formatPaiseAsInr(split.settlement_breakdown.priced_items_paise)} · Remaining bill split equally: {formatPaiseAsInr(split.settlement_breakdown.remainder_paise)}</p>}
              {split.settlement_breakdown.quantity_allocations.length > 0 && <ul className='mt-2 space-y-1'>
                {split.settlement_breakdown.quantity_allocations.map((allocation, index) => <li key={`${allocation.item_name}-${index}`}>
                  {allocation.item_name}: {allocation.quantity_per_person} × {formatPaiseAsInr(allocation.unit_price_paise)} each for {allocation.people.join(', ')}
                </li>)}
              </ul>}
              {split.settlement_breakdown.contributions.length > 0 && <p className='mt-2'>Already contributed: {split.settlement_breakdown.contributions.map((entry) =>
                `${entry.person} ${formatPaiseAsInr(entry.amount_paise)}`).join(', ')}</p>}
              {split.settlement_breakdown.debts.length > 0 && <p className='mt-1'>Included debts: {split.settlement_breakdown.debts.map((entry) =>
                `${entry.debtor} owes ${entry.creditor} ${formatPaiseAsInr(entry.amount_paise)}`).join('; ')}</p>}
              <ul className='mt-2 space-y-1'>
                {split.settlement_breakdown.transfers.length === 0 ? <li>No transfers needed.</li> :
                  split.settlement_breakdown.transfers.map((transfer, index) => <li key={`${transfer.debtor}-${transfer.creditor}-${index}`}>
                    {transfer.debtor} pays {transfer.creditor} {formatPaiseAsInr(transfer.amount_paise)}
                  </li>)}
              </ul>
            </details>}
            {split.settlement_breakdown ? (split.settlement_breakdown.transfers.filter((transfer) =>
              transfer.creditor.trim().toLocaleLowerCase() === 'you').length > 0 ?
              split.settlement_breakdown.transfers.filter((transfer) =>
                transfer.creditor.trim().toLocaleLowerCase() === 'you')
                .sort((a, b) => Number(Boolean(a.repayment_transaction_id)) - Number(Boolean(b.repayment_transaction_id)))
                .map((transfer, index) =>
                <div key={`${transfer.debtor}-${index}`} className='flex min-w-0 flex-col gap-3 border-t border-[var(--bg-border)] pt-2 text-sm sm:flex-row sm:items-center sm:justify-between'>
                  <span className='min-w-0 break-words text-[var(--text-primary)]'>{transfer.debtor} · {formatPaiseAsInr(transfer.amount_paise)} {transfer.repayment_transaction_id ? 'repaid' : 'due to you'}</span>
                  {transfer.repayment_transaction_id ? <div className='flex flex-col items-end gap-1'>
                    <span className='text-xs text-green-400'>Repaid</span>
                    <button type='button' className='text-xs text-[var(--brand-primary)]'
                      onClick={() => navigate(`/transactions?transactionId=${transfer.repayment_transaction_id}`)}>View repayment</button>
                  </div> : <div className='flex flex-col items-end gap-1'>
                    <label className='space-y-1 text-xs text-[var(--text-muted)]'>Received in
                      <select aria-label={`Account receiving repayment from ${transfer.debtor}`}
                        className='block w-full max-w-40 rounded-lg border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-1 text-xs text-[var(--text-primary)]'
                        value={repaymentAccounts[`${split.id}:${transfer.debtor}`] ?? defaultAccountId}
                        onChange={(event) => setRepaymentAccounts((current) => ({
                          ...current, [`${split.id}:${transfer.debtor}`]: event.target.value,
                        }))}>
                        {activeAccounts.length === 0 && <option value=''>Choose account</option>}
                        {activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                      </select>
                    </label>
                    <button type='button' disabled={repayingTransfer || repayingAllSplitId !== null ||
                      !(repaymentAccounts[`${split.id}:${transfer.debtor}`] ?? defaultAccountId)}
                      className='rounded-lg bg-[var(--brand-primary)] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[var(--brand-hover)] disabled:opacity-50'
                      onClick={() => markSettlementTransferRepaid(split.id, transfer.debtor)}>Mark repaid</button>
                  </div>}
                </div>) : <p className='border-t border-[var(--bg-border)] pt-2 text-xs text-[var(--text-muted)]'>No settlement amount is due to you.</p>) :
            [...split.participants].sort((a, b) =>
              Number(a.settled_paise >= a.share_paise) - Number(b.settled_paise >= b.share_paise))
              .map((person) => <div key={person.id} className='flex min-w-0 flex-col gap-3 border-t border-[var(--bg-border)] pt-2 text-sm sm:flex-row sm:items-center sm:justify-between'>
              <span className='min-w-0 break-words text-[var(--text-primary)]'>{person.name} · {formatPaiseAsInr(person.share_paise)}</span>
              {!split.settlement_breakdown && (person.settled_paise === person.share_paise ? <div className='flex flex-col items-end gap-1'>
                <span className='text-green-400'>Repaid</span>
                {person.repayment_transaction_id && <button type='button' className='text-xs text-[var(--brand-primary)]'
                  onClick={() => navigate(`/transactions?transactionId=${person.repayment_transaction_id}`)}>View repayment</button>}
              </div> :
                <div className='flex flex-col items-end gap-1'>
                  <label className='space-y-1 text-xs text-[var(--text-muted)]'>Received in
                    <select aria-label={`Account receiving repayment from ${person.name}`}
                      className='block w-full max-w-40 rounded-lg border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-1 text-xs text-[var(--text-primary)]'
                      value={repaymentAccounts[person.id] ?? defaultAccountId}
                      onChange={(event) => setRepaymentAccounts((current) => ({ ...current, [person.id]: event.target.value }))}>
                      {activeAccounts.length === 0 && <option value=''>Choose account</option>}
                      {activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                    </select>
                  </label>
                  <button type='button' disabled={repaying || repayingAllSplitId !== null ||
                    !(repaymentAccounts[person.id] ?? defaultAccountId)}
                    className='rounded-lg bg-[var(--brand-primary)] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[var(--brand-hover)] disabled:opacity-50'
                    onClick={() => markRepaid(split.id, person.id)}>Mark repaid</button>
                </div>)}
            </div>)}
            {!split.settlement_breakdown && split.outstanding_paise > 0 && <p className='text-xs text-[var(--text-muted)]'>Mark repaid records a Split repayment income transaction in the selected account.</p>}
            </>}
          </Card>)}
    </section>
  </div>;
}
