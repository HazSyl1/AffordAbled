import { zodResolver } from '@hookform/resolvers/zod';
import { AlertCircle, ChevronDown } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';

import {
  type AccountType,
  useCreateAccountMutation,
  useListAccountsQuery,
} from '../../../features/accounts/accountsApi';
import {
  type CategoryType,
  useCreateCategoryMutation,
  useListCategoriesQuery,
} from '../../../features/categories/categoriesApi';
import { useCreateTransactionMutation } from '../../../features/transactions/transactionsApi';
import type { TransactionType } from '../../../features/transactions/transactionsApi';
import { DASHBOARD_CHAT_UI_TEXT } from '../../../constants';
import { Badge } from '../../atoms/Badge';
import { Button } from '../../atoms/Button';
import { Input } from '../../atoms/Input';
import { FormField } from '../../molecules/FormField';
import { createTransactionSchema } from './CreateTransactionForm.schema';
import type { CreateTransactionFormValues } from './CreateTransactionForm.schema';

export interface CreateTransactionFormProps {
  onSuccess?: () => void;
  showHeading?: boolean;
  mode?: 'page' | 'sheet';
  initialValues?: Partial<CreateTransactionFormValues>;
  submitLabel?: string;
  prefillMode?: 'standard' | 'manual_low_confidence';
}

function getDefaultOccurredAt(): string {
  const now = new Date();
  const localTimestamp = new Date(now.getTime() - now.getTimezoneOffset() * 60 * 1000);
  return localTimestamp.toISOString().slice(0, 16);
}

function resolveOccurredAt(value: string | undefined): string {
  if (!value) {
    return getDefaultOccurredAt();
  }

  const parsedDate = new Date(value);
  if (Number.isNaN(parsedDate.getTime())) {
    return getDefaultOccurredAt();
  }

  const localTimestamp = new Date(parsedDate.getTime() - parsedDate.getTimezoneOffset() * 60 * 1000);
  return localTimestamp.toISOString().slice(0, 16);
}

function getCategoryTypeForTransactionType(transactionType: TransactionType): CategoryType {
  if (transactionType === 'income' || transactionType === 'refund') {
    return 'income';
  }
  return 'expense';
}

const TYPE_OPTIONS: Array<{ label: string; value: TransactionType }> = [
  { label: 'Expense', value: 'expense' },
  { label: 'Income', value: 'income' },
  { label: 'Transfer', value: 'transfer' },
  { label: 'Refund', value: 'refund' },
];

const ACCOUNT_TYPE_OPTIONS: Array<{ label: string; value: AccountType }> = [
  { label: 'Wallet', value: 'wallet' },
  { label: 'Cash', value: 'cash' },
  { label: 'Bank', value: 'bank' },
  { label: 'Card', value: 'card' },
];

const ADD_ACCOUNT_OPTION = '__add_account__';
const ADD_CATEGORY_OPTION = '__add_category__';

const DEFAULT_VALUES: CreateTransactionFormValues = {
  accountId: '',
  type: 'expense',
  amountRupees: '',
  occurredAt: getDefaultOccurredAt(),
  categoryId: '',
  toAccountId: '',
  merchant: '',
  note: '',
};

function resolveInitialValues(initialValues?: Partial<CreateTransactionFormValues>): CreateTransactionFormValues {
  return {
    ...DEFAULT_VALUES,
    ...initialValues,
    occurredAt: resolveOccurredAt(initialValues?.occurredAt),
  };
}

const SELECT_TRIGGER_CLASS =
  'flex w-full min-h-12 items-center justify-between rounded-xl border border-[var(--bg-border)] bg-[var(--bg-surface)] px-3 py-3 text-left text-base text-[var(--text-primary)] shadow-sm outline-none transition-colors focus-visible:border-[var(--brand-primary)] focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]';

interface ThemedSelectOption {
  label: string;
  value: string;
  disabled?: boolean;
}

