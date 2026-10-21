import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useNavigate } from 'react-router-dom';

import { useAppDispatch } from '../../app/hooks';
import { Button } from '../../components/atoms/Button';
import { Input } from '../../components/atoms/Input';
import { FormField } from '../../components/molecules/FormField';
import { AuthPageShell } from '../../components/molecules/AuthPageShell/AuthPageShell';
import { AUTH_UI_TEXT } from '../../constants';
import { useRegisterMutation } from '../../features/auth/authApi';
import { setCredentials } from '../../features/auth/authSlice';
import { registerSchema } from './RegisterPage.schema';
import type { RegisterFormValues } from './RegisterPage.schema';
import { apiClient } from '../../lib/apiClient';

export function RegisterPage() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const [registerUser] = useRegisterMutation();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormValues>({ resolver: zodResolver(registerSchema) });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const result = await registerUser(values).unwrap();
      dispatch(apiClient.util.resetApiState());
      dispatch(setCredentials({ accessToken: result.access_token }));
      navigate('/dashboard', { replace: true });
    } catch {
      setFormError(AUTH_UI_TEXT.registrationError);
    }
  });

  const maxDob = new Date().toISOString().slice(0, 10);

  return (
    <AuthPageShell
      catchphrase='A fresh start for your everyday finances.'
      description='Bring your accounts, transactions, and shared expenses together, then let helpful insights make the picture clearer.'
    >
      <form className='mx-auto min-w-0 w-full max-w-[420px]' onSubmit={onSubmit} noValidate>
        <p className='mb-1 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--brand-primary)]'>Your next money habit starts here</p>
        <h2 className='mb-2 text-2xl font-semibold text-[var(--text-primary)]'>{AUTH_UI_TEXT.registerTitle}</h2>
        <p className='mb-6 text-sm text-[var(--text-secondary)]'>Create a personal space for tracking, understanding, and sharing expenses.</p>

        <FormField label={AUTH_UI_TEXT.nameLabel} htmlFor='name' error={errors.name?.message}>
          <Input id='name' type='text' autoComplete='name' {...register('name')} />
        </FormField>

        <FormField label={AUTH_UI_TEXT.dobLabel} htmlFor='date_of_birth' error={errors.date_of_birth?.message}>
          <Input id='date_of_birth' type='date' className='block w-full min-w-0 max-w-full' max={maxDob} {...register('date_of_birth')} />
        </FormField>

        <FormField label={AUTH_UI_TEXT.emailLabel} htmlFor='email' error={errors.email?.message}>
          <Input id='email' type='email' autoComplete='email' {...register('email')} />
        </FormField>

        <FormField label={AUTH_UI_TEXT.passwordLabel} htmlFor='password' error={errors.password?.message}>
          <Input id='password' type='password' autoComplete='new-password' {...register('password')} />
        </FormField>

        {formError ? (
          <p className='mb-4 text-sm text-[var(--negative)]' role='alert'>
            {formError}
          </p>
        ) : null}

        <Button type='submit' isLoading={isSubmitting}>
          {AUTH_UI_TEXT.registerAction}
        </Button>

        <p className='mt-4 text-sm text-[var(--text-secondary)]'>
          {AUTH_UI_TEXT.alreadyHaveAccountPrompt}{' '}
          <Link className='text-[var(--brand-primary)]' to='/login'>
            {AUTH_UI_TEXT.loginLinkLabel}
          </Link>
        </p>
      </form>
    </AuthPageShell>
  );
}
