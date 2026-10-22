import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { BadgePercent, CheckCircle2, ReceiptText, UsersRound, Wallet } from 'lucide-react';
import { useForm, useWatch } from 'react-hook-form';
import { useSearchParams } from 'react-router-dom';
import { z } from 'zod';

import { useListAccountsQuery } from '../../features/accounts/accountsApi';
import { useListCategoriesQuery } from '../../features/categories/categoriesApi';
import {
  type SettlementDraft, type SettlementInput, useConfirmSettlementDraftMutation,
  useCreateSettlementDraftMutation, useGetSettlementDraftQuery,
  useListSettlementPlansQuery,
  useUpdateSettlementDraftMutation,
} from '../../features/splits/settlementPlansApi';
import { useListTransactionsQuery } from '../../features/transactions/transactionsApi';
import { formatPaiseAsInr } from '../../lib/money';

const rowSchema = z.object({
  id: z.string(), label: z.string(), amount: z.string(), sharedBy: z.string(), paidBy: z.string(),
  sourceQuote: z.string(),
});
const formSchema = z.object({
  title: z.string().trim().min(1),
  participants: z.string().trim().min(1),
  debts: z.array(z.object({ debtor: z.string(), creditor: z.string(), amount: z.string() })),
  bills: z.array(z.object({
    id: z.string(), merchant: z.string().trim().min(1), total: z.string(),
    charges: z.array(rowSchema).min(1),
    discounts: z.array(z.object({ label: z.string(), rate: z.string(), amount: z.string(),
      chargeIds: z.string(), includeExtras: z.boolean(), sourceQuote: z.string() })),
    extras: z.array(z.object({ id: z.string(), label: z.string(), kind: z.enum(['fee', 'tip']), rate: z.string(),
      amount: z.string(), base: z.string(), baseChargeIds: z.string(), sharedBy: z.string(), paidBy: z.string(),
      sourceQuote: z.string() })),
    payments: z.array(z.object({ person: z.string(), amount: z.string(), transactionId: z.string(),
      accountId: z.string(), categoryId: z.string(), coveredChargeIds: z.string(),
      coveredExtraIds: z.string() })).min(1),
  })).min(1),
});
type FormValues = z.infer<typeof formSchema>;
type BillForm = FormValues['bills'][number];

const fieldClass = 'min-w-0 w-full rounded-lg border border-[var(--bg-border)] bg-[var(--bg-elevated)] px-3 py-2 text-sm text-[var(--text-primary)]';
const labelClass = 'block min-w-0 space-y-1 text-xs font-medium text-[var(--text-secondary)]';
const smallButton = 'inline-flex min-w-0 max-w-full items-center justify-center rounded-lg border border-[var(--bg-border)] px-3 py-2 text-center text-xs font-semibold whitespace-normal break-words text-[var(--text-secondary)] hover:text-white';
const steps = [
  { icon: UsersRound, title: 'People', description: 'Name everyone, including yourself as You.' },
  { icon: ReceiptText, title: 'Bills', description: 'Add each item and who shares its cost.' },
  { icon: BadgePercent, title: 'Adjustments', description: 'Coupons reduce costs; fees and tips add to them.' },
  { icon: Wallet, title: 'Payments', description: 'Say who actually paid each charge.' },
  { icon: CheckCircle2, title: 'Review', description: 'Check the totals and transfers before saving.' },
];
const names = (value: string) => value.split(',').map((part) => part.trim()).filter(Boolean);
const isOwnerName = (value: string) => ['you', 'me', 'myself', 'i'].includes(value.trim().toLowerCase());
const toggleId = (value: string, id: string) => {
  const selected = names(value);
  return (selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id]).join(', ');
};

function paise(value: string): number {
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(value.trim())) throw new Error('Use amounts with at most two decimals.');
  const [whole, fractional = ''] = value.trim().split('.');
  const result = Number(whole) * 100 + Number(fractional.padEnd(2, '0'));
  if (!Number.isSafeInteger(result)) throw new Error('Amount is too large.');
  return result;
}

function basisPoints(value: string): number {
  return paise(value);
}

function rupees(value: number): string {
  return (value / 100).toFixed(2);
}

function newBill(): BillForm {
  return {
    id: crypto.randomUUID(), merchant: '', total: '',
    charges: [{ id: crypto.randomUUID(), label: '', amount: '', sharedBy: 'You', paidBy: 'You', sourceQuote: '' }],
    discounts: [], extras: [],
    payments: [{ person: 'You', amount: '', transactionId: '', accountId: '', categoryId: '',
      coveredChargeIds: '', coveredExtraIds: '' }],
  };
}

