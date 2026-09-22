import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '../../components/atoms/Button';
import { Input } from '../../components/atoms/Input';
import { FormField } from '../../components/molecules/FormField';
import { useLoginMutation } from '../../features/auth/authApi';
import { setCredentials } from '../../features/auth/authSlice';
import { useAppDispatch } from '../../app/hooks';
import { loginSchema } from './LoginPage.schema';
import type { LoginFormValues } from './LoginPage.schema';

export function LoginPage() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const [login] = useLoginMutation();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginSchema) });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const result = await login(values).unwrap();
      dispatch(setCredentials({ accessToken: result.access_token }));
      navigate('/', { replace: true });
    } catch {
      setFormError('Invalid email or password.');
    }
  });

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form className="w-full max-w-[360px]" onSubmit={onSubmit} noValidate>
        <h1 className="mb-6 text-2xl font-semibold text-[var(--text-primary)]">Log in</h1>

        <FormField label="Email" htmlFor="email" error={errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" {...register('email')} />
        </FormField>

        <FormField label="Password" htmlFor="password" error={errors.password?.message}>
          <Input id="password" type="password" autoComplete="current-password" {...register('password')} />
        </FormField>

        {formError ? (
          <p className="mb-4 text-sm text-[var(--negative)]" role="alert">
            {formError}
          </p>
        ) : null}

        <Button type="submit" isLoading={isSubmitting}>
          Log in
        </Button>

        <p className="mt-4 text-sm text-[var(--text-secondary)]">
          No account?{' '}
          <Link className="text-[var(--brand-primary)]" to="/register">
            Register
          </Link>
        </p>
      </form>
    </div>
  );
}
