import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { Button } from '../../components/atoms/Button';
import { Card } from '../../components/atoms/Card';
import { BottomSheet } from '../../components/molecules/BottomSheet';
import { CreateTransactionForm } from '../../components/organisms/CreateTransactionForm';
import type { CreateTransactionFormValues } from '../../components/organisms/CreateTransactionForm/CreateTransactionForm.schema';
import { TransactionList } from '../../components/organisms/TransactionList';
import { useListTransactionsQuery } from '../../features/transactions/transactionsApi';
import type { Transaction } from '../../features/transactions/transactionsApi';
import { SHEET_TITLES } from '../../constants';
import { formatPaiseAsInr } from '../../lib/money';

function mapTransactionToFormValues(transaction: Transaction): Partial<CreateTransactionFormValues> {
  return {
    accountId: transaction.account_id,
    type: transaction.type,
    amountRupees: (transaction.amount_paise / 100).toFixed(2),
    occurredAt: transaction.occurred_at,
    categoryId: transaction.category_id ?? '',
    toAccountId: transaction.to_account_id ?? '',
    merchant: transaction.merchant ?? '',
    note: transaction.note ?? '',
  };
}

export function TransactionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTransactionId = searchParams.get('transactionId');
  const { data: transactions } = useListTransactionsQuery();
  const [isAddTransactionSheetOpen, setIsAddTransactionSheetOpen] = useState(false);
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);
  const transactionBeingEdited = requestedTransactionId
    ? transactions?.find((item) => item.id === requestedTransactionId) ?? null
    : selectedTransaction;

  const editInitialValues = useMemo(
    () => (transactionBeingEdited ? mapTransactionToFormValues(transactionBeingEdited) : undefined),
    [transactionBeingEdited],
  );

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

  const handleOpenEditSheet = (transaction: Transaction) => {
    setSelectedTransaction(transaction);
  };

  const handleCloseEditSheet = () => {
    setSelectedTransaction(null);
    if (requestedTransactionId) {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        next.delete('transactionId');
        return next;
      }, { replace: true });
    }
  };

  return (
    <div className='mx-auto w-full max-w-[1200px] px-4 py-4 md:px-6 md:py-6'>
      <header className='sticky top-[env(safe-area-inset-top)] z-10 -mx-4 mb-4 border-b border-[var(--bg-border)] bg-[color:rgba(9,9,11,0.9)] px-4 py-4 backdrop-blur-xl md:static md:mx-0 md:border-none md:bg-transparent md:px-0 md:py-0'>
        <div className='flex items-start justify-between gap-3'>
          <div>
            <h1 className='text-xl font-bold text-[var(--text-primary)]'>Transactions</h1>
            <p className='text-xs text-[var(--text-secondary)]'>Review spending, income, and transfers in one place. Click a transaction to edit it or add a split.</p>
          </div>

          <div className='flex gap-2'>
            <Button type='button' className='w-auto px-3 lg:hidden' onClick={() => setIsAddTransactionSheetOpen(true)}>
              + Add
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
            <TransactionList onTransactionSelect={handleOpenEditSheet} />
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

      <BottomSheet
        isOpen={Boolean(transactionBeingEdited)}
        onClose={handleCloseEditSheet}
        title={SHEET_TITLES.editTransaction}
      >
        {transactionBeingEdited ? (
          <CreateTransactionForm
            mode='sheet'
            showHeading={false}
            transactionId={transactionBeingEdited.id}
            initialValues={editInitialValues}
            submitLabel='Save changes'
            onSuccess={handleCloseEditSheet}
          />
        ) : null}
      </BottomSheet>
    </div>
  );
}