function fromInput(data: SettlementInput): FormValues {
  return {
    title: data.title,
    participants: data.participants.filter((name) => name !== 'You').join(', '),
    debts: data.debts.map((row) => ({ debtor: row.debtor, creditor: row.creditor,
      amount: rupees(row.amount_paise) })),
    bills: data.bills.map((bill) => ({
      id: bill.id, merchant: bill.merchant, total: bill.stated_total_paise ? rupees(bill.stated_total_paise) : '',
      charges: bill.charges.map((row) => ({
        id: row.id, label: row.label, amount: rupees(row.amount_paise), sharedBy: row.shared_by.join(', '),
        sourceQuote: row.source_quote || '',
        paidBy: row.paid_by || bill.payments.find((payment) =>
          payment.covered_charge_ids?.includes(row.id))?.person || (bill.payments.length === 1
            ? bill.payments[0].person : ''),
      })),
      discounts: bill.discounts.map((row) => ({
        label: row.label, rate: row.rate_bps ? rupees(row.rate_bps) : '',
        amount: row.amount_paise ? rupees(row.amount_paise) : '', chargeIds: row.charge_ids.join(', '),
        includeExtras: row.include_extras ?? false, sourceQuote: row.source_quote || '',
      })),
      extras: bill.extras.map((row) => ({
        id: row.id || crypto.randomUUID(), label: row.label, kind: row.kind,
        rate: row.rate_bps ? rupees(row.rate_bps) : '',
        amount: row.amount_paise ? rupees(row.amount_paise) : '',
        base: row.base_paise ? rupees(row.base_paise) : '',
        baseChargeIds: (row.base_charge_ids || []).join(', '), sharedBy: row.shared_by.join(', '),
        sourceQuote: row.source_quote || '',
        paidBy: row.paid_by || bill.payments.find((payment) =>
          row.id && payment.covered_extra_ids?.includes(row.id))?.person || (bill.payments.length === 1
            ? bill.payments[0].person : ''),
      })),
      payments: bill.payments.map((row) => ({
        person: row.person, amount: row.amount_paise == null ? '' : rupees(row.amount_paise),
        transactionId: row.transaction_id || '',
        accountId: row.account_id || '', categoryId: row.category_id || '',
        coveredChargeIds: (row.covered_charge_ids || []).join(', '),
        coveredExtraIds: (row.covered_extra_ids || []).join(', '),
      })),
    })),
  };
}

function toInput(values: FormValues): SettlementInput {
  return {
    title: values.title.trim(), participants: ['You', ...names(values.participants)],
    debts: values.debts.map((row) => ({ debtor: row.debtor.trim(), creditor: row.creditor.trim(),
      amount_paise: paise(row.amount) })),
    bills: values.bills.map((bill) => ({
      id: bill.id, merchant: bill.merchant.trim(), stated_total_paise: bill.total ? paise(bill.total) : undefined,
      charges: bill.charges.map((row) => ({
        id: row.id, label: row.label.trim(), amount_paise: paise(row.amount), shared_by: names(row.sharedBy),
        paid_by: row.paidBy.trim() || undefined,
        source_quote: row.sourceQuote || undefined,
      })),
      discounts: bill.discounts.map((row) => ({
        label: row.label.trim(), charge_ids: names(row.chargeIds).length
          ? names(row.chargeIds) : bill.charges.map((charge) => charge.id),
        rate_bps: row.rate ? basisPoints(row.rate) : undefined,
        amount_paise: row.amount ? paise(row.amount) : undefined,
        include_extras: row.includeExtras,
        source_quote: row.sourceQuote || undefined,
      })),
      extras: bill.extras.map((row) => ({
        id: row.id, label: row.label.trim(), kind: row.kind, shared_by: names(row.sharedBy),
        paid_by: row.paidBy.trim() || undefined,
        source_quote: row.sourceQuote || undefined,
        rate_bps: row.rate ? basisPoints(row.rate) : undefined,
        amount_paise: row.amount ? paise(row.amount) : undefined,
        base_paise: row.rate && row.base ? paise(row.base) : undefined,
        base_charge_ids: row.rate && !row.base
          ? names(row.baseChargeIds).length
            ? names(row.baseChargeIds) : bill.charges.map((charge) => charge.id)
          : undefined,
      })),
      payments: bill.payments.filter((row) => {
        const rowPayers = [...bill.charges, ...bill.extras].map((item) => item.paidBy.trim());
        return rowPayers.some((name) => !name) || rowPayers.some((name) =>
          name.toLowerCase() === row.person.trim().toLowerCase());
      }).map((row) => ({
        person: row.person.trim(), amount_paise: row.amount ? paise(row.amount) : undefined,
        covered_charge_ids: row.amount ? [] : names(row.coveredChargeIds),
        covered_extra_ids: row.amount ? [] : names(row.coveredExtraIds),
        transaction_id: isOwnerName(row.person) ? row.transactionId || undefined : undefined,
        account_id: isOwnerName(row.person) && !row.transactionId
          ? row.accountId || undefined : undefined,
        category_id: isOwnerName(row.person) && !row.transactionId
          ? row.categoryId || undefined : undefined,
        occurred_at: isOwnerName(row.person) && !row.transactionId
          ? new Date().toISOString() : undefined,
      })),
    })),
  };
}

function detail(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const data = error.data;
    if (typeof data === 'object' && data !== null && 'detail' in data) return String(data.detail);
  }
  return 'Could not complete the request. Check the bill details and try again.';
}