interface ThemedSelectProps {
  id: string;
  value: string;
  placeholder: string;
  options: ThemedSelectOption[];
  onChange: (nextValue: string) => void;
}

function ThemedSelect({ id, value, placeholder, options, onChange }: ThemedSelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current) {
        return;
      }

      if (!rootRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
    };
  }, []);

  const selectedOption = options.find((option) => option.value === value);

  return (
    <div className='relative' ref={rootRef}>
      <button
        id={id}
        type='button'
        aria-haspopup='listbox'
        aria-expanded={isOpen}
        className={SELECT_TRIGGER_CLASS}
        onClick={() => setIsOpen((open) => !open)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            setIsOpen(true);
          }
          if (event.key === 'Escape') {
            setIsOpen(false);
          }
        }}
      >
        <span className={selectedOption ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}>
          {selectedOption?.label ?? placeholder}
        </span>
        <ChevronDown
          className={[
            'pointer-events-none size-4 text-[var(--text-muted)] transition-transform duration-200',
            isOpen ? 'rotate-180' : '',
          ].join(' ')}
        />
      </button>

      {isOpen ? (
        <div className='absolute left-0 right-0 top-[calc(100%+0.5rem)] z-30 overflow-hidden rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] shadow-[0_20px_48px_rgba(0,0,0,0.34)]'>
          <ul role='listbox' aria-labelledby={id} className='max-h-64 overflow-auto p-1'>
            {options.map((option) => {
              const isSelected = option.value === value;
              return (
                <li key={option.value}>
                  <button
                    type='button'
                    role='option'
                    aria-selected={isSelected}
                    disabled={option.disabled}
                    className={[
                      'w-full rounded-lg px-3 py-2 text-left text-sm transition-all',
                      option.disabled
                        ? 'cursor-not-allowed text-[var(--text-muted)]'
                        : isSelected
                          ? 'bg-[var(--bg-border)] font-medium text-[var(--text-primary)] shadow-[inset_0_0_0_1px_var(--bg-border)]'
                          : 'text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] hover:shadow-[inset_0_0_0_1px_var(--bg-border)]',
                    ].join(' ')}
                    onClick={() => {
                      if (option.disabled) {
                        return;
                      }
                      onChange(option.value);
                      setIsOpen(false);
                    }}
                  >
                    {option.label}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function CreateTransactionForm({
  onSuccess,
  showHeading = true,
  mode = 'page',
  initialValues,
  submitLabel = 'Add transaction',
  prefillMode = 'standard',
}: CreateTransactionFormProps) {
  const isSheetMode = mode === 'sheet';
  const [createTransaction] = useCreateTransactionMutation();
  const [createAccount, { isLoading: isCreatingAccount }] = useCreateAccountMutation();
  const [createCategory, { isLoading: isCreatingCategory }] = useCreateCategoryMutation();
  const { data: accounts } = useListAccountsQuery();
  const { data: categories } = useListCategoriesQuery();

  const [formError, setFormError] = useState<string | null>(null);
  const [quickAccountName, setQuickAccountName] = useState('');
  const [quickAccountType, setQuickAccountType] = useState<AccountType>('wallet');
  const [quickAccountError, setQuickAccountError] = useState<string | null>(null);
  const [showQuickAccount, setShowQuickAccount] = useState(false);
  const [quickCategoryName, setQuickCategoryName] = useState('');
  const [quickCategoryError, setQuickCategoryError] = useState<string | null>(null);
  const [showQuickCategory, setShowQuickCategory] = useState(false);

  const {
    control,
    register,
    handleSubmit,
    reset,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<CreateTransactionFormValues>({
    resolver: zodResolver(createTransactionSchema),
    defaultValues: resolveInitialValues(initialValues),
  });

  const transactionType = useWatch({ control, name: 'type' });
  const sourceAccountId = useWatch({ control, name: 'accountId' });
  const destinationAccountId = useWatch({ control, name: 'toAccountId' });
  const categoryId = useWatch({ control, name: 'categoryId' });

  const filteredCategories = useMemo(() => {
    if (!categories) {
      return [];
    }

    if (transactionType === 'expense') {
      return categories.filter((category) => category.type === 'expense');
    }

    if (transactionType === 'income' || transactionType === 'refund') {
      return categories.filter((category) => category.type === 'income');
    }

    return [];
  }, [categories, transactionType]);

  const destinationAccountOptions = useMemo(() => {
    if (!accounts) {
      return [];
    }
    return accounts.filter((account) => account.id !== sourceAccountId);
  }, [accounts, sourceAccountId]);

  const categoryTypeForNewCategory = useMemo(
    () => getCategoryTypeForTransactionType(transactionType),
    [transactionType],
  );

  const handleTypeChange = (nextType: TransactionType) => {
    setValue('type', nextType, { shouldDirty: true, shouldValidate: true });
    if (nextType === 'transfer') {
      setShowQuickCategory(false);
      setQuickCategoryError(null);
      setQuickCategoryName('');
      setValue('categoryId', '', { shouldValidate: true });
    }
  };

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);

    try {
      await createTransaction({
        account_id: values.accountId,
        type: values.type,
        amount_paise: Math.round(Number(values.amountRupees) * 100),
        occurred_at: new Date(values.occurredAt).toISOString(),
        category_id: values.type === 'transfer' ? undefined : values.categoryId || undefined,
        to_account_id: values.type === 'transfer' ? values.toAccountId || undefined : undefined,
        merchant: values.merchant?.trim() || undefined,
        note: values.note?.trim() || undefined,
      }).unwrap();

      setShowQuickCategory(false);
      setQuickCategoryName('');
      setQuickCategoryError(null);
      setShowQuickAccount(false);
      setQuickAccountName('');
      setQuickAccountType('wallet');
      setQuickAccountError(null);
      reset(resolveInitialValues(initialValues));
      onSuccess?.();
    } catch {
      setFormError('Could not create the transaction.');
    }
  });

  const handleCreateAccount = async () => {
    const name = quickAccountName.trim();

    if (!name) {
      setQuickAccountError('Account name is required.');
      return;
    }

    setQuickAccountError(null);

    try {
      const account = await createAccount({
        name,
        type: quickAccountType,
        balance_paise: 0,
        currency: 'INR',
      }).unwrap();

      setShowQuickAccount(false);
      setQuickAccountName('');
      setQuickAccountType('wallet');
      setValue('accountId', account.id, { shouldValidate: true });
    } catch {
      setQuickAccountError('Could not add account. Try a different name.');
    }
  };

  const handleCreateCategory = async () => {
    const name = quickCategoryName.trim();

    if (!name) {
      setQuickCategoryError('Category name is required.');
      return;
    }

    setQuickCategoryError(null);

    try {
      const category = await createCategory({
        name,
        type: categoryTypeForNewCategory,
      }).unwrap();

      setShowQuickCategory(false);
      setQuickCategoryName('');
      setValue('categoryId', category.id, { shouldValidate: true });
    } catch {
      setQuickCategoryError('Could not add category. Try a different name.');
    }
  };

  return (
    <form className='w-full' onSubmit={onSubmit} noValidate>
      {showHeading ? (
        <>
          <h2 className='text-base font-semibold text-[var(--text-primary)]'>Add a transaction</h2>
          <p className='mb-4 text-sm text-[var(--text-secondary)]'>Use this form for new and backdated entries.</p>
        </>
      ) : null}

      {prefillMode === 'manual_low_confidence' ? (
        <div className='mb-4 rounded-xl border border-[var(--info)]/40 bg-[color:rgba(96,165,250,0.08)] p-3'>
          <div className='flex flex-wrap items-center gap-2'>
            <AlertCircle size={14} className='text-[var(--info)]' aria-hidden='true' />
            <Badge tone='info'>{DASHBOARD_CHAT_UI_TEXT.manualPrefillBadgeLabel}</Badge>
            <p className='m-0 text-xs text-[var(--text-primary)]'>{DASHBOARD_CHAT_UI_TEXT.manualPrefillHint}</p>
          </div>
        </div>
      ) : null}

      {isSheetMode ? (
        <div className='mb-4 flex gap-2 overflow-x-auto scrollbar-none'>
          {TYPE_OPTIONS.map((typeOption) => (
            <button
              key={typeOption.value}
              type='button'
              onClick={() => handleTypeChange(typeOption.value)}
              className={[
                'min-h-11 flex-1 rounded-xl px-3 py-2 text-xs font-semibold transition-all',
                transactionType === typeOption.value
                  ? 'bg-[var(--brand-primary)] text-white'
                  : 'border border-[var(--bg-border)] bg-[var(--bg-elevated)] text-[var(--text-secondary)]',
              ].join(' ')}
            >
              {typeOption.label}
            </button>
          ))}
        </div>
      ) : (
        <FormField label='Type' htmlFor='transaction-type' error={errors.type?.message}>
          <ThemedSelect
            id='transaction-type'
            value={transactionType}
            placeholder='Select type'
            options={TYPE_OPTIONS.map((typeOption) => ({ label: typeOption.label, value: typeOption.value }))}
            onChange={(nextValue) => handleTypeChange(nextValue as TransactionType)}
          />
        </FormField>
      )}

      <div className='grid grid-cols-1 gap-x-3 md:grid-cols-2'>
        <FormField label='Amount (INR)' htmlFor='transaction-amount' error={errors.amountRupees?.message}>
          <Input
            id='transaction-amount'
            inputMode='decimal'
            placeholder='0.00'
            className={isSheetMode ? 'text-2xl font-bold placeholder:text-[var(--bg-border)]' : ''}
            {...register('amountRupees')}
          />
        </FormField>

        <FormField label='Source account' htmlFor='transaction-account' error={errors.accountId?.message}>
          <ThemedSelect
            id='transaction-account'
            value={sourceAccountId ?? ''}
            placeholder='Select account'
            options={[
              { label: '+ Add account', value: ADD_ACCOUNT_OPTION },
              ...(accounts ?? []).map((account) => ({ label: account.name, value: account.id })),
            ]}
            onChange={(nextValue) => {
              if (nextValue === ADD_ACCOUNT_OPTION) {
                setShowQuickAccount(true);
                setQuickAccountError(null);
                setValue('accountId', '', { shouldValidate: true });
                return;
              }

              setShowQuickAccount(false);
              setQuickAccountError(null);
              setValue('accountId', nextValue, { shouldDirty: true, shouldValidate: true });
            }}
          />
        </FormField>
      </div>

      {showQuickAccount ? (
        <div className='mb-4 rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-3'>
          <p className='m-0 text-xs text-[var(--text-secondary)]'>
            New accounts start at INR 0. You can update balances anytime.
          </p>
          <div className='mt-2 grid grid-cols-1 gap-2 md:grid-cols-2'>
            <Input
              id='quick-account-name'
              value={quickAccountName}
              onChange={(event) => setQuickAccountName(event.target.value)}
              placeholder='Account name'
            />
            <ThemedSelect
              id='quick-account-type'
              value={quickAccountType}
              placeholder='Select account type'
              options={ACCOUNT_TYPE_OPTIONS.map((accountTypeOption) => ({
                label: accountTypeOption.label,
                value: accountTypeOption.value,
              }))}
              onChange={(nextValue) => setQuickAccountType(nextValue as AccountType)}
            />
          </div>
          <div className='mt-2 flex flex-col gap-2 sm:flex-row'>
            <Button
              type='button'
              onClick={handleCreateAccount}
              isLoading={isCreatingAccount}
              className='w-full sm:w-auto'
            >
              Save account
            </Button>
            <Button
              type='button'
              variant='secondary'
              onClick={() => {
                setShowQuickAccount(false);
                setQuickAccountError(null);
                setQuickAccountName('');
                setQuickAccountType('wallet');
              }}
              className='w-full sm:w-auto'
            >
              Cancel
            </Button>
          </div>

          {quickAccountError ? (
            <p className='mt-2 text-sm text-[var(--negative)]' role='alert'>
              {quickAccountError}
            </p>
          ) : null}
        </div>
      ) : null}

      {transactionType === 'transfer' ? (
        <>
          <FormField label='Destination account' htmlFor='transaction-to-account' error={errors.toAccountId?.message}>
            <ThemedSelect
              id='transaction-to-account'
              value={destinationAccountId ?? ''}
              placeholder='Select destination account'
              options={destinationAccountOptions.map((account) => ({ label: account.name, value: account.id }))}
              onChange={(nextValue) => setValue('toAccountId', nextValue, { shouldDirty: true, shouldValidate: true })}
            />
          </FormField>

          <p className='mb-4 text-xs text-[var(--text-muted)]'>Transfer entries move balance between two of your accounts.</p>
        </>
      ) : (
        <>
          <FormField label='Category' htmlFor='transaction-category' error={errors.categoryId?.message}>
            <ThemedSelect
              id='transaction-category'
              value={categoryId ?? ''}
              placeholder='Select category'
              options={[
                { label: '+ Add category', value: ADD_CATEGORY_OPTION },
                ...filteredCategories.map((category) => ({ label: category.name, value: category.id })),
              ]}
              onChange={(nextValue) => {
                if (nextValue === ADD_CATEGORY_OPTION) {
                  setShowQuickCategory(true);
                  setQuickCategoryError(null);
                  setValue('categoryId', '', { shouldValidate: true });
                  return;
                }

                setShowQuickCategory(false);
                setQuickCategoryError(null);
                setValue('categoryId', nextValue, { shouldDirty: true, shouldValidate: true });
              }}
            />
          </FormField>

          {showQuickCategory ? (
            <div className='mb-4 rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-3'>
              <p className='m-0 text-xs text-[var(--text-secondary)]'>
                New category type: <span className='font-semibold capitalize text-[var(--text-primary)]'>{categoryTypeForNewCategory}</span>
              </p>
              <div className='mt-2 flex flex-col gap-2 sm:flex-row'>
                <Input
                  id='quick-category-name'
                  value={quickCategoryName}
                  onChange={(event) => setQuickCategoryName(event.target.value)}
                  placeholder='Category name'
                />
                <Button
                  type='button'
                  onClick={handleCreateCategory}
                  isLoading={isCreatingCategory}
                  className='w-full sm:w-auto'
                >
                  Save category
                </Button>
                <Button
                  type='button'
                  variant='secondary'
                  onClick={() => {
                    setShowQuickCategory(false);
                    setQuickCategoryError(null);
                    setQuickCategoryName('');
                  }}
                  className='w-full sm:w-auto'
                >
                  Cancel
                </Button>
              </div>

              {quickCategoryError ? (
                <p className='mt-2 text-sm text-[var(--negative)]' role='alert'>
                  {quickCategoryError}
                </p>
              ) : null}
            </div>
          ) : null}
        </>
      )}

      <div className='grid grid-cols-1 gap-x-3 md:grid-cols-2'>
        <FormField label='Date and time' htmlFor='transaction-occurred-at' error={errors.occurredAt?.message}>
          <Input id='transaction-occurred-at' type='datetime-local' {...register('occurredAt')} />
        </FormField>

        <FormField label='Merchant (optional)' htmlFor='transaction-merchant' error={errors.merchant?.message}>
          <Input id='transaction-merchant' placeholder='Store or source' {...register('merchant')} />
        </FormField>
      </div>

      <FormField label='Note (optional)' htmlFor='transaction-note' error={errors.note?.message}>
        <Input id='transaction-note' placeholder='Add context' {...register('note')} />
      </FormField>

      {formError ? (
        <p className='mb-4 text-sm text-[var(--negative)]' role='alert'>
          {formError}
        </p>
      ) : null}

      <Button type='submit' isLoading={isSubmitting}>
        {submitLabel}
      </Button>
    </form>
  );
}
