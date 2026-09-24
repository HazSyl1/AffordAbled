import { useMemo } from 'react';
import { Link } from 'react-router-dom';

import { useListAccountsQuery } from '../../../features/accounts/accountsApi';
import { useListCategoriesQuery } from '../../../features/categories/categoriesApi';
import { useListTransactionsQuery } from '../../../features/transactions/transactionsApi';
import type { Transaction, TransactionType } from '../../../features/transactions/transactionsApi';
import { formatPaiseAsInr } from '../../../lib/money';
import { Badge } from '../../atoms/Badge';
import { Card } from '../../atoms/Card';

const TYPE_ICON: Record<TransactionType, string> = {
  expense: '🧾',
  income: '💰',
  transfer: '🔁',
  refund: '↩️',
};

const TYPE_LABEL: Record<TransactionType, string> = {
  expense: 'Expense',
  income: 'Income',
  transfer: 'Transfer',
  refund: 'Refund',
};

function getBadgeTone(type: TransactionType): 'negative' | 'positive' | 'info' {
  if (type === 'expense') {
    return 'negative';
  }

  if (type === 'transfer') {
    return 'info';
  }

  return 'positive';
}

function getAmountToneClass(type: TransactionType): string {
  if (type === 'expense') {
    return 'text-[var(--negative)]';
  }

  if (type === 'transfer') {
    return 'text-[var(--text-primary)]';
  }

  return 'text-[var(--positive)]';
}

function formatAmount(type: TransactionType, amountPaise: number): string {
  const amount = formatPaiseAsInr(amountPaise);
  if (type === 'expense') {
    return `-${amount}`;
  }
  if (type === 'income' || type === 'refund') {
    return `+${amount}`;
  }
  return amount;
}

function getDateGroupLabel(occurredAt: string): string {
  const date = new Date(occurredAt);
  const now = new Date();

  const dateOnly = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const todayOnly = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterdayOnly = new Date(todayOnly);
  yesterdayOnly.setDate(todayOnly.getDate() - 1);

  if (dateOnly.getTime() === todayOnly.getTime()) {
    return 'Today';
  }

  if (dateOnly.getTime() === yesterdayOnly.getTime()) {
    return 'Yesterday';
  }

  return date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function groupTransactionsByDate(transactions: Transaction[]): Array<{ label: string; items: Transaction[] }> {
  const groups = new Map<string, Transaction[]>();

  for (const transaction of transactions) {
    const label = getDateGroupLabel(transaction.occurred_at);
    const existingItems = groups.get(label) ?? [];
    existingItems.push(transaction);
    groups.set(label, existingItems);
  }

  return Array.from(groups.entries()).map(([label, items]) => ({ label, items }));
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
    return (transactions ?? [])
      .filter((transaction) => transaction.deleted_at === null)
      .sort((a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime());
  }, [transactions]);

  const groupedTransactions = useMemo(() => {
    return groupTransactionsByDate(visibleTransactions);
  }, [visibleTransactions]);

  if (isLoading) {
    return <p className='text-sm text-[var(--text-secondary)]'>Loading transactions...</p>;
  }

  if (isError) {
    return (
      <p className='text-sm text-[var(--negative)]' role='alert'>
        Could not load transactions.
      </p>
    );
  }

  if (visibleTransactions.length === 0) {
    return (
      <Card variant='elevated' className='border-dashed p-5'>
        <p className='m-0 text-sm text-[var(--text-secondary)]'>No transactions yet. Add your first one from the Add button.</p>
      </Card>
    );
  }

  return (
    <div className='space-y-5'>
      {groupedTransactions.map((group) => (
        <section key={group.label}>
          <h3 className='mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-muted)]'>{group.label}</h3>
          <ul className='m-0 flex list-none flex-col gap-3 p-0'>
            {group.items.map((transaction) => {
              const accountName = accountNameById.get(transaction.account_id) ?? 'Unknown account';
              const categoryName = transaction.category_id ? categoryNameById.get(transaction.category_id) : null;

              return (
                <li key={transaction.id}>
                  <Card className='p-4 active:scale-[0.98]'>
                    <div className='flex items-center gap-3'>
                      <div className='flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full bg-[var(--bg-elevated)] text-xl'>
                        {TYPE_ICON[transaction.type]}
                      </div>

                      <div className='min-w-0 flex-1'>
                        <p className='truncate text-sm font-semibold text-[var(--text-primary)]'>
                          {transaction.merchant || categoryName || TYPE_LABEL[transaction.type]}
                        </p>
                        <p className='mt-1 truncate text-xs text-[var(--text-muted)]'>
                          {(categoryName ?? TYPE_LABEL[transaction.type]) + ' · ' + accountName}
                        </p>
                      </div>

                      <div className='text-right'>
                        <p className={`text-sm font-bold ${getAmountToneClass(transaction.type)}`}>
                          {formatAmount(transaction.type, transaction.amount_paise)}
                        </p>
                        <div className='mt-1 flex items-center justify-end gap-2'>
                          <span className='text-xs text-[var(--text-muted)]'>{formatTime(transaction.occurred_at)}</span>
                          <Badge tone={getBadgeTone(transaction.type)}>{TYPE_LABEL[transaction.type]}</Badge>
                        </div>
                        <div className='mt-1'>
                          <Link
                            to={`/chat?transaction_id=${transaction.id}`}
                            className='text-xs font-semibold text-[var(--brand-primary)] hover:underline'
                          >
                            Chat about this
                          </Link>
                        </div>
                      </div>
                    </div>
                  </Card>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
