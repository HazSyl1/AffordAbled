import { useMemo } from 'react';

import { useListAccountsQuery } from '../../../features/accounts/accountsApi';
import { useListCategoriesQuery } from '../../../features/categories/categoriesApi';
import { useListTransactionsQuery } from '../../../features/transactions/transactionsApi';
import type { TransactionType } from '../../../features/transactions/transactionsApi';
import { formatPaiseAsInr } from '../../../lib/money';

const TYPE_LABEL: Record<TransactionType, string> = {
  expense: 'Expense',
  income: 'Income',
  transfer: 'Transfer',
  refund: 'Refund',
};

const TYPE_BADGE_CLASS: Record<TransactionType, string> = {
  expense: 'border border-[color:rgba(248,113,113,0.35)] bg-[color:rgba(248,113,113,0.14)] text-[var(--negative)]',
  income: 'border border-[color:rgba(74,222,128,0.35)] bg-[color:rgba(74,222,128,0.14)] text-[var(--positive)]',
  transfer: 'border border-[color:rgba(96,165,250,0.35)] bg-[color:rgba(96,165,250,0.14)] text-[var(--info)]',
  refund: 'border border-[color:rgba(74,222,128,0.35)] bg-[color:rgba(74,222,128,0.14)] text-[var(--positive)]',
};

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

function formatAmount(type: TransactionType, amountPaise: number): string {
  const amount = formatPaiseAsInr(amountPaise);

  if (type === 'income' || type === 'refund') {
    return `+${amount}`;
  }

  if (type === 'expense') {
    return `-${amount}`;
  }

  return amount;
}

function getAmountToneClass(type: TransactionType): string {
  if (type === 'income' || type === 'refund') {
    return 'text-[var(--positive)]';
  }

  if (type === 'expense') {
    return 'text-[var(--negative)]';
  }

  return 'text-[var(--text-primary)]';
}

export function TransactionList() {
  const { data: transactions, isLoading, isError } = useListTransactionsQuery();
  const { data: accounts } = useListAccountsQuery();
  const { data: categories } = useListCategoriesQuery();

  const accountNameById = useMemo(() => {
    return new Map((accounts ?? []).map((account) => [account.id, account.name]));
  }, [accounts]);

  const categoryNameById = useMemo(() => {
    return new Map((categories ?? []).map((category) => [category.id, category.name]));
  }, [categories]);

  const visibleTransactions = useMemo(() => {
    return (transactions ?? []).filter((transaction) => transaction.deleted_at === null);
  }, [transactions]);

  return (
    <div>
      <header className='mb-4 flex items-center justify-between gap-3'>
        <h2 className='text-lg font-semibold text-[var(--text-primary)]'>Recent transactions</h2>
        <span className='rounded-full bg-[var(--bg-elevated)] px-2.5 py-1 text-xs font-semibold text-[var(--text-secondary)]'>
          {visibleTransactions.length} total
        </span>
      </header>

      {isLoading ? <p className='text-[var(--text-secondary)]'>Loading transactions...</p> : null}

      {!isLoading && isError ? (
        <p className='text-[var(--negative)]' role='alert'>
          Could not load transactions.
        </p>
      ) : null}

      {!isLoading && !isError && visibleTransactions.length === 0 ? (
        <div className='rounded-[var(--card-radius)] border border-dashed border-[var(--bg-border)] bg-[var(--bg-elevated)] p-5'>
          <p className='m-0 text-sm text-[var(--text-secondary)]'>No transactions yet. Add your first one from the form.</p>
        </div>
      ) : null}

      {!isLoading && !isError && visibleTransactions.length > 0 ? (
        <ul className='m-0 flex list-none flex-col gap-3 p-0'>
          {visibleTransactions.map((transaction) => {
            const accountName = accountNameById.get(transaction.account_id) ?? 'Unknown account';
            const categoryName = transaction.category_id ? categoryNameById.get(transaction.category_id) : null;
            const destinationAccountName = transaction.to_account_id
              ? accountNameById.get(transaction.to_account_id)
              : null;

            return (
              <li
                key={transaction.id}
                className='rounded-[var(--card-radius)] border border-[var(--bg-border)] bg-[var(--bg-app)] p-4 transition-colors hover:bg-[var(--bg-elevated)]'
              >
                <div className='flex flex-wrap items-center justify-between gap-3'>
                  <div className='flex items-center gap-2'>
                    <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${TYPE_BADGE_CLASS[transaction.type]}`}>
                      {TYPE_LABEL[transaction.type]}
                    </span>
                    <span className='text-sm text-[var(--text-secondary)]'>{accountName}</span>
                  </div>

                  <span className={`tabular-nums text-base font-semibold ${getAmountToneClass(transaction.type)}`}>
                    {formatAmount(transaction.type, transaction.amount_paise)}
                  </span>
                </div>

                <div className='mt-2 flex flex-wrap items-center gap-2 text-xs text-[var(--text-secondary)]'>
                  {categoryName ? (
                    <span className='rounded-full bg-[var(--bg-elevated)] px-2 py-1'>{categoryName}</span>
                  ) : null}
                  {destinationAccountName ? (
                    <span className='rounded-full bg-[var(--bg-elevated)] px-2 py-1'>To: {destinationAccountName}</span>
                  ) : null}
                  {transaction.merchant ? (
                    <span className='rounded-full bg-[var(--bg-elevated)] px-2 py-1'>{transaction.merchant}</span>
                  ) : null}
                  <span className='rounded-full bg-[var(--bg-elevated)] px-2 py-1'>
                    {formatTimestamp(transaction.occurred_at)}
                  </span>
                </div>

                {transaction.note ? <p className='mt-2 text-sm text-[var(--text-secondary)]'>{transaction.note}</p> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
