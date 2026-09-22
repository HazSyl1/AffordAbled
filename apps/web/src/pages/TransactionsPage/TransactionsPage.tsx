import { Link } from 'react-router-dom';

import { useAppDispatch } from '../../app/hooks';
import { Button } from '../../components/atoms/Button';
import { CreateTransactionForm } from '../../components/organisms/CreateTransactionForm';
import { TransactionList } from '../../components/organisms/TransactionList';
import { useLogoutMutation } from '../../features/auth/authApi';
import { clearCredentials } from '../../features/auth/authSlice';

export function TransactionsPage() {
  const dispatch = useAppDispatch();
  const [logout] = useLogoutMutation();

  const handleLogout = async () => {
    try {
      await logout().unwrap();
    } finally {
      dispatch(clearCredentials());
    }
  };

  return (
    <div className='mx-auto max-w-[1100px] px-4 py-6 md:py-8'>
      <header className='mb-6 flex flex-wrap items-center justify-between gap-3 md:mb-8'>
        <div>
          <h1 className='text-2xl font-semibold text-[var(--text-primary)] md:text-3xl'>Transactions</h1>
          <p className='text-sm text-[var(--text-secondary)]'>Track every expense, income, transfer, and refund.</p>
        </div>

        <div className='flex items-center gap-2'>
          <Link
            to='/'
            className='inline-flex items-center justify-center rounded-[var(--btn-radius)] border border-[var(--bg-border)] bg-[var(--bg-card)] px-4 py-2 font-semibold text-[var(--text-primary)] transition-colors hover:bg-[var(--bg-elevated)]'
          >
            Accounts
          </Link>
          <Button variant='secondary' onClick={handleLogout}>
            Log out
          </Button>
        </div>
      </header>

      <div className='grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_390px] lg:items-start'>
        <section className='rounded-[var(--card-radius)] border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 md:p-5'>
          <TransactionList />
        </section>

        <section className='rounded-[var(--card-radius)] border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 md:sticky md:top-6 md:p-5'>
          <CreateTransactionForm />
        </section>
      </div>
    </div>
  );
}