export function ComplexSettlementPlanner() {
  const [searchParams, setSearchParams] = useSearchParams();
  const draftId = searchParams.get('draft');
  const { currentData: savedDraft, isLoading: loadingDraft, isFetching: fetchingDraft, isError: draftError, refetch } =
    useGetSettlementDraftQuery(draftId || '', { skip: !draftId, refetchOnMountOrArgChange: true });
  const onDraftId = (id: string | null) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (id) next.set('draft', id);
      else next.delete('draft');
      return next;
    });
  };

  if (draftId && loadingDraft && !savedDraft) {
    return <section role='status' className='rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-6 text-center'>
      <img src='/affordabled-wallet-loader.svg' alt='' aria-hidden='true' width='180' height='140'
        className='mx-auto h-auto w-40' />
      <p className='text-sm text-[var(--text-secondary)]'>Opening your latest settlement preview…</p>
    </section>;
  }
  if (draftId && draftError) {
    return <section className='rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-6'>
      <h2 className='font-semibold text-[var(--text-primary)]'>This preview could not be opened</h2>
      <p className='mt-2 text-sm text-[var(--text-secondary)]'>The link may be old or the draft may be unavailable.</p>
      <button type='button' className={`${smallButton} mt-4`} onClick={() => onDraftId(null)}>Start a new plan</button>
    </section>;
  }
  if (savedDraft?.status === 'confirmed') {
    return <section className='rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-6'>
      <h2 className='font-semibold text-[var(--text-primary)]'>This settlement was already saved</h2>
      <p className='mt-2 text-sm text-[var(--text-secondary)]'>A saved plan cannot be edited through its old preview.
        Show the saved plans, then choose Edit plan to create a revision.</p>
      <button type='button' className={`${smallButton} mt-4`} onClick={() => onDraftId(null)}>Show saved plans</button>
    </section>;
  }

  return <PlannerForm key={`${savedDraft?.id || 'new'}:${savedDraft?.version || 0}`}
    savedDraft={savedDraft} restoringDraft={Boolean(draftId && fetchingDraft)}
    reloadDraft={async () => { if (draftId) await refetch().unwrap(); }} onDraftId={onDraftId} />;
}

