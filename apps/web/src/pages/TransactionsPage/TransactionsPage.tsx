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
    <div className='mx-auto max-w-[860px] px-4 py-6'>
      <header className='mb-6 flex flex-wrap items-center justify-between gap-3'>
        <h1 className='text-[var(--text-primary)]'>Transactions</h1>

        <div className='flex items-center gap-2'>
          <Link
            to='/'
            className='inline-flex items-center justify-center rounded-[var(--btn-radius)] border border-[var(--bg-border)] px-4 py-2 font-semibold text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]'
          >
            Accounts
          </Link>
          <Button variant='secondary' onClick={handleLogout}>
            Log out
          </Button>
        </div>
      </header>

      <section className='mb-6'>
        <TransactionList />
      </section>

      <section className='mb-6'>
        <CreateTransactionForm />
      </section>
    </div>
  );
}
