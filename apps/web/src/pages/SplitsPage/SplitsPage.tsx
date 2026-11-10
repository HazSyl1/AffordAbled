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
  useRecordSplitPaymentMutation,
  useDeleteSplitMutation, useUpdateSplitMutation,
  useListPersonSplitBalancesQuery, useSettlePersonSplitBalanceMutation,
  useListSplitContactDetailsQuery, useSetSplitContactDetailsMutation, useDeleteSplitContactDetailsMutation,
  useListSplitNotificationStatusesQuery,
  type CreateSplitRequest, type PersonSplitBalance, type Split,
} from '../../features/splits/splitsApi';
import { useListSettlementPlansQuery, useSettleSettlementPlanTransferMutation,
  type SettlementPlan } from '../../features/splits/settlementPlansApi';
import { useListTransactionsQuery } from '../../features/transactions/transactionsApi';
import { formatPaiseAsInr } from '../../lib/money';
import { ComplexSettlementPlanner } from './ComplexSettlementPlanner';
import { NotificationConfirmDialog } from './NotificationConfirmDialog';
import { BalanceEmailButton } from './BalanceEmailButton';

type Person = { name: string; amount: string | null; isNew: boolean };
type ManagedPerson = {
  id: string;
  contactId: string | null;
  name: string;
  phone_e164: string | null;
  email: string | null;
};
const NEW_PERSON = '__new_person__';
const NEW_OWED_PERSON = '__new_owed_person__';
const newPerson = (): Person => ({ name: '', amount: null, isNew: false });
const inputClass = 'min-w-0 w-full rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] px-3 py-2 text-[var(--text-primary)]';

function paise(value: string): number | null {
  return /^\d+(?:\.\d{1,2})?$/.test(value.trim()) ? Math.round(Number(value) * 100) : null;
}

