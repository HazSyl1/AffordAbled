import { zodResolver } from '@hookform/resolvers/zod';
import { useMemo, useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';

import { useListAccountsQuery } from '../../../features/accounts/accountsApi';
import { useListCategoriesQuery } from '../../../features/categories/categoriesApi';
import { useCreateTransactionMutation } from '../../../features/transactions/transactionsApi';
import { Button } from '../../atoms/Button';
import { Input } from '../../atoms/Input';
import { FormField } from '../../molecules/FormField';
import { createTransactionSchema } from './CreateTransactionForm.schema';
import type { CreateTransactionFormValues } from './CreateTransactionForm.schema';

function getDefaultOccurredAt(): string {
  const now = new Date();
  const localTimestamp = new Date(now.getTime() - now.getTimezoneOffset() * 60 * 1000);
  return localTimestamp.toISOString().slice(0, 16);
}

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

export function CreateTransactionForm() {
  const [createTransaction] = useCreateTransactionMutation();
  const { data: accounts } = useListAccountsQuery();
  const { data: categories } = useListCategoriesQuery();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    control,
    register,
    handleSubmit,
    reset,
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

      reset({ ...DEFAULT_VALUES, occurredAt: getDefaultOccurredAt() });
    } catch {
      setFormError('Could not create the transaction.');
    }
  });

  return (
    <form className='max-w-[420px]' onSubmit={onSubmit} noValidate>
      <h2 className='mb-4 text-lg font-semibold text-[var(--text-primary)]'>Add a transaction</h2>

      <FormField label='Source account' htmlFor='transaction-account' error={errors.accountId?.message}>
        <select
          id='transaction-account'
          className='w-full rounded-[var(--input-radius)] border border-[var(--bg-border)] bg-[var(--bg-card)] px-3 py-2 text-[var(--text-primary)]'
          {...register('accountId')}
        >
          <option value=''>Select account</option>
          {accounts?.map((account) => (
            <option key={account.id} value={account.id}>
              {account.name}
            </option>
          ))}
        </select>
      </FormField>

      <FormField label='Type' htmlFor='transaction-type' error={errors.type?.message}>
        <select
          id='transaction-type'
          className='w-full rounded-[var(--input-radius)] border border-[var(--bg-border)] bg-[var(--bg-card)] px-3 py-2 text-[var(--text-primary)]'
          {...register('type')}
        >
          <option value='expense'>Expense</option>
          <option value='income'>Income</option>
          <option value='transfer'>Transfer</option>
          <option value='refund'>Refund</option>
        </select>
      </FormField>

      <FormField label='Amount (INR)' htmlFor='transaction-amount' error={errors.amountRupees?.message}>
        <Input id='transaction-amount' inputMode='decimal' {...register('amountRupees')} />
      </FormField>

      <FormField label='Date and time' htmlFor='transaction-occurred-at' error={errors.occurredAt?.message}>
        <Input id='transaction-occurred-at' type='datetime-local' {...register('occurredAt')} />
      </FormField>

      {transactionType === 'transfer' ? (
        <FormField label='Destination account' htmlFor='transaction-to-account' error={errors.toAccountId?.message}>
          <select
            id='transaction-to-account'
            className='w-full rounded-[var(--input-radius)] border border-[var(--bg-border)] bg-[var(--bg-card)] px-3 py-2 text-[var(--text-primary)]'
            {...register('toAccountId')}
          >
            <option value=''>Select destination account</option>
            {destinationAccountOptions.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name}
              </option>
            ))}
          </select>
        </FormField>
      ) : (
        <FormField label='Category' htmlFor='transaction-category' error={errors.categoryId?.message}>
          <select
            id='transaction-category'
            className='w-full rounded-[var(--input-radius)] border border-[var(--bg-border)] bg-[var(--bg-card)] px-3 py-2 text-[var(--text-primary)]'
            {...register('categoryId')}
          >
            <option value=''>Select category</option>
            {filteredCategories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </FormField>
      )}

      <FormField label='Merchant (optional)' htmlFor='transaction-merchant' error={errors.merchant?.message}>
        <Input id='transaction-merchant' {...register('merchant')} />
      </FormField>

      <FormField label='Note (optional)' htmlFor='transaction-note' error={errors.note?.message}>
        <Input id='transaction-note' {...register('note')} />
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
