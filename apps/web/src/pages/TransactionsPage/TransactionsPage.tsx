import { useMemo, useState } from 'react';

import { useAppDispatch } from '../../app/hooks';
import { Button } from '../../components/atoms/Button';
import { Card } from '../../components/atoms/Card';
import { BottomSheet } from '../../components/molecules/BottomSheet';
import { CreateTransactionForm } from '../../components/organisms/CreateTransactionForm';
import { TransactionList } from '../../components/organisms/TransactionList';
import { useLogoutMutation } from '../../features/auth/authApi';
import { clearCredentials } from '../../features/auth/authSlice';
import { useListTransactionsQuery } from '../../features/transactions/transactionsApi';
import { SHEET_TITLES } from '../../constants';
import { formatPaiseAsInr } from '../../lib/money';

export function TransactionsPage() {
  const dispatch = useAppDispatch();
  const [logout] = useLogoutMutation();
  const { data: transactions } = useListTransactionsQuery();
  const [isAddTransactionSheetOpen, setIsAddTransactionSheetOpen] = useState(false);

  const summary = useMemo(() => {
    let expensePaise = 0;
    let incomePaise = 0;
    let transferPaise = 0;

    for (const transaction of transactions ?? []) {
      if (transaction.deleted_at !== null) {
        continue;
      }

      if (transaction.type === 'expense') {
        expensePaise += transaction.amount_paise;
      } else if (transaction.type === 'income' || transaction.type === 'refund') {
        incomePaise += transaction.amount_paise;
      } else if (transaction.type === 'transfer') {
        transferPaise += transaction.amount_paise;
      }
    }

    return {
      expensePaise,
      incomePaise,
      transferPaise,
      netPaise: incomePaise - expensePaise,
    };
  }, [transactions]);

  const handleLogout = async () => {
    try {
      await logout().unwrap();
    } finally {
      dispatch(clearCredentials());
    }
  };

  return (
    <div className='mx-auto w-full max-w-[1200px] px-4 py-4 md:px-6 md:py-6'>
      <header className='sticky top-[env(safe-area-inset-top)] z-10 -mx-4 mb-4 border-b border-[var(--bg-border)] bg-[color:rgba(9,9,11,0.9)] px-4 py-4 backdrop-blur-xl md:static md:mx-0 md:border-none md:bg-transparent md:px-0 md:py-0'>
        <div className='flex items-start justify-between gap-3'>
          <div>
            <h1 className='text-xl font-bold text-[var(--text-primary)]'>Transactions</h1>
            <p className='text-xs text-[var(--text-secondary)]'>Review spending, income, and transfers in one place.</p>
          </div>

          <div className='flex gap-2'>
            <Button type='button' className='w-auto px-3 lg:hidden' onClick={() => setIsAddTransactionSheetOpen(true)}>
              + Add
            </Button>
            <Button type='button' variant='secondary' className='w-auto px-3' onClick={handleLogout}>
              Log out
            </Button>
          </div>
        </div>
      </header>

      <section className='mb-5'>
        <div className='flex gap-3 overflow-x-auto pb-1 scrollbar-none'>
          <Card className='min-w-[120px] flex-shrink-0 p-3'>
            <p className='text-lg font-bold text-[var(--negative)]'>-{formatPaiseAsInr(summary.expensePaise)}</p>
            <p className='mt-0.5 text-xs text-[var(--text-muted)]'>Expenses</p>
          </Card>
          <Card className='min-w-[120px] flex-shrink-0 p-3'>
            <p className='text-lg font-bold text-[var(--positive)]'>+{formatPaiseAsInr(summary.incomePaise)}</p>
            <p className='mt-0.5 text-xs text-[var(--text-muted)]'>Income</p>
          </Card>
          <Card className='min-w-[120px] flex-shrink-0 p-3'>
            <p className='text-lg font-bold text-[var(--text-primary)]'>{formatPaiseAsInr(summary.netPaise)}</p>
            <p className='mt-0.5 text-xs text-[var(--text-muted)]'>Net</p>
          </Card>
          <Card className='min-w-[120px] flex-shrink-0 p-3'>
            <p className='text-lg font-bold text-[var(--info)]'>{formatPaiseAsInr(summary.transferPaise)}</p>
            <p className='mt-0.5 text-xs text-[var(--text-muted)]'>Transfers</p>
          </Card>
        </div>
      </section>

      <div className='grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start'>
        <section>
          <Card className='p-4 md:p-5'>
            <TransactionList />
          </Card>
        </section>

        <section className='hidden lg:block lg:sticky lg:top-6'>
          <Card className='p-5'>
            <CreateTransactionForm mode='page' />
          </Card>
        </section>
      </div>

      <BottomSheet
        isOpen={isAddTransactionSheetOpen}
        onClose={() => setIsAddTransactionSheetOpen(false)}
        title={SHEET_TITLES.addTransaction}
      >
        <CreateTransactionForm
          mode='sheet'
          showHeading={false}
          onSuccess={() => setIsAddTransactionSheetOpen(false)}
        />
      </BottomSheet>
    </div>
  );
}
