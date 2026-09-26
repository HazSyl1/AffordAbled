import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useNavigate } from 'react-router-dom';

import { useAppDispatch } from '../../app/hooks';
import { Button } from '../../components/atoms/Button';
import { Input } from '../../components/atoms/Input';
import { FormField } from '../../components/molecules/FormField';
import { AUTH_UI_TEXT } from '../../constants';
import { useRegisterMutation } from '../../features/auth/authApi';
import { setCredentials } from '../../features/auth/authSlice';
import { registerSchema } from './RegisterPage.schema';
import type { RegisterFormValues } from './RegisterPage.schema';

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
      dispatch(setCredentials({ accessToken: result.access_token }));
      navigate('/', { replace: true });
    } catch {
      setFormError(AUTH_UI_TEXT.registrationError);
    }
  });

  const maxDob = new Date().toISOString().slice(0, 10);

  return (
    <div className='flex min-h-screen items-center justify-center p-4'>
      <form className='w-full max-w-[360px]' onSubmit={onSubmit} noValidate>
        <h1 className='mb-6 text-2xl font-semibold text-[var(--text-primary)]'>{AUTH_UI_TEXT.registerTitle}</h1>

        <FormField label={AUTH_UI_TEXT.nameLabel} htmlFor='name' error={errors.name?.message}>
          <Input id='name' type='text' autoComplete='name' {...register('name')} />
        </FormField>

        <FormField label={AUTH_UI_TEXT.dobLabel} htmlFor='date_of_birth' error={errors.date_of_birth?.message}>
          <Input id='date_of_birth' type='date' max={maxDob} {...register('date_of_birth')} />
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
    </div>
  );
}
