import { useMemo } from 'react';

import { useListAccountsQuery } from '../../../features/accounts/accountsApi';
import { useListCategoriesQuery } from '../../../features/categories/categoriesApi';
import { useListTransactionsQuery } from '../../../features/transactions/transactionsApi';
import { formatPaiseAsInr } from '../../../lib/money';

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
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

  if (isLoading) {
    return <p className='text-[var(--text-secondary)]'>Loading transactions…</p>;
  }

  if (isError) {
    return (
      <p className='text-[var(--negative)]' role='alert'>
        Could not load transactions.
      </p>
    );
  }

  if (!transactions || transactions.length === 0) {
    return <p className='text-[var(--text-secondary)]'>No transactions yet — add your first one below.</p>;
  }

  return (
    <ul className='m-0 flex list-none flex-col gap-2 p-0'>
      {transactions.map((transaction) => {
        const accountName = accountNameById.get(transaction.account_id) ?? 'Unknown account';
        const categoryName = transaction.category_id ? categoryNameById.get(transaction.category_id) : null;

        return (
          <li
            key={transaction.id}
            className='rounded-[var(--card-radius)] border border-[var(--bg-border)] bg-[var(--bg-card)] p-3'
          >
            <div className='mb-1 flex items-center justify-between gap-3'>
              <span className='font-semibold capitalize text-[var(--text-primary)]'>{transaction.type}</span>
              <span className='tabular-nums font-semibold text-[var(--text-primary)]'>
                {formatPaiseAsInr(transaction.amount_paise)}
              </span>
            </div>

            <div className='flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-[var(--text-secondary)]'>
              <span>{accountName}</span>
              {categoryName ? <span>{categoryName}</span> : null}
              {transaction.merchant ? <span>{transaction.merchant}</span> : null}
              <span>{formatTimestamp(transaction.occurred_at)}</span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
