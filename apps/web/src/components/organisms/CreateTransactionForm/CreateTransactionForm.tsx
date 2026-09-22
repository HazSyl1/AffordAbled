import { zodResolver } from '@hookform/resolvers/zod';
import { useMemo, useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';

import { useListAccountsQuery } from '../../../features/accounts/accountsApi';
import {
  type CategoryType,
  useCreateCategoryMutation,
  useListCategoriesQuery,
} from '../../../features/categories/categoriesApi';
import { useCreateTransactionMutation } from '../../../features/transactions/transactionsApi';
import type { TransactionType } from '../../../features/transactions/transactionsApi';
import { Button } from '../../atoms/Button';
import { Input } from '../../atoms/Input';
import { FormField } from '../../molecules/FormField';
import { createTransactionSchema } from './CreateTransactionForm.schema';
import type { CreateTransactionFormValues } from './CreateTransactionForm.schema';

export interface CreateTransactionFormProps {
  onSuccess?: () => void;
  showHeading?: boolean;
  mode?: 'page' | 'sheet';
}

function getDefaultOccurredAt(): string {
  const now = new Date();
  const localTimestamp = new Date(now.getTime() - now.getTimezoneOffset() * 60 * 1000);
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

const SELECT_CLASS =
  'w-full min-h-12 rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] px-3 py-3 text-base text-[var(--text-primary)] outline-none transition-colors focus:border-[var(--brand-primary)] focus:ring-1 focus:ring-[var(--brand-primary)]';

export function CreateTransactionForm({ onSuccess, showHeading = true, mode = 'page' }: CreateTransactionFormProps) {
  const isSheetMode = mode === 'sheet';
  const [createTransaction] = useCreateTransactionMutation();
  const [createCategory, { isLoading: isCreatingCategory }] = useCreateCategoryMutation();
  const { data: accounts } = useListAccountsQuery();
  const { data: categories } = useListCategoriesQuery();

  const [formError, setFormError] = useState<string | null>(null);
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
    defaultValues: DEFAULT_VALUES,
  });

  const transactionType = useWatch({ control, name: 'type' });
  const sourceAccountId = useWatch({ control, name: 'accountId' });

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
      reset({ ...DEFAULT_VALUES, occurredAt: getDefaultOccurredAt() });
      onSuccess?.();
    } catch {
      setFormError('Could not create the transaction.');
    }
  });

  const { onChange: onTypeFieldChange, ...typeField } = register('type');
  const { onChange: onCategoryChange, ...categoryField } = register('categoryId');

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
          <select
            id='transaction-type'
            className={SELECT_CLASS}
            {...typeField}
            onChange={(event) => {
              onTypeFieldChange(event);
              handleTypeChange(event.target.value as TransactionType);
            }}
          >
            <option value='expense'>Expense</option>
            <option value='income'>Income</option>
            <option value='transfer'>Transfer</option>
            <option value='refund'>Refund</option>
          </select>
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
          <select id='transaction-account' className={SELECT_CLASS} {...register('accountId')}>
            <option value='' disabled hidden>
              Select account
            </option>
            {accounts?.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name}
              </option>
            ))}
          </select>
        </FormField>
      </div>

      {transactionType === 'transfer' ? (
        <>
          <FormField label='Destination account' htmlFor='transaction-to-account' error={errors.toAccountId?.message}>
            <select id='transaction-to-account' className={SELECT_CLASS} {...register('toAccountId')}>
              <option value='' disabled hidden>
                Select destination account
              </option>
              {destinationAccountOptions.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </select>
          </FormField>

          <p className='mb-4 text-xs text-[var(--text-muted)]'>Transfer entries move balance between two of your accounts.</p>
        </>
      ) : (
        <>
          <FormField label='Category' htmlFor='transaction-category' error={errors.categoryId?.message}>
            <select
              id='transaction-category'
              className={SELECT_CLASS}
              {...categoryField}
              onChange={(event) => {
                if (event.target.value === ADD_CATEGORY_OPTION) {
                  setShowQuickCategory(true);
                  setQuickCategoryError(null);
                  setValue('categoryId', '', { shouldValidate: true });
                  return;
                }

                setShowQuickCategory(false);
                setQuickCategoryError(null);
                onCategoryChange(event);
              }}
            >
              <option value={ADD_CATEGORY_OPTION}>+ Add category</option>
              <option value='' disabled hidden>
                Select category
              </option>
              {filteredCategories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
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
        Add transaction
      </Button>
    </form>
  );
}