function detail(error: unknown): string {
  if (typeof error === 'object' && error !== null) {
    if ('data' in error) {
      const data = (error as { data?: { detail?: string | { message?: string } } }).data;
      if (typeof data?.detail === 'string') return data.detail;
      if (typeof data?.detail === 'object' && data.detail?.message) return data.detail.message;
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
      transfer.creditor.trim().toLowerCase() === 'you' && !transfer.repayment_transaction_id &&
      transfer.amount_paise > (transfer.settled_paise ?? 0)).length
    : split.participants.filter((person) =>
      person.settled_paise < person.share_paise && !person.repayment_transaction_id).length;
}

type EditPerson = { id?: string; name: string; amount: string; hasRepayment: boolean; contactId?: string };

function EditSplitForm({ split, onCancel, proposedTotalPaise }: {
  split: Split; onCancel: () => void; proposedTotalPaise?: number;
}) {
  const [updateSplit, { isLoading: saving }] = useUpdateSplitMutation();
  const [title, setTitle] = useState(split.title);
  const [totalAmount, setTotalAmount] = useState(((proposedTotalPaise ?? split.total_paise) / 100).toFixed(2));
  const [ownerAmount, setOwnerAmount] = useState((split.owner_share_paise / 100).toFixed(2));
  const [people, setPeople] = useState<EditPerson[]>(() => split.participants.map((person) => ({
    id: person.id, name: person.name, amount: (person.share_paise / 100).toFixed(2),
    hasRepayment: person.repayment_transaction_id !== null || person.settled_paise > 0,
    contactId: person.contact_id ?? undefined,
  })));
  const [showValidation, setShowValidation] = useState(false);
  const [error, setError] = useState('');
  const ownShare = paise(ownerAmount);
  const targetTotalPaise = paise(totalAmount);
  const shares = people.map((person) => paise(person.amount));
  const allocatedPaise = (ownShare ?? 0) + shares.reduce<number>((sum, share) => sum + (share ?? 0), 0);
  const remainingPaise = (targetTotalPaise ?? 0) - allocatedPaise;
  const invalidAmounts = targetTotalPaise === null || ownShare === null ||
    shares.some((share) => share === null || share <= 0) || remainingPaise !== 0;
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
          ...(targetTotalPaise !== split.total_paise ? { transaction_amount_paise: targetTotalPaise! } : {}),
          participants: people.map((person, index) => ({
            ...(person.id ? { id: person.id } : {}), name: person.name.trim(), share_paise: shares[index]!,
            ...(person.contactId ? { contact_id: person.contactId } : {}),
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
    <label className='block space-y-1 text-sm text-[var(--text-secondary)]'>Expense total (₹)
      <input className={`${inputClass} ${showValidation && targetTotalPaise === null ? 'border-red-400/70' : ''}`}
        inputMode='decimal' aria-invalid={showValidation && targetTotalPaise === null}
        value={totalAmount} onChange={(event) => { setTotalAmount(event.target.value); setError(''); }} />
      <span className='block text-xs text-[var(--text-muted)]'>Changing this also updates the linked expense and account balance.</span>
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
      <p>Total: {targetTotalPaise === null ? 'Enter a valid total' : formatPaiseAsInr(targetTotalPaise)}</p>
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
  const { data: personBalances = [], isLoading: loadingPersonBalances } = useListPersonSplitBalancesQuery();
  const { data: settlementPlans = [], isLoading: loadingSettlementPlans,
    isError: settlementPlansError } = useListSettlementPlansQuery();
  const { data: transactions = [] } = useListTransactionsQuery();
  const { data: accounts = [] } = useListAccountsQuery();
  const { data: contacts = [] } = useListSplitContactsQuery();
  const { data: contactDetails = [] } = useListSplitContactDetailsQuery();
  const { data: notificationStatuses = {} } = useListSplitNotificationStatusesQuery();
  const [setContactDetails, { isLoading: savingContact }] = useSetSplitContactDetailsMutation();
  const [deleteContactDetails, { isLoading: deletingContact }] = useDeleteSplitContactDetailsMutation();
  const [createSplit, { isLoading: creating }] = useCreateSplitMutation();
  const [createOwed, { isLoading: creatingOwed }] = useCreateOwedMutation();
  const [repay, { isLoading: repaying }] = useRepaySplitParticipantMutation();
  const [recordSplitPayment, { isLoading: recordingSplitPayment }] = useRecordSplitPaymentMutation();
  const [settlePersonBalance, { isLoading: settlingPersonBalance }] = useSettlePersonSplitBalanceMutation();
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
  const [paymentAmounts, setPaymentAmounts] = useState<Record<string, string>>({});
  const [partialPaymentOpen, setPartialPaymentOpen] = useState<Record<string, boolean>>({});
  const [settlementAccounts, setSettlementAccounts] = useState<Record<string, string>>({});
  const [settlingPlanTransferId, setSettlingPlanTransferId] = useState<string | null>(null);
  const [settlementFeedback, setSettlementFeedback] = useState<Record<string, string>>({});
  const [repayingAllSplitId, setRepayingAllSplitId] = useState<string | null>(null);
  const [editingSplitId, setEditingSplitId] = useState<string | null>(
    searchParams.get('edit') === '1' ? focusedSplitId : null,
  );
  const [balancesOpen, setBalancesOpen] = useState(false);
  const [settlementsOpen, setSettlementsOpen] = useState(Boolean(focusedPlanId));
  const [owedOpen, setOwedOpen] = useState(false);
  const [complexOpen, setComplexOpen] = useState(Boolean(searchParams.get('draft')));
  const [owedName, setOwedName] = useState('');
  const [addingOwedPerson, setAddingOwedPerson] = useState(false);
  const [owedAmount, setOwedAmount] = useState('');
  const [owedTitle, setOwedTitle] = useState('');
  const [owedDirection, setOwedDirection] = useState<'to_you' | 'by_you'>('to_you');
  const [balanceReview, setBalanceReview] = useState<PersonSplitBalance | null>(null);
  const [balanceSettlementAmount, setBalanceSettlementAmount] = useState('');
  const [balanceSettlementAccountId, setBalanceSettlementAccountId] = useState('');
  const [managePeopleOpen, setManagePeopleOpen] = useState(false);
  const [contactName, setContactName] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [contactSearch, setContactSearch] = useState('');
  const [contactFormOpen, setContactFormOpen] = useState(false);
  const [editingContactId, setEditingContactId] = useState<string | null>(null);
  const [editingContactKey, setEditingContactKey] = useState<string | null>(null);
  const [contactPendingRemoval, setContactPendingRemoval] = useState<ManagedPerson | null>(null);
  const [removeContactError, setRemoveContactError] = useState('');
  const [contactFeedback, setContactFeedback] = useState('');
  const [notificationQueue, setNotificationQueue] = useState<{ split: Split; participantIds?: string[] }[]>([]);
  const [notificationFeedback, setNotificationFeedback] = useState('');
  const expenseSplitOwedPaise = splits.filter((split) => split.kind === 'expense_split')
    .reduce((total, split) => total + split.outstanding_paise, 0);
  const standaloneOwedPaise = splits.filter((split) => split.kind === 'money_owed' && split.direction === 'to_you')
    .reduce((total, split) => total + split.outstanding_paise, 0);
  const payableOwedPaise = splits.filter((split) => split.kind === 'money_owed' && split.direction === 'by_you')
    .reduce((total, split) => total + split.outstanding_paise, 0);
  const totalOwedPaise = expenseSplitOwedPaise + standaloneOwedPaise;
  const orderedSplits = [...splits].sort((a, b) => Number(b.outstanding_paise > 0) - Number(a.outstanding_paise > 0));
  const activeAccounts = accounts.filter((account) => account.is_active);
  const defaultAccountId = activeAccounts.find((account) => account.is_default)?.id ?? activeAccounts[0]?.id ?? '';
  const contactForName = (name: string) => contactDetails.find((contact) =>
    contact.name.trim().toLowerCase() === name.trim().toLowerCase());
  const managedPeople = useMemo<ManagedPerson[]>(() => {
    const people = new Map<string, ManagedPerson>();
    contactDetails.forEach((contact) => people.set(contact.name.trim().toLowerCase(), {
      id: contact.id, contactId: contact.id, name: contact.name,
      phone_e164: contact.phone_e164, email: contact.email,
    }));
    splits.forEach((split) => split.participants.forEach((participant) => {
      const key = participant.name.trim().toLowerCase();
      if (!key || people.has(key)) return;
      people.set(key, {
        id: `existing-${key}`, contactId: participant.contact_id, name: participant.name,
        phone_e164: null, email: null,
      });
    }));
    return [...people.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [contactDetails, splits]);
  const filteredContactDetails = managedPeople.filter((contact) => {
    const query = contactSearch.trim().toLowerCase();
    return !query || [contact.name, contact.email ?? '', contact.phone_e164 ?? '']
      .some((value) => value.toLowerCase().includes(query));
  });

  const resetContactForm = () => {
    setEditingContactId(null);
    setEditingContactKey(null);
    setContactName('');
    setContactPhone('');
    setContactEmail('');
    setContactFormOpen(false);
  };

  const editContact = (contact: ManagedPerson) => {
    setEditingContactId(contact.contactId);
    setEditingContactKey(contact.id);
    setContactName(contact.name);
    setContactPhone(contact.phone_e164 ?? '');
    setContactEmail(contact.email ?? '');
    setContactFeedback('');
    setContactFormOpen(true);
  };

  const removeContact = async (contact: ManagedPerson) => {
    if (!contact.contactId) {
      editContact(contact);
      return;
    }
    setContactPendingRemoval(contact);
    setRemoveContactError('');
  };

  const confirmRemoveContact = async () => {
    if (!contactPendingRemoval?.contactId) return;
    try {
      await deleteContactDetails(contactPendingRemoval.contactId).unwrap();
      if (editingContactId === contactPendingRemoval.contactId) resetContactForm();
      setContactPendingRemoval(null);
      setContactFeedback(`${contactPendingRemoval.name} removed from saved people.`);
    } catch (failure) { setRemoveContactError(detail(failure)); }
  };

  const saveContact = async (event: FormEvent) => {
    event.preventDefault();
    setContactFeedback('');
    if (!contactName.trim()) { setContactFeedback('Enter the person’s name.'); return; }
    if (contactPhone.trim() && !/^\+[1-9]\d{7,14}$/.test(contactPhone.trim())) {
      setContactFeedback('Use international format, such as +919876543210.');
      return;
    }
    try {
      await setContactDetails({
        ...(editingContactId ? { contact_id: editingContactId } : {}),
        name: contactName.trim(), phone_e164: contactPhone.trim() || null,
        email: contactEmail.trim().toLowerCase() || null,
      }).unwrap();
      setContactFeedback(editingContactId ? 'Person updated.' : 'Person added.');
      resetContactForm();
    } catch (failure) { setContactFeedback(detail(failure)); }
  };
  const contactEditor = (inline: boolean) => <form onSubmit={(event) => { void saveContact(event); }}
    className={`grid gap-3 rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-4 sm:grid-cols-2 ${inline ? 'mt-4' : ''}`}>
    <h3 className='font-medium text-[var(--text-primary)] sm:col-span-2'>
      {editingContactId ? 'Edit person' : 'Add person details'}
    </h3>
    <label className='space-y-1 text-sm text-[var(--text-secondary)]'>Name
      <input className={inputClass} value={contactName} maxLength={100} list='split-contact-names' required
        onChange={(event) => { setContactName(event.target.value); setContactFeedback(''); }} />
      <datalist id='split-contact-names'>{contacts.map((name) => <option key={name} value={name} />)}</datalist>
    </label>
    <label className='space-y-1 text-sm text-[var(--text-secondary)]'>Email address
      <input className={inputClass} value={contactEmail} maxLength={320} type='email'
        placeholder='person@example.com'
        onChange={(event) => { setContactEmail(event.target.value); setContactFeedback(''); }} />
    </label>
    <label className='space-y-1 text-sm text-[var(--text-secondary)] sm:col-span-2'>Phone number (optional)
      <input className={inputClass} value={contactPhone} maxLength={20} inputMode='tel'
        placeholder='+919876543210'
        onChange={(event) => { setContactPhone(event.target.value); setContactFeedback(''); }} />
    </label>
    <div className='flex flex-wrap gap-2 sm:col-span-2'>
      <Button type='submit' isLoading={savingContact}>{editingContactId ? 'Save changes' : 'Save details'}</Button>
      <Button type='button' variant='secondary' disabled={savingContact} onClick={resetContactForm}>Cancel</Button>
    </div>
  </form>;
  const confirmBalanceSettlement = async () => {
    if (!balanceReview) return;
    const netPaise = balanceReview.net_paise;
    const fullCashAmount = Math.abs(netPaise);
    let amountPaise: number | undefined;
    if (fullCashAmount > 0) {
      const parsedAmount = paise(balanceSettlementAmount);
      if (parsedAmount === null || parsedAmount <= 100 || parsedAmount > fullCashAmount) {
        setError(`Enter an amount greater than ₹1.00 and no more than ${formatPaiseAsInr(fullCashAmount)}.`);
        return;
      }
      amountPaise = parsedAmount;
    }
    if ((amountPaise ?? 0) > 0 && !activeAccounts.some((account) => account.id === balanceSettlementAccountId)) {
      setError('Add or activate a wallet account before recording the cash settlement.');
      return;
    }
    setError('');
    try {
      await settlePersonBalance({
        person_name: balanceReview.person,
        expected_owed_to_you_paise: balanceReview.owed_to_you_paise,
        expected_you_owe_paise: balanceReview.you_owe_paise,
        ...(amountPaise === undefined ? {} : { amount_paise: amountPaise }),
        ...((amountPaise ?? 0) > 0 ? { account_id: balanceSettlementAccountId } : {}),
      }).unwrap();
      setBalanceReview(null);
      setBalanceSettlementAmount('');
      setBalanceSettlementAccountId('');
    } catch (failure) {
      setError(detail(failure));
    }
  };

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
        ...(contactForName(person.name)?.id ? { contact_id: contactForName(person.name)!.id } : {}),
      })),
    });
  }

  async function confirm() {
    if (!review) return;
    try {
      const created = await createSplit(review).unwrap();
      if (created.participants.some((participant) => participant.share_paise > participant.settled_paise)) {
        setNotificationQueue([{ split: created }]);
      }
      setOpen(false); setReview(null); setTransactionId(''); setTitle(''); setTitleManuallyEdited(false);
      setPeople([newPerson()]); setOwnerAmount(null); setShowValidation(false); setError(''); navigate('/splits');
    } catch (failure) { setError(detail(failure)); }
  }

  async function saveOwed(event: FormEvent) {
    event.preventDefault();
    setError('');
    const amount = paise(owedAmount);
    if (!owedName.trim() || amount === null || amount <= 0) {
      setError(`Enter ${owedDirection === 'to_you' ? 'who owes you' : 'who you owe'} and a positive amount.`);
      return;
    }
    try {
      const contact = contactForName(owedName);
      const created = await createOwed({
        name: owedName.trim(), title: owedTitle.trim(), amount_paise: amount, direction: owedDirection,
        ...(contact?.id ? { contact_id: contact.id } : {}),
      }).unwrap();
      if (owedDirection === 'to_you' && created.participants[0]) {
        setNotificationQueue([{ split: created }]);
      }
      setOwedName(''); setAddingOwedPerson(false); setOwedAmount(''); setOwedTitle('');
      setOwedDirection('to_you'); setOwedOpen(false);
    } catch (failure) { setError(detail(failure)); }
  }

  async function recordParticipantPayment(split: Split, person: Split['participants'][number], amountInput?: string) {
    const accountId = repaymentAccounts[person.id] ?? defaultAccountId;
    if (!accountId) { setError(split.direction === 'by_you' ? 'Choose the account you will pay from.' : 'Choose the account that received the repayment.'); return; }
    const remaining = Math.max(0, person.share_paise - person.settled_paise);
    let amountPaise: number | undefined;
    if (amountInput !== undefined) {
      const parsed = paise(amountInput);
      if (parsed === null || parsed <= 100) { setError('Enter a payment greater than ₹1.00.'); return; }
      if (parsed > remaining) { setError(`Payment cannot be more than the remaining ${formatPaiseAsInr(remaining)}.`); return; }
      amountPaise = parsed;
    }
    setError('');
    try {
      await recordSplitPayment({ splitId: split.id, participantId: person.id, accountId, amountPaise }).unwrap();
      setPaymentAmounts((current) => ({ ...current, [person.id]: '' }));
      setPartialPaymentOpen((current) => ({ ...current, [person.id]: false }));
    }
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
        transfer.creditor.trim().toLowerCase() === 'you' && !transfer.repayment_transaction_id &&
        transfer.amount_paise > (transfer.settled_paise ?? 0))
        .map((transfer) => ({ id: transfer.debtor, name: transfer.debtor,
          accountId: repaymentAccounts[`${split.id}:${transfer.debtor}`] ?? defaultAccountId,
          amountPaise: transfer.amount_paise }))
      : split.participants.filter((person) => person.settled_paise < person.share_paise && !person.repayment_transaction_id)
        .map((person) => ({ id: person.id, name: person.name,
          accountId: repaymentAccounts[person.id] ?? defaultAccountId,
          amountPaise: person.share_paise - person.settled_paise }));
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
      <p className='text-sm text-[var(--text-muted)]'>Track expense shares, money others owe you, and money you owe.</p>
    </header>
    <div className='min-w-0 space-y-4 rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4'>
      <div className='min-w-0' aria-live='polite'>
        <p className='text-xs text-[var(--text-muted)]'>Others owe you</p>
        <p className='break-words text-2xl font-bold text-[var(--positive)]'>{isLoading ? '…' : formatPaiseAsInr(totalOwedPaise)}</p>
        <p className='text-xs text-[var(--text-muted)]'>Expense shares {formatPaiseAsInr(expenseSplitOwedPaise)} · Other IOUs {formatPaiseAsInr(standaloneOwedPaise)}</p>
        <div className='mt-3 border-t border-[var(--bg-border)] pt-3'>
          <p className='text-xs text-[var(--text-muted)]'>You owe</p>
          <p className='break-words text-xl font-semibold text-red-400'>{isLoading ? '…' : `${payableOwedPaise > 0 ? '−' : ''}${formatPaiseAsInr(payableOwedPaise)}`}</p>
          <p className='text-xs text-[var(--text-muted)]'>Payable IOUs are separate from amounts others owe you.</p>
        </div>
        <p className='mt-1 text-xs text-[var(--text-muted)]'>Group settlement plans are listed separately below and are not included in this total.</p>
      </div>
      <div className='grid min-w-0 grid-cols-1 gap-2 min-[480px]:grid-cols-2 md:grid-cols-3'>
        <Button type='button' aria-pressed={open} variant={open ? 'primary' : 'secondary'}
          className='min-w-0 border whitespace-normal text-center text-sm' onClick={() => {
          setOpen((value) => !value); setOwedOpen(false); setComplexOpen(false); setReview(null);
        }}>Split an expense</Button>
        <Button type='button' aria-pressed={owedOpen} variant={owedOpen ? 'primary' : 'secondary'}
          className='min-w-0 border whitespace-normal text-center text-sm' onClick={() => {
          setOwedOpen((value) => !value); setOpen(false); setComplexOpen(false); setReview(null);
        }}>Record money owed</Button>
        <Button type='button' aria-pressed={complexOpen} variant={complexOpen ? 'primary' : 'secondary'}
          className='min-w-0 border whitespace-normal text-center text-sm'
          onClick={() => {
            setComplexOpen((value) => !value); setOpen(false); setOwedOpen(false); setReview(null);
          }}>Plan group settlement</Button>
        <Button type='button' aria-pressed={managePeopleOpen} variant={managePeopleOpen ? 'primary' : 'secondary'}
          className='min-w-0 border whitespace-normal text-center text-sm'
          onClick={() => setManagePeopleOpen((value) => !value)}>Manage people</Button>
        <Button type='button' aria-pressed={balancesOpen} variant={balancesOpen ? 'primary' : 'secondary'}
          className='min-w-0 border whitespace-normal text-center text-sm'
          onClick={() => setBalancesOpen((value) => !value)}>Balances by person</Button>
        <Button type='button' aria-pressed={settlementsOpen} variant={settlementsOpen ? 'primary' : 'secondary'}
          className='min-w-0 border whitespace-normal text-center text-sm'
          onClick={() => setSettlementsOpen((value) => !value)}>Group settlements</Button>
      </div>
    </div>
    {managePeopleOpen && <Card className='space-y-4 p-5'>
      <div className='flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between'>
        <div>
          <h2 className='font-semibold text-[var(--text-primary)]'>Manage people</h2>
          <p className='text-sm text-[var(--text-muted)]'>Add, search, edit, or remove people used in your splits.</p>
        </div>
        <Button type='button' onClick={() => {
          resetContactForm(); setContactFeedback(''); setContactFormOpen(true);
        }}>Add person</Button>
      </div>
      <p className='text-xs text-[var(--text-muted)]'>
        Email addresses are used to send split payment reminders only after you explicitly confirm each reminder.
      </p>
      {managedPeople.length > 0 && <label className='block space-y-1 text-sm text-[var(--text-secondary)]'>
        Search people
        <input className={inputClass} type='search' value={contactSearch} placeholder='Search by name, email, or phone'
          onChange={(event) => setContactSearch(event.target.value)} />
      </label>}
      {managedPeople.length === 0 && !contactFormOpen && <p className='rounded-xl border border-dashed border-[var(--bg-border)] p-5 text-center text-sm text-[var(--text-muted)]'>
        No people found yet. Add someone to attach their email to future split reminders.
      </p>}
      {managedPeople.length > 0 && filteredContactDetails.length === 0 && <p className='text-sm text-[var(--text-muted)]'>
        No people match &quot;{contactSearch}&quot;.
      </p>}
      {filteredContactDetails.length > 0 && <ul className='grid gap-3 sm:grid-cols-2'>
        {filteredContactDetails.map((contact) => <li key={contact.id}
          className='rounded-xl border border-[var(--bg-border)] p-4 text-sm'>
          <p className='break-words font-medium text-[var(--text-primary)]'>{contact.name}</p>
          <p className='mt-1 break-all text-sm text-[var(--text-secondary)]'>{contact.email ?? 'No email address'}</p>
          <p className='mt-1 text-xs text-[var(--text-muted)]'>{contact.phone_e164 ?? 'No phone number'}</p>
          <div className='mt-3 flex flex-wrap gap-2'>
            <Button type='button' variant='secondary' onClick={() => editContact(contact)}>
              {contact.contactId ? 'Edit' : 'Add details'}
            </Button>
            {contact.contactId && <Button type='button' variant='ghost' className='text-[var(--negative)]'
              disabled={deletingContact} onClick={() => { void removeContact(contact); }}>Remove</Button>}
          </div>
          {contactFormOpen && editingContactKey === contact.id && contactEditor(true)}
        </li>)}
      </ul>}
      {contactFormOpen && !editingContactKey && contactEditor(false)}
      {contactFeedback && <p role='status' className='text-sm text-[var(--text-muted)]'>{contactFeedback}</p>}
    </Card>}
    {complexOpen && <ComplexSettlementPlanner />}
    {owedOpen && <Card className='space-y-3 p-5'>
      <div><h2 className='font-semibold text-[var(--text-primary)]'>Record an amount owed</h2>
        <p className='text-xs text-[var(--text-muted)]'>Track a loan or other IOU separately from a shared purchase. No transaction is created until it is paid.</p></div>
      <form onSubmit={saveOwed} className='grid gap-3 sm:grid-cols-2'>
        <label className='space-y-1 text-sm text-[var(--text-secondary)]'>Who owes the money?
          <ThemedSelect id='owed-direction' value={owedDirection} placeholder='Choose who owes' options={[
            { value: 'to_you', label: 'Someone owes me' }, { value: 'by_you', label: 'I owe someone' },
          ]} onChange={(value) => setOwedDirection(value as 'to_you' | 'by_you')} />
        </label>
        <label className='space-y-1 text-sm text-[var(--text-secondary)]'>Person
          {contacts.length > 0 && <ThemedSelect id='owed-person' value={addingOwedPerson ? NEW_OWED_PERSON : owedName}
            placeholder='Choose a saved person' options={[
              ...contacts.map((name) => ({ value: name, label: name })),
              { value: NEW_OWED_PERSON, label: '+ Add a new person' },
            ]}
            onChange={(value) => {
              if (value === NEW_OWED_PERSON) {
                setOwedName('');
                setAddingOwedPerson(true);
              } else {
                setOwedName(value);
                setAddingOwedPerson(false);
              }
            }} />}
          {(contacts.length === 0 || addingOwedPerson) && <input className={inputClass} maxLength={100} value={owedName}
            placeholder={owedDirection === 'to_you' ? 'Enter the person who owes you' : 'Enter the person you owe'}
            onChange={(event) => setOwedName(event.target.value)} />}
        </label>
        <label className='space-y-1 text-sm text-[var(--text-secondary)]'>Amount (₹)
          <input className={inputClass} inputMode='decimal' value={owedAmount} placeholder='500.00'
            onChange={(event) => setOwedAmount(event.target.value)} />
        </label>
        <label className='space-y-1 text-sm text-[var(--text-secondary)] sm:col-span-2'>Reason
          <input className={inputClass} maxLength={255} value={owedTitle} placeholder='Tickets I paid for'
            onChange={(event) => setOwedTitle(event.target.value)} />
        </label>
        <div className='grid grid-cols-1 gap-2 sm:col-span-2 sm:grid-cols-2'><Button type='submit' isLoading={creatingOwed}>Save IOU</Button>
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
    {error && <p role='alert' className='text-sm text-red-400'>{error}</p>}
    {error && <p role='alert' className='rounded-xl bg-red-500/10 p-3 text-sm text-red-300'>{error}</p>}
    {balancesOpen && <section className='space-y-3'>
      <div className='rounded-xl border border-[var(--bg-border)] bg-[var(--bg-surface)] p-4'>
        <div className='flex flex-wrap items-center justify-between gap-3'>
          <div><h2 className='font-semibold text-[var(--text-primary)]'>Balances by person</h2>
            <p className='mt-1 text-xs text-[var(--text-muted)]'>Review mutual balances and settle them. Smaller balances are listed first.</p></div>
        </div>
      </div>
      {balancesOpen && <Card className='space-y-3 p-4'>
        <p className='text-xs text-[var(--text-muted)]'>Matching amounts in both directions are offset before any cash repayment. Review the details before confirming.</p>
      <ul className='grid grid-cols-2 gap-2'>
        {personBalances.map((balance) => <li key={balance.person.toLocaleLowerCase()} className='min-w-0 rounded-xl border border-[var(--bg-border)] p-3'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <span className='font-medium text-[var(--text-primary)]'>{balance.person}</span>
            <span className={`font-semibold tabular-nums ${balance.net_paise < 0 ? 'text-red-400' : 'text-[var(--positive)]'}`}>
              {balance.net_paise < 0 ? '−' : '+'}{formatPaiseAsInr(Math.abs(balance.net_paise))}</span>
          </div>
          <p className='mt-1 text-xs text-[var(--text-muted)]'>Owes you {formatPaiseAsInr(balance.owed_to_you_paise)} · You owe {formatPaiseAsInr(balance.you_owe_paise)}</p>
          <details className='mt-2 text-xs text-[var(--text-secondary)]'>
            <summary className='cursor-pointer text-[var(--brand-primary)]'>View records ({balance.entries.length})</summary>
            <ul className='mt-2 space-y-2'>
              {balance.entries.map((record, index) => <li key={`${record.split_id}-${index}`} className='flex flex-wrap items-center justify-between gap-2'>
                <span>{record.title} · {record.direction === 'to_you' ? 'owes you' : 'you owe'} {formatPaiseAsInr(record.remaining_paise)}</span>
                <span className='flex gap-3'>
                  <button type='button' className='text-[var(--brand-primary)]' onClick={() => navigate(`/splits?splitId=${record.split_id}`)}>View split</button>
                  {splits.find((split) => split.id === record.split_id)?.transaction_id && <button type='button' className='text-[var(--brand-primary)]'
                    onClick={() => navigate(`/transactions?transactionId=${splits.find((split) => split.id === record.split_id)?.transaction_id}`)}>View transaction</button>}
                </span>
              </li>)}
            </ul>
          </details>
          <button type='button' disabled={settlingPersonBalance} className='mt-2 w-full rounded-lg border border-[var(--brand-primary)]/40 px-3 py-1.5 text-xs font-semibold text-[var(--brand-primary)] disabled:opacity-50'
            onClick={() => {
              setError('');
              setBalanceReview(balance);
              setBalanceSettlementAmount(balance.net_paise === 0 ? '' : (Math.abs(balance.net_paise) / 100).toFixed(2));
              setBalanceSettlementAccountId(defaultAccountId);
            }}>{balance.net_paise === 0 ? 'Review offset' : 'Settle balance'}</button>
          {(() => {
            const contact = contactDetails.find((item) => item.name.trim().toLowerCase() === balance.person.trim().toLowerCase());
            if (contact?.email) return <BalanceEmailButton contactId={contact.id} name={balance.person}
              onFeedback={setNotificationFeedback} />;
            return <button type='button'
              className='mt-2 w-full rounded-lg border border-[var(--brand-primary)]/40 px-3 py-1.5 text-xs font-semibold text-[var(--brand-primary)]'
              onClick={() => {
                setManagePeopleOpen(true);
                if (contact) editContact({ id: contact.id, contactId: contact.id, name: contact.name,
                  phone_e164: contact.phone_e164, email: contact.email });
                setContactFeedback(`Add ${balance.person}'s email to send their current balance summary.`);
              }}>Add email to send summary</button>;
          })()}
        </li>)}
      </ul>
      </Card>}
    </section>}
    {loadingPersonBalances && <p className='text-xs text-[var(--text-muted)]'>Loading balances by person…</p>}
    {settlementsOpen && <section className='space-y-3'>
      <div className='rounded-xl border border-[var(--bg-border)] bg-[var(--bg-surface)] p-4'>
        <div className='flex flex-wrap items-center justify-between gap-3'>
          <div><h2 id='group-settlements-heading' className='font-semibold text-[var(--text-primary)]'>Group settlements</h2>
            <p className='mt-1 text-xs text-[var(--text-muted)]'>Review saved plans and repayments.</p></div>
        </div>
      </div>
      {settlementsOpen && <section className='space-y-3' aria-labelledby='group-settlements-heading'>
        <p className='text-xs text-[var(--text-muted)]'>Confirmed plans stay here. Only payments you made or received appear in Transactions.</p>
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
      </section>}
    </section>}
    <section className='space-y-3'><h2 className='font-semibold text-[var(--text-primary)]'>Your split and IOU tracker</h2>
      {isLoading ? <p className='text-sm text-[var(--text-muted)]'>Loading splits…</p> : splits.length === 0 ?
        <Card className='p-5 text-sm text-[var(--text-muted)]'>No splits yet.</Card> : orderedSplits.map((split) =>
          <Card key={split.id} id={`split-${split.id}`}
            className={`scroll-mt-6 space-y-3 p-5 ${focusedSplitId === split.id ? 'ring-2 ring-[var(--brand-primary)]' : ''}`}>
            <div className='flex min-w-0 flex-col gap-3 sm:flex-row sm:justify-between'><div className='min-w-0'><h3 className='break-words font-semibold text-[var(--text-primary)]'>{split.title}</h3>
              <span className='mb-1 inline-flex rounded-full bg-[var(--brand-subtle)] px-2 py-0.5 text-[10px] font-semibold text-[var(--brand-primary)]'>
                {split.kind === 'money_owed' ? (split.direction === 'by_you' ? 'You owe' : 'Money owed to you') : 'Expense split'}
              </span>
              <p className='text-xs text-[var(--text-muted)]'>Total {formatPaiseAsInr(split.total_paise)}{split.kind === 'expense_split' ? ` · Your share ${formatPaiseAsInr(split.owner_share_paise)}` : ''}</p>
              {notificationStatuses[split.id] && <p className='text-xs text-[var(--text-muted)]'>
                {notificationStatuses[split.id].limits_bypassed
                  ? `Reminders sent: ${notificationStatuses[split.id].notification_count} · Test limits disabled`
                  : `Reminders sent: ${notificationStatuses[split.id].notification_count} of ${notificationStatuses[split.id].max_notifications}`}
                {!notificationStatuses[split.id].limits_bypassed && notificationStatuses[split.id].cooldown_remaining_seconds > 0
                  ? ` · ${Math.ceil(notificationStatuses[split.id].cooldown_remaining_seconds / 60)} min cooldown` : ''}
              </p>}</div>
              <div className='min-w-0 text-left sm:text-right'><span className={`break-words text-sm font-semibold ${split.kind === 'money_owed' && split.direction === 'by_you' && split.outstanding_paise > 0 ? 'text-red-400' : 'text-[var(--text-primary)]'}`}>
                {split.kind === 'money_owed' && split.direction === 'by_you'
                  ? `${split.outstanding_paise > 0 ? '−' : ''}${formatPaiseAsInr(split.outstanding_paise)} you owe`
                  : `${formatPaiseAsInr(split.outstanding_paise)} ${split.settlement_breakdown ? 'due to you' : 'due'}`}</span>
                <div className='flex flex-wrap gap-2 sm:justify-end'>
                  {split.transaction_id && <button type='button' className='rounded-lg border border-[var(--bg-border)] px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:border-[var(--brand-primary)] hover:bg-[var(--brand-subtle)] hover:text-[var(--brand-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)] focus-visible:ring-offset-2'
                    onClick={() => navigate(`/transactions?transactionId=${split.transaction_id}`)}>View transaction</button>}
                  {split.kind === 'expense_split' && <button type='button' className='rounded-lg border border-[var(--brand-primary)]/30 bg-[var(--brand-subtle)] px-3 py-1.5 text-xs font-semibold text-[var(--brand-primary)] transition-colors hover:border-[var(--brand-primary)] hover:bg-[var(--brand-primary)] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)] focus-visible:ring-offset-2'
                    onClick={() => setEditingSplitId(editingSplitId === split.id ? null : split.id)}>
                    {editingSplitId === split.id ? 'Close edit' : 'Edit split'}
                  </button>}
                  {split.direction === 'to_you' && unpaidCount(split) > 1 && <button type='button'
                    className='max-w-full rounded-lg border border-[var(--brand-primary)]/30 bg-[var(--brand-subtle)] px-3 py-1.5 text-center text-xs font-semibold whitespace-normal text-[var(--brand-primary)] disabled:opacity-50'
                    disabled={repayingAllSplitId !== null || repaying || repayingTransfer || activeAccounts.length === 0}
                    onClick={() => void markAllRepaid(split)}>
                    {repayingAllSplitId === split.id ? 'Recording repayments…' : 'Mark all as repaid'}
                  </button>}
                  {split.direction === 'to_you' && !split.settlement_breakdown && split.outstanding_paise > 0 &&
                    <button type='button'
                      disabled={notificationStatuses[split.id]?.blocked_reason === 'cooldown_active' ||
                        notificationStatuses[split.id]?.blocked_reason === 'split_limit_reached' ||
                        notificationStatuses[split.id]?.blocked_reason === 'daily_limit_reached' ||
                        notificationStatuses[split.id]?.request_in_progress}
                      className='rounded-lg border border-[var(--brand-primary)]/40 px-3 py-1.5 text-xs font-semibold text-[var(--brand-primary)] disabled:opacity-50'
                      onClick={() => setNotificationQueue([{ split }])}>
                      {notificationStatuses[split.id]?.request_in_progress ? 'Reminder queued' : 'Send reminder'}
                    </button>}
                  <button type='button'
                    className='rounded-lg border border-red-400/50 bg-red-500/10 px-3 py-1.5 text-xs font-semibold text-red-300 transition-colors hover:bg-red-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-60'
                    disabled={deleting}
                    onClick={() => removeSplit(split.id)}>Remove split</button>
                </div></div></div>
            {editingSplitId === split.id ? <EditSplitForm key={split.id} split={split}
              proposedTotalPaise={searchParams.get('edit') === '1' ? paise(searchParams.get('transactionAmount') ?? '') ?? undefined : undefined}
              onCancel={() => setEditingSplitId(null)} /> : <>
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
              transfer.creditor.trim().toLocaleLowerCase() === 'you' && transfer.amount_paise >
                (transfer.settled_paise ?? 0)).length > 0 ?
              split.settlement_breakdown.transfers.filter((transfer) =>
                transfer.creditor.trim().toLocaleLowerCase() === 'you' && transfer.amount_paise >
                  (transfer.settled_paise ?? 0))
                .sort((a, b) => Number(Boolean(a.repayment_transaction_id) || a.amount_paise <= (a.settled_paise ?? 0)) -
                  Number(Boolean(b.repayment_transaction_id) || b.amount_paise <= (b.settled_paise ?? 0)))
                .map((transfer, index) =>
                <div key={`${transfer.debtor}-${index}`} className='flex min-w-0 flex-col gap-3 border-t border-[var(--bg-border)] pt-2 text-sm sm:flex-row sm:items-center sm:justify-between'>
                  <span className='min-w-0 break-words text-[var(--text-primary)]'>{transfer.debtor} · {formatPaiseAsInr(Math.max(0, transfer.amount_paise - (transfer.settled_paise ?? 0)))} {transfer.repayment_transaction_id ? 'repaid' : transfer.settled_paise ? 'partially repaid · remaining' : 'due to you'}</span>
                  {transfer.repayment_transaction_id || transfer.amount_paise <= (transfer.settled_paise ?? 0) ? <div className='flex flex-col items-end gap-1'>
                    <span className='text-xs text-green-400'>{transfer.repayment_transaction_id ? 'Repaid' : 'Settled by offset'}</span>
                    {transfer.repayment_transaction_id && <button type='button' className='text-xs text-[var(--brand-primary)]'
                      onClick={() => navigate(`/transactions?transactionId=${transfer.repayment_transaction_id}`)}>View repayment</button>}
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
              .map((person) => {
                const remaining = Math.max(0, person.share_paise - person.settled_paise);
                const ownerPays = split.kind === 'money_owed' && split.direction === 'by_you';
                const amountText = paymentAmounts[person.id] ?? '';
                const amountPaise = amountText ? paise(amountText) : null;
                return <div key={person.id} className='space-y-2 border-t border-[var(--bg-border)] pt-2'>
                  <div className='flex min-w-0 flex-col gap-3 text-sm sm:flex-row sm:items-start sm:justify-between'>
                    <div className='min-w-0'>
                      <p className={`break-words font-medium ${ownerPays ? 'text-red-400' : 'text-[var(--text-primary)]'}`}>
                        {ownerPays ? `You owe ${person.name}` : `${person.name} owes you`}: {formatPaiseAsInr(remaining)} remaining
                      </p>
                      <p className='text-xs text-[var(--text-muted)]'>Original {formatPaiseAsInr(person.share_paise)} · Paid {formatPaiseAsInr(person.settled_paise)}</p>
                    </div>
                    {remaining > 0 ? <div className='flex w-full min-w-0 flex-col gap-2 sm:w-56 sm:shrink-0 sm:items-end'>
                      <label className='w-full space-y-1 text-xs text-[var(--text-muted)]'>
                        {ownerPays ? 'Pay from' : 'Received in'}
                        <select aria-label={`Account for payment with ${person.name}`}
                          className='block w-full rounded-lg border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-2 text-xs text-[var(--text-primary)]'
                          value={repaymentAccounts[person.id] ?? defaultAccountId}
                          onChange={(event) => setRepaymentAccounts((current) => ({ ...current, [person.id]: event.target.value }))}>
                          {activeAccounts.length === 0 && <option value=''>Choose account</option>}
                          {activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                        </select>
                      </label>
                      {partialPaymentOpen[person.id] && <label className='w-full space-y-1 text-xs text-[var(--text-muted)]'>
                        Partial amount (greater than ₹1.00)
                        <input className={inputClass} inputMode='decimal' placeholder={(remaining / 100).toFixed(2)}
                          aria-label={`Partial payment amount for ${person.name}`} max={remaining / 100}
                          value={amountText} onChange={(event) => setPaymentAmounts((current) => ({ ...current, [person.id]: event.target.value }))} />
                      </label>}
                      <div className='flex w-full flex-wrap justify-end gap-2'>
                        {!ownerPays && <button type='button'
                          disabled={notificationStatuses[split.id]?.blocked_reason === 'cooldown_active' ||
                            notificationStatuses[split.id]?.blocked_reason === 'split_limit_reached' ||
                            notificationStatuses[split.id]?.blocked_reason === 'daily_limit_reached' ||
                            notificationStatuses[split.id]?.request_in_progress}
                          title={!notificationStatuses[split.id]?.recipients.find((recipient) => recipient.participant_id === person.id)?.recipient
                            ? 'Add this person\'s email, then send their reminder.' : undefined}
                          className='rounded-lg border border-[var(--brand-primary)]/40 px-3 py-1.5 text-xs font-semibold text-[var(--brand-primary)] disabled:opacity-50'
                          onClick={() => setNotificationQueue([{ split, participantIds: [person.id] }])}>Send reminder</button>}
                        <button type='button' disabled={recordingSplitPayment || repayingAllSplitId !== null}
                          className='rounded-lg border border-[var(--brand-primary)]/40 px-3 py-1.5 text-xs font-semibold text-[var(--brand-primary)] disabled:opacity-50'
                          onClick={() => {
                            setPartialPaymentOpen((current) => ({ ...current, [person.id]: !current[person.id] }));
                            setPaymentAmounts((current) => ({ ...current, [person.id]: '' }));
                            setError('');
                          }}>{partialPaymentOpen[person.id] ? 'Cancel' : 'Partial Payment'}</button>
                        <button type='button' disabled={recordingSplitPayment || repayingAllSplitId !== null ||
                          (partialPaymentOpen[person.id] && (!amountText || amountPaise === null || amountPaise <= 100 || amountPaise > remaining)) ||
                          !activeAccounts.some((account) => account.id === (repaymentAccounts[person.id] ?? defaultAccountId))}
                          className='rounded-lg bg-[var(--brand-primary)] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[var(--brand-hover)] disabled:opacity-50'
                          onClick={() => void recordParticipantPayment(split, person, partialPaymentOpen[person.id] ? amountText : undefined)}>
                          {partialPaymentOpen[person.id] ? 'Mark Partial Payment' : ownerPays ? 'Mark paid' : 'Mark repaid'}
                        </button>
                      </div>
                    </div> : <span className='text-xs font-medium text-green-400'>Fully paid</span>}
                  </div>
                  {person.payments?.length > 0 && <details className='text-xs text-[var(--text-secondary)]'>
                    <summary className='cursor-pointer text-[var(--brand-primary)]'>Payment history ({person.payments.length})</summary>
                    <ul className='mt-2 space-y-1'>
                      {[...person.payments].sort((a, b) => b.created_at.localeCompare(a.created_at)).map((payment) => <li key={payment.id} className='flex flex-wrap justify-between gap-2'>
                        <span>{new Date(payment.created_at).toLocaleString()} · {formatPaiseAsInr(payment.amount_paise)}
                          {!payment.transaction_id && ' (balance offset)'}</span>
                        {payment.transaction_id && <button type='button' className='text-[var(--brand-primary)]'
                          onClick={() => navigate(`/transactions?transactionId=${payment.transaction_id}`)}>View transaction</button>}
                      </li>)}
                    </ul>
                  </details>}
                </div>;
              })}            {!split.settlement_breakdown && split.outstanding_paise > 0 && <p className='text-xs text-[var(--text-muted)]'>
              {split.kind === 'money_owed' && split.direction === 'by_you'
                ? 'Mark paid records an expense in the Split category and deducts it from the selected account.'
                : 'Mark repaid records income in the Split category in the selected account.'}</p>}
            </>}
          </Card>)}
    </section>
    {notificationFeedback && <p role='status' className='rounded-xl bg-[var(--brand-subtle)] p-3 text-sm text-[var(--brand-primary)]'>
      {notificationFeedback}
    </p>}
    {contactPendingRemoval && <div className='fixed inset-0 z-[130] flex items-center justify-center bg-black/70 p-4'
      role='presentation'>
      <Card role='dialog' aria-modal='true' aria-labelledby='remove-contact-title'
        className='w-full max-w-md space-y-4 p-5'>
        <div>
          <h2 id='remove-contact-title' className='text-lg font-semibold text-[var(--text-primary)]'>
            Remove {contactPendingRemoval.name}?
          </h2>
          <p className='mt-1 text-sm text-[var(--text-muted)]'>
            This removes their saved contact details only. Existing split records are not deleted.
          </p>
        </div>
        {removeContactError && <p role='alert' className='rounded-lg bg-red-500/10 p-3 text-sm text-red-300'>
          {removeContactError}
        </p>}
        <div className='flex flex-wrap justify-end gap-2'>
          <Button type='button' variant='secondary' disabled={deletingContact}
            onClick={() => { setContactPendingRemoval(null); setRemoveContactError(''); }}>Cancel</Button>
          <Button type='button' variant='ghost'
            className='border border-red-400/50 bg-red-500/10 text-red-300 hover:bg-red-500 hover:text-white'
            isLoading={deletingContact} onClick={() => { void confirmRemoveContact(); }}>Remove person</Button>
        </div>
      </Card>
    </div>}
    {notificationQueue[0] && <NotificationConfirmDialog
      split={notificationQueue[0].split}
      contacts={contactDetails}
      initialParticipantIds={notificationQueue[0].participantIds}
      onQueued={(message) => setNotificationFeedback(message)}
      onClose={() => setNotificationQueue((current) => current.slice(1))}
    />}
    {balanceReview && <div className='fixed inset-0 z-[100] flex items-center justify-center overflow-y-auto bg-black/70 p-4' role='presentation'
      onMouseDown={(event) => { if (event.target === event.currentTarget && !settlingPersonBalance) setBalanceReview(null); }}>
      <Card role='dialog' aria-modal='true' aria-labelledby='settle-balance-title' className='my-auto w-full max-w-lg space-y-4 p-5'>
        <div>
          <h2 id='settle-balance-title' className='text-lg font-semibold text-[var(--text-primary)]'>Review balance with {balanceReview.person}</h2>
          <p className='mt-1 text-sm text-[var(--text-muted)]'>The app first cancels out what you owe each other. It then applies any cash payment to the smallest outstanding split entries first.</p>
        </div>
        <div className='grid grid-cols-2 gap-2 text-sm'>
          <div className='rounded-lg bg-[var(--bg-elevated)] p-3'><p className='text-xs text-[var(--text-muted)]'>They owe you</p>
            <p className='font-semibold text-[var(--text-primary)]'>{formatPaiseAsInr(balanceReview.owed_to_you_paise)}</p></div>
          <div className='rounded-lg bg-[var(--bg-elevated)] p-3'><p className='text-xs text-[var(--text-muted)]'>You owe them</p>
            <p className='font-semibold text-[var(--text-primary)]'>{formatPaiseAsInr(balanceReview.you_owe_paise)}</p></div>
          <div className='rounded-lg bg-[var(--bg-elevated)] p-3'><p className='text-xs text-[var(--text-muted)]'>Canceled out</p>
            <p className='font-semibold text-[var(--text-primary)]'>{formatPaiseAsInr(Math.min(balanceReview.owed_to_you_paise, balanceReview.you_owe_paise))}</p></div>
          <div className='rounded-lg bg-[var(--bg-elevated)] p-3'><p className='text-xs text-[var(--text-muted)]'>Net balance</p>
            <p className={`font-semibold ${balanceReview.net_paise < 0 ? 'text-red-400' : 'text-[var(--positive)]'}`}>
              {balanceReview.net_paise === 0 ? 'Settled by offset' : `${balanceReview.net_paise < 0 ? 'You pay' : 'They pay'} ${formatPaiseAsInr(Math.abs(balanceReview.net_paise))}`}</p></div>
        </div>
        {balanceReview.net_paise !== 0 && <>
          <label className='block space-y-1 text-sm text-[var(--text-secondary)]'>Cash amount to record (₹)
            <input className={inputClass} inputMode='decimal' value={balanceSettlementAmount}
              max={(Math.abs(balanceReview.net_paise) / 100).toFixed(2)}
              onChange={(event) => setBalanceSettlementAmount(event.target.value)} />
          </label>
          <label className='block space-y-1 text-sm text-[var(--text-secondary)]'>Wallet account for this payment
            <select className={inputClass} value={balanceSettlementAccountId}
              onChange={(event) => setBalanceSettlementAccountId(event.target.value)}>
              {activeAccounts.length === 0 && <option value=''>No active account</option>}
              {activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
            </select>
          </label>
        </>}
        <p className='rounded-lg border border-[var(--bg-border)] p-3 text-xs text-[var(--text-muted)]'>Confirming updates the existing split and IOU records. Only the cash amount creates wallet transactions; an offset alone does not.</p>
        {error && <p role='alert' className='text-sm text-red-400'>{error}</p>}
        <div className='grid grid-cols-2 gap-2'>
          <Button type='button' variant='secondary' disabled={settlingPersonBalance} onClick={() => setBalanceReview(null)}>Cancel</Button>
          <Button type='button' isLoading={settlingPersonBalance} onClick={() => void confirmBalanceSettlement()}>
            {balanceReview.net_paise === 0 ? 'Confirm offset' : 'Confirm settlement'}
          </Button>
        </div>
      </Card>
    </div>}
  </div>;
}