function PlannerForm({ savedDraft, restoringDraft, reloadDraft, onDraftId }: {
  savedDraft?: SettlementDraft;
  restoringDraft: boolean;
  reloadDraft: () => Promise<void>;
  onDraftId: (id: string | null) => void;
}) {
  const [draft, setDraft] = useState<SettlementDraft | null>(savedDraft || null);
  const [revisionPlanId, setRevisionPlanId] = useState<string | undefined>(savedDraft?.revision_plan_id || undefined);
  const [message, setMessage] = useState('');
  const [needsReload, setNeedsReload] = useState(false);
  const { data: accounts = [] } = useListAccountsQuery();
  const { data: categories = [] } = useListCategoriesQuery();
  const { data: transactions = [] } = useListTransactionsQuery();
  const { data: plans = [] } = useListSettlementPlansQuery();
  const [createDraft, { isLoading: previewing }] = useCreateSettlementDraftMutation();
  const [updateDraft] = useUpdateSettlementDraftMutation();
  const [confirmDraft, { isLoading: confirming }] = useConfirmSettlementDraftMutation();
  const { register, handleSubmit, getValues, setValue, reset, control, formState } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: savedDraft ? fromInput(savedDraft.data) : {
      title: '', participants: '', bills: [newBill()], debts: [],
    },
  });
  const bills = useWatch({ control, name: 'bills' });
  const debts = useWatch({ control, name: 'debts' });
  const missingWalletDetails = draft?.data.bills.some((bill) => bill.payments.some((payment) =>
    isOwnerName(payment.person) && !payment.transaction_id &&
    (!payment.account_id || !payment.category_id))) ?? false;

  async function preview(values: FormValues) {
    setMessage('');
    try {
      const data = toInput(values);
      const next = draft
        ? await updateDraft({ id: draft.id, version: draft.version, data }).unwrap()
        : await createDraft({ request_key: crypto.randomUUID(), data,
          revision_plan_id: revisionPlanId }).unwrap();
      setDraft(next);
      reset(fromInput(next.data));
      onDraftId(next.id);
      setMessage('Review the amounts below before saving.');
    } catch (error) {
      const reason = detail(error);
      if (reason === 'This preview has changed. Reload it before editing.') {
        setNeedsReload(true);
        setMessage('This preview was updated or already saved. Reload the latest version before editing.');
      } else setMessage(reason);
    }
  }

  async function confirm() {
    if (!draft) return;
    setMessage('');
    try {
      const plan = await confirmDraft({ id: draft.id, version: draft.version }).unwrap();
      setMessage(`Saved ${plan.title}. Wallet payments and the settlement were recorded together.`);
      setDraft(null);
      setRevisionPlanId(undefined);
      reset({ title: '', participants: '', bills: [newBill()], debts: [] });
      onDraftId(null);
    } catch (error) {
      const reason = detail(error);
      if (reason === 'This preview has changed. Reload it before confirming.') {
        setNeedsReload(true);
        setMessage('This preview was updated or already saved. Reload the latest version before confirming.');
      } else setMessage(reason);
    }
  }

  function changeBill(index: number, update: (bill: BillForm) => BillForm) {
    const current = getValues('bills');
    setValue('bills', current.map((bill, itemIndex) => itemIndex === index ? update(bill) : bill),
      { shouldDirty: true });
  }

  function syncRowPayers(index: number) {
    const bill = getValues('bills')[index];
    const rowPayers = [...bill.charges, ...bill.extras].map((row) => row.paidBy.trim());
    if (rowPayers.some((name) => !name)) return;
    const payers = [...new Map(rowPayers.map((name) => [name.toLowerCase(), name])).values()];
    setValue(`bills.${index}.payments`, payers.map((name) => {
      const existing = bill.payments.find((payment) => payment.person.trim().toLowerCase() === name.toLowerCase());
      return existing ? { ...existing, coveredChargeIds: '', coveredExtraIds: '' } : {
        person: name, amount: '', transactionId: '', accountId: '', categoryId: '',
        coveredChargeIds: '', coveredExtraIds: '',
      };
    }), { shouldDirty: true });
  }

  return <section className='min-w-0 space-y-5 rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 sm:p-6'>
    <div><h2 className='text-lg font-semibold text-[var(--text-primary)]'>Plan a group settlement</h2>
      <p className='mt-1 text-sm text-[var(--text-secondary)]'>Bring several bills into one plan. First review the math, then choose whether to save new wallet expenses and who owes whom.</p></div>
    <ol aria-label='How to plan a settlement' className='grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5'>
      {steps.map((step, index) => <li key={step.title}
        className={`min-w-0 rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-3 ${index === steps.length - 1 ? 'col-span-2 sm:col-span-1' : ''}`}>
        <div className='flex items-center gap-2 text-[var(--brand-primary)]'>
          <step.icon className='h-4 w-4 shrink-0' aria-hidden='true' />
          <span className='min-w-0 break-words text-xs font-semibold'>{index + 1}. {step.title}</span>
        </div>
        <p className='mt-2 text-xs leading-5 text-[var(--text-secondary)]'>{step.description}</p>
      </li>)}
    </ol>
    <form onSubmit={handleSubmit(preview, () => setMessage('Complete the title, people, and bill fields.'))}
      className='space-y-5'>
      <div className='grid gap-3 sm:grid-cols-2'>
        <label className={labelClass}>Plan title<input className={fieldClass}
          {...register('title')} placeholder='Dinner and cafes' /></label>
        <label className={labelClass}>Other people (separate with commas)
          <input className={fieldClass} {...register('participants')} placeholder='A, B, C, D, E' /></label>
      </div>
      <p className='rounded-lg bg-[var(--brand-subtle)] p-3 text-xs leading-5 text-[var(--text-secondary)]'>
        <strong className='text-[var(--text-primary)]'>Two different roles:</strong> “Shared by” is who owes a share.
        “Paid by” is who already paid the merchant. Use “You” for yourself. A promise to repay is not an actual payment.
      </p>
      <div className='space-y-2'><h3 className='text-sm font-medium text-[var(--text-primary)]'>Older debts to include (optional)</h3>
        <p className='text-xs text-[var(--text-muted)]'>For example, if C already owes A ₹500, add it here. This does not create another bill item.</p>
        {debts.map((_, index) => <div key={index} className='grid min-w-0 gap-2 rounded-lg border border-[var(--bg-border)] p-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_8rem_auto]'>
          <label className={labelClass}>Who owes?<input className={fieldClass}
            {...register(`debts.${index}.debtor`)} placeholder='C' /></label>
          <label className={labelClass}>Who receives?<input className={fieldClass}
            {...register(`debts.${index}.creditor`)} placeholder='A' /></label>
          <label className={labelClass}>Amount (₹)<input className={fieldClass} inputMode='decimal'
            {...register(`debts.${index}.amount`)} placeholder='500.00' /></label>
          <button type='button' className={`${smallButton} self-end`} onClick={() => setValue('debts',
            debts.filter((__, rowIndex) => rowIndex !== index), { shouldDirty: true })}>Remove</button>
        </div>)}
        <button type='button' className={smallButton} onClick={() => setValue('debts',
          [...debts, { debtor: '', creditor: '', amount: '' }], { shouldDirty: true })}>Add debt</button>
      </div>
      {bills.map((bill, billIndex) => <div key={bill.id} className='min-w-0 space-y-5 rounded-xl border border-[var(--bg-border)] p-4'>
        <div className='flex flex-wrap items-center justify-between gap-2'><h3 className='min-w-0 break-words font-semibold text-[var(--text-primary)]'>Bill {billIndex + 1}{bill.merchant ? ` · ${bill.merchant}` : ''}</h3>
          {bills.length > 1 && <button className={smallButton} type='button'
            onClick={() => setValue('bills', bills.filter((_, index) => index !== billIndex),
              { shouldDirty: true })}>Remove bill</button>}</div>
        <div className='grid gap-3 sm:grid-cols-2'>
          <label className={labelClass}>Merchant or bill name<input className={fieldClass}
            {...register(`bills.${billIndex}.merchant`)} placeholder='Cafe XYZ' /></label>
          <label className={labelClass}>Final amount charged (₹, optional)<input className={fieldClass}
            {...register(`bills.${billIndex}.total`)} placeholder='Leave blank if unknown' inputMode='decimal' />
            <span className='block text-[var(--text-muted)]'>Use the amount on the receipt after coupons, fees, and tips. It must match the calculated total.</span></label>
        </div>
        <div className='space-y-2'><h4 className='text-sm font-medium text-[var(--text-primary)]'>Items and shared charges</h4>
          <p className='text-xs text-[var(--text-muted)]'>Add what was bought. The people sharing an item may differ from the person who paid for it.</p>
          {bill.charges.map((row, index) => <div key={row.id} className='grid min-w-0 gap-2 rounded-lg border border-[var(--bg-border)] p-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.2fr)_7rem_minmax(0,1.2fr)_7rem_auto]'>
            <label className={labelClass}>Item {index + 1}<input className={fieldClass}
              {...register(`bills.${billIndex}.charges.${index}.label`)} placeholder='Starters' /></label>
            <label className={labelClass}>Price (₹)<input className={fieldClass} inputMode='decimal'
              {...register(`bills.${billIndex}.charges.${index}.amount`)} placeholder='5000.00' /></label>
            <label className={labelClass}>Shared by<input className={fieldClass}
              {...register(`bills.${billIndex}.charges.${index}.sharedBy`)} placeholder='You, A, B, E' /></label>
            <label className={labelClass}>Paid by<input className={fieldClass}
              {...register(`bills.${billIndex}.charges.${index}.paidBy`, {
                onBlur: () => syncRowPayers(billIndex),
              })} placeholder='You' /></label>
            <button className={`${smallButton} self-end`} type='button' disabled={bill.charges.length === 1}
              onClick={() => changeBill(billIndex, (current) => ({
                ...current, charges: current.charges.filter((_, rowIndex) => rowIndex !== index),
              }))}>Remove</button>
          </div>)}
          <button className={smallButton} type='button' onClick={() => changeBill(billIndex, (current) => ({
            ...current, charges: [...current.charges, {
              id: crypto.randomUUID(), label: '', amount: '', sharedBy: 'You', paidBy: 'You', sourceQuote: '',
            }],
          }))}>Add item</button>
        </div>
        <div className='space-y-2'><h4 className='flex items-center gap-2 text-sm font-medium text-[var(--text-primary)]'>
          <BadgePercent className='h-4 w-4 text-[var(--brand-primary)]' aria-hidden='true' /> Coupons and discounts</h4>
          <p className='text-xs text-[var(--text-muted)]'>A coupon subtracts from this bill. Add it here, not under fees or tips. Choose either a percentage or a fixed amount.</p>
          {bill.discounts.map((_, index) => <div key={index} className='space-y-3 rounded-lg border border-[var(--bg-border)] p-3'>
            <div className='grid gap-2 sm:grid-cols-3'>
              <label className={labelClass}>Coupon name<input className={fieldClass}
                {...register(`bills.${billIndex}.discounts.${index}.label`)} placeholder='Swiggy coupon' /></label>
              <label className={labelClass}>Discount rate (%)<input className={fieldClass} inputMode='decimal'
                {...register(`bills.${billIndex}.discounts.${index}.rate`)} placeholder='10' /></label>
              <label className={labelClass}>Or fixed discount (₹)<input className={fieldClass} inputMode='decimal'
                {...register(`bills.${billIndex}.discounts.${index}.amount`)} placeholder='Leave blank for %' /></label>
            </div>
            <fieldset className='flex flex-wrap gap-2 text-xs text-[var(--text-secondary)]'><legend className='font-medium'>Which items get this discount?</legend>
              {bill.charges.map((charge) => <label key={charge.id} className='inline-flex items-center gap-1'>
                <input type='checkbox' checked={!bill.discounts[index].chargeIds ||
                  names(bill.discounts[index].chargeIds).includes(charge.id)}
                  onChange={() => changeBill(billIndex, (current) => {
                    const selected = current.discounts[index].chargeIds === 'none' ? []
                      : current.discounts[index].chargeIds
                        ? names(current.discounts[index].chargeIds) : current.charges.map((item) => item.id);
                    const next = selected.includes(charge.id)
                      ? selected.filter((id) => id !== charge.id) : [...selected, charge.id];
                    return { ...current, discounts: current.discounts.map((item, rowIndex) => rowIndex === index
                      ? { ...item, chargeIds: next.length ? next.join(', ') : 'none' } : item) };
                  })} />{charge.label || 'Unnamed item'}</label>)}
            </fieldset>
            <label className='inline-flex items-center gap-2 text-xs text-[var(--text-secondary)]'>
              <input type='checkbox' {...register(`bills.${billIndex}.discounts.${index}.includeExtras`)} />
              Include this bill’s fees and tips in the discount base
            </label>
            <p className='text-xs text-[var(--text-muted)]'>For “10% off food plus service fee”, select the food items and check the box above.</p>
            <button className={smallButton} type='button' onClick={() => changeBill(billIndex, (current) => ({
              ...current, discounts: current.discounts.filter((_, rowIndex) => rowIndex !== index),
            }))}>Remove coupon</button>
          </div>)}
          <button className={smallButton} type='button' onClick={() => changeBill(billIndex, (current) => ({
            ...current, discounts: [...current.discounts, { label: '', rate: '', amount: '',
              chargeIds: '', includeExtras: false, sourceQuote: '' }],
          }))}>Add coupon</button>
        </div>
        <div className='space-y-2'><h4 className='text-sm font-medium text-[var(--text-primary)]'>Fees and tips</h4>
          <p className='text-xs text-[var(--text-muted)]'>These add to the bill. Select Fee or Tip, then enter a percentage or fixed amount.</p>
          {bill.extras.some((extra) => /\b(coupon|discount)\b/i.test(extra.label)) &&
            <p role='alert' className='rounded-lg border border-amber-400/40 bg-amber-400/10 p-2 text-xs text-amber-200'>
              A coupon or discount appears in Fees and tips. This would add to the bill. Remove it here and add it under Coupons and discounts above.
            </p>}
          {bill.extras.map((_, index) => <div key={index} className='space-y-3 rounded-lg border border-[var(--bg-border)] p-3'>
            <div className='grid gap-2 sm:grid-cols-2 lg:grid-cols-3'>
              <label className={labelClass}>Fee or tip name<input className={fieldClass}
                {...register(`bills.${billIndex}.extras.${index}.label`)} placeholder='Card fee' /></label>
              <label className={labelClass}>Type<select className={fieldClass}
                {...register(`bills.${billIndex}.extras.${index}.kind`)}>
                <option value='fee'>Fee</option><option value='tip'>Tip</option></select></label>
              <label className={labelClass}>Rate (%)<input className={fieldClass} inputMode='decimal'
                {...register(`bills.${billIndex}.extras.${index}.rate`)} placeholder='2.7' /></label>
              <label className={labelClass}>Or fixed amount (₹)<input className={fieldClass} inputMode='decimal'
                {...register(`bills.${billIndex}.extras.${index}.amount`)} placeholder='Leave blank for %' /></label>
              <label className={labelClass}>Custom rate base (₹, optional)<input className={fieldClass} inputMode='decimal'
                {...register(`bills.${billIndex}.extras.${index}.base`)} placeholder='Use selected items below' /></label>
              <label className={labelClass}>Shared by<input className={fieldClass}
                {...register(`bills.${billIndex}.extras.${index}.sharedBy`)} placeholder='A, C, D, E' /></label>
              <label className={labelClass}>Paid by<input className={fieldClass}
                {...register(`bills.${billIndex}.extras.${index}.paidBy`, {
                  onBlur: () => syncRowPayers(billIndex),
                })} placeholder='You' /></label>
            </div>
            <fieldset className='flex flex-wrap gap-2 text-xs text-[var(--text-secondary)]'><legend className='font-medium'>Calculate the percentage from these items</legend>
              {bill.charges.map((charge) => <label key={charge.id} className='inline-flex items-center gap-1'>
                <input type='checkbox' checked={!bill.extras[index].baseChargeIds ||
                  names(bill.extras[index].baseChargeIds).includes(charge.id)}
                  onChange={() => changeBill(billIndex, (current) => {
                    const selected = current.extras[index].baseChargeIds === 'none' ? []
                      : current.extras[index].baseChargeIds
                        ? names(current.extras[index].baseChargeIds) : current.charges.map((item) => item.id);
                    const next = selected.includes(charge.id)
                      ? selected.filter((id) => id !== charge.id) : [...selected, charge.id];
                    return { ...current, extras: current.extras.map((item, rowIndex) => rowIndex === index
                      ? { ...item, baseChargeIds: next.length ? next.join(', ') : 'none' } : item) };
                  })} />{charge.label || 'Unnamed item'}</label>)}
            </fieldset>
            <p className='text-xs text-[var(--text-muted)]'>Use the custom rate base above instead if the percentage applies to a different amount.</p>
            <button className={smallButton} type='button' onClick={() => changeBill(billIndex, (current) => ({
              ...current, extras: current.extras.filter((_, rowIndex) => rowIndex !== index),
            }))}>Remove fee or tip</button>
          </div>)}
          <button className={smallButton} type='button' onClick={() => changeBill(billIndex, (current) => ({
            ...current, extras: [...current.extras, { id: crypto.randomUUID(), label: '', kind: 'fee', rate: '', amount: '',
              base: '', baseChargeIds: '', sharedBy: 'You', paidBy: 'You', sourceQuote: '' }],
          }))}>Add fee or tip</button>
        </div>
        <div className='space-y-2'><h4 className='flex items-center gap-2 text-sm font-medium text-[var(--text-primary)]'>
          <Wallet className='h-4 w-4 text-[var(--brand-primary)]' aria-hidden='true' /> Who actually paid?</h4>
          <p className='text-xs text-[var(--text-muted)]'>Payers come from the “Paid by” fields above. If one person paid the whole bill, leave the amount blank; the final amount is calculated. With multiple payers and a coupon, enter each person’s actual final payment.</p>
          {bill.payments.map((payment, index) => <div key={index} className='space-y-3 rounded-lg border border-[var(--bg-border)] p-3'>
            <div className='grid gap-2 sm:grid-cols-2'>
              <label className={labelClass}>Payer<input className={fieldClass}
                {...register(`bills.${billIndex}.payments.${index}.person`)} placeholder='You or friend name' /></label>
              <label className={labelClass}>Amount already paid (₹)<input className={fieldClass} inputMode='decimal'
                {...register(`bills.${billIndex}.payments.${index}.amount`)} placeholder='Leave blank for one payer' /></label>
            </div>
            <fieldset className='flex flex-wrap gap-2 text-xs text-[var(--text-secondary)]'>
              <legend className='font-medium'>Or calculate from rows this person paid</legend>
              {bill.charges.map((charge) => <label key={charge.id} className='inline-flex items-center gap-1'>
                <input type='checkbox' checked={names(bill.payments[index].coveredChargeIds).includes(charge.id)}
                  onChange={() => changeBill(billIndex, (current) => ({ ...current,
                    payments: current.payments.map((payment, rowIndex) => rowIndex === index
                      ? { ...payment, amount: '',
                        coveredChargeIds: toggleId(payment.coveredChargeIds, charge.id) } : payment),
                  }))} />{charge.label || 'Unnamed item'}</label>)}
              {bill.extras.map((extra) => <label key={extra.id} className='inline-flex items-center gap-1'>
                <input type='checkbox' checked={names(bill.payments[index].coveredExtraIds).includes(extra.id)}
                  onChange={() => changeBill(billIndex, (current) => ({ ...current,
                    payments: current.payments.map((payment, rowIndex) => rowIndex === index
                      ? { ...payment, amount: '',
                        coveredExtraIds: toggleId(payment.coveredExtraIds, extra.id) } : payment),
                  }))} />{extra.label || 'Unnamed fee or tip'}</label>)}
            </fieldset>
            {isOwnerName(payment.person) ? <div className='space-y-2 rounded-lg bg-[var(--brand-subtle)] p-3'>
              <p className='text-xs font-medium text-[var(--text-primary)]'>Your wallet payment</p>
              <p className='text-xs text-[var(--text-muted)]'>Link an expense already in your wallet, or choose an account and category to record a new expense when you save.</p>
              <div className='grid gap-2 sm:grid-cols-2'>
                <label className={labelClass}>Existing wallet expense (optional)<select className={fieldClass}
                  {...register(`bills.${billIndex}.payments.${index}.transactionId`)}>
                  <option value=''>Record a new wallet expense</option>
                  {transactions.filter((row) => row.type === 'expense' && !plans.some((plan) =>
                    plan.id !== revisionPlanId && plan.transaction_ids.includes(row.id))).map((row) =>
                    <option key={row.id} value={row.id}>{row.merchant || 'Expense'} · {formatPaiseAsInr(row.amount_paise)}</option>)}
                </select></label>
                {!payment.transactionId && <>
                  <label className={labelClass}>Paying wallet account<select className={fieldClass}
                    {...register(`bills.${billIndex}.payments.${index}.accountId`)}>
                    <option value=''>Choose account</option>
                    {accounts.filter((row) => row.is_active).map((row) =>
                      <option key={row.id} value={row.id}>{row.name}</option>)}
                  </select></label>
                  <label className={labelClass}>Expense category<select className={fieldClass}
                    {...register(`bills.${billIndex}.payments.${index}.categoryId`)}>
                    <option value=''>Choose category</option>
                    {categories.filter((row) => row.type === 'expense').map((row) =>
                      <option key={row.id} value={row.id}>{row.name}</option>)}
                  </select></label>
                </>}
              </div>
            </div> : <p className='text-xs text-[var(--text-muted)]'>This person paid outside your wallet. No wallet expense is created for their payment.</p>}
            <button className={smallButton} type='button' disabled={bill.payments.length === 1}
              onClick={() => changeBill(billIndex, (current) => ({
                ...current, payments: current.payments.filter((_, rowIndex) => rowIndex !== index),
              }))}>Remove payer</button>
          </div>)}
          <button className={smallButton} type='button' onClick={() => changeBill(billIndex, (current) => ({
            ...current, payments: [...current.payments, { person: '', amount: '', transactionId: '',
              accountId: '', categoryId: '', coveredChargeIds: '', coveredExtraIds: '' }],
          }))}>Add payer</button>
        </div>
      </div>)}
      <div className='grid grid-cols-1 gap-2 sm:grid-cols-2'>
        <button type='button' className={smallButton} onClick={() => setValue('bills', [...bills, newBill()],
          { shouldDirty: true })}>Add bill</button>
        <button type='submit' disabled={previewing || restoringDraft || needsReload}
          className='min-w-0 rounded-lg bg-[var(--brand-primary)] px-4 py-2 text-center text-sm font-semibold whitespace-normal text-white disabled:opacity-50'>
          {previewing ? 'Calculating…' : restoringDraft ? 'Opening latest preview…' : 'Review settlement'}</button>
      </div>
    </form>
    {message && <p role='status' className='text-sm text-[var(--text-secondary)]'>{message}</p>}
    {needsReload && <button type='button' className={smallButton} onClick={() => {
      void reloadDraft().catch((error: unknown) => setMessage(detail(error)));
    }}>Reload latest preview</button>}
    {draft && <div className='min-w-0 space-y-4 break-words rounded-xl border border-purple-400/30 p-4'>
      <h3 className='flex items-center gap-2 font-semibold text-[var(--text-primary)]'>
        <CheckCircle2 className='h-4 w-4 text-[var(--brand-primary)]' aria-hidden='true' /> Review {draft.data.title}</h3>
      <p className='text-xs text-[var(--text-muted)]'>This is a preview. Check each bill total, the discounts, who paid, and the final transfers before saving.</p>
      <p className='text-sm text-[var(--text-secondary)]'>Total across bills: {formatPaiseAsInr(draft.preview.total_paise)}</p>
      {draft.preview.bills.map((bill, billIndex) => <div key={bill.id} className='text-sm text-[var(--text-secondary)]'>
        <strong className='text-[var(--text-primary)]'>{bill.merchant}: {formatPaiseAsInr(bill.total_paise)}</strong>
        {bill.rows.map((row, index) => <p key={index}>{row.label}: {formatPaiseAsInr(row.amount_paise)} ·
          {Object.entries(row.allocations).map(([person, amount]) => ` ${person} ${formatPaiseAsInr(amount)}`).join(',')}</p>)}
        {bill.payment_amounts_paise?.map((amount, index) => <p key={`payment-${index}`}>
          Paid by {draft.data.bills[billIndex].payments[index].person}: {formatPaiseAsInr(amount)}
        </p>)}
      </div>)}
      <div className='text-sm text-[var(--text-secondary)]'>{Object.entries(draft.preview.shares_paise).map(([person, amount]) =>
        <p key={person}>{person}: share {formatPaiseAsInr(amount)} · already paid {formatPaiseAsInr(draft.preview.paid_paise[person])}</p>)}</div>
      <div className='text-sm text-[var(--text-secondary)]'><strong className='text-[var(--text-primary)]'>Settlement plan</strong>
        {draft.preview.transfers.length
          ? draft.preview.transfers.map((row, index) => <p key={index}>{row.debtor} pays {row.creditor} {formatPaiseAsInr(row.amount_paise)}</p>)
          : <p>No transfers needed.</p>}</div>
      {draft.preview.settled_transfers?.length ? <div className='text-sm text-[var(--text-muted)]'>
        <strong>Already settled</strong>{draft.preview.settled_transfers.map((row) =>
          <p key={row.id}>{row.debtor} paid {row.creditor} {formatPaiseAsInr(row.amount_paise)}</p>)}
      </div> : null}
      {formState.isDirty && <p className='text-xs text-amber-300'>You changed the form. Review again before saving.</p>}
      {missingWalletDetails && <p className='text-xs text-amber-300'>Choose an account and expense category for each new payment you made, then review again.</p>}
      <button type='button' disabled={confirming || restoringDraft || needsReload || formState.isDirty || missingWalletDetails || draft.status !== 'draft'}
        className='max-w-full rounded-lg bg-[var(--brand-primary)] px-4 py-2 text-center text-sm font-semibold whitespace-normal text-white disabled:opacity-50'
        onClick={confirm}>{confirming ? 'Saving…' : 'Save plan and wallet expenses'}</button>
    </div>}
    {plans.length > 0 && <div className='space-y-3 border-t border-[var(--bg-border)] pt-4'>
      <h3 className='font-semibold text-[var(--text-primary)]'>Edit a saved plan</h3>
      <p className='text-xs text-[var(--text-muted)]'>Repayments are shown in the Group settlements cards above.</p>
      {plans.map((plan) => <div key={plan.id} id={`group-plan-${plan.id}`}
        className='min-w-0 scroll-mt-4 space-y-2 break-words rounded-xl border border-[var(--bg-border)] p-3 text-sm'>
        <p className='font-semibold text-[var(--text-primary)]'>{plan.title} · {formatPaiseAsInr(plan.total_paise)}</p>
        <button type='button' className={smallButton}
          onClick={() => { reset(fromInput(plan.data)); setDraft(null); setRevisionPlanId(plan.id);
            setMessage('Edit the plan, then review and confirm the revision.'); }}>
          Edit plan</button>
      </div>)}
    </div>}
  </section>;
}
