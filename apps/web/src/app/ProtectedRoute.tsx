import { Navigate, Outlet } from 'react-router-dom';

import { Button } from '../components/atoms/Button';
import { PageLoader } from '../components/molecules/PageLoader';
import { CreateAccountForm } from '../components/organisms/CreateAccountForm';
import { Layout } from '../components/templates/Layout';
import { APP_NAME } from '../constants';
import { useListAccountsQuery } from '../features/accounts/accountsApi';
import { useAppSelector } from './hooks';

export function ProtectedRoute() {
  const accessToken = useAppSelector((state) => state.auth.accessToken);
  const { data: accounts, isLoading, isError, refetch } = useListAccountsQuery(undefined, { skip: !accessToken });

  if (!accessToken) {
    return <Navigate to="/login" replace />;
  }

  if (isLoading) {
    return <PageLoader />;
  }

  if (isError) {
    return (
      <main className='flex min-h-screen items-center justify-center bg-[var(--bg-app)] px-4'>
        <section className='w-full max-w-md rounded-3xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-6 text-center'>
          <h1 className='text-xl font-semibold text-[var(--text-primary)]'>We couldn’t load your accounts</h1>
          <p className='mt-2 text-sm text-[var(--text-secondary)]'>Check your connection and try again to continue.</p>
          <Button type='button' className='mt-5' onClick={() => void refetch()}>Try again</Button>
        </section>
      </main>
    );
  }

  if (!accounts?.length) {
    return (
      <main className='flex min-h-screen items-center justify-center bg-[var(--bg-app)] px-4 py-8'>
        <section className='w-full max-w-lg rounded-3xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-6 shadow-2xl sm:p-8'>
          <p className='text-xs font-semibold uppercase tracking-[0.16em] text-[var(--brand-primary)]'>{APP_NAME} · Getting started</p>
          <h1 className='mt-3 text-2xl font-bold text-[var(--text-primary)]'>Add your first account</h1>
          <p className='mb-6 mt-2 text-sm leading-6 text-[var(--text-secondary)]'>Add a bank account, card, cash wallet, or another place you keep money. You can start with a zero balance and update it later.</p>
          <CreateAccountForm showHeading={false} />
        </section>
      </main>
    );
  }

  return (
    <Layout>
      <Outlet />
    </Layout>
  );
}
