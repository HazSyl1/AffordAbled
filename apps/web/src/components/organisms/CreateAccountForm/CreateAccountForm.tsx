import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';

import { Button } from '../../atoms/Button';
import { Input } from '../../atoms/Input';
import { FormField } from '../../molecules/FormField';
import { useCreateAccountMutation } from '../../../features/accounts/accountsApi';
import { createAccountSchema } from './CreateAccountForm.schema';
import type { CreateAccountFormValues } from './CreateAccountForm.schema';

export function CreateAccountForm() {
  const [createAccount] = useCreateAccountMutation();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<CreateAccountFormValues>({
    resolver: zodResolver(createAccountSchema),
    defaultValues: { type: 'wallet' },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await createAccount({
        name: values.name,
        type: values.type,
        balance_paise: Math.round(Number(values.balanceRupees) * 100),
        currency: 'INR',
      }).unwrap();
      reset();
    } catch {
      setFormError('Could not create the account.');
    }
  });

  return (
    <form className="max-w-[360px]" onSubmit={onSubmit} noValidate>
      <h2 className="mb-4 text-lg font-semibold text-[var(--text-primary)]">Add an account</h2>

      <FormField label="Name" htmlFor="account-name" error={errors.name?.message}>
        <Input id="account-name" {...register('name')} />
      </FormField>

      <FormField label="Type" htmlFor="account-type" error={errors.type?.message}>
        <select
          id="account-type"
          className="w-full rounded-[var(--input-radius)] border border-[var(--bg-border)] bg-[var(--bg-card)] px-3 py-2 text-[var(--text-primary)]"
          {...register('type')}
        >
          <option value="wallet">Wallet</option>
          <option value="cash">Cash</option>
          <option value="bank">Bank</option>
          <option value="card">Card</option>
        </select>
      </FormField>

      <FormField label="Starting balance (INR)" htmlFor="account-balance" error={errors.balanceRupees?.message}>
        <Input id="account-balance" inputMode="decimal" {...register('balanceRupees')} />
      </FormField>

      {formError ? (
        <p className="mb-4 text-sm text-[var(--negative)]" role="alert">
          {formError}
        </p>
      ) : null}

      <Button type="submit" isLoading={isSubmitting}>
        Add account
      </Button>
    </form>
  );
}
