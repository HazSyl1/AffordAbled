import { useListAccountsQuery } from '../../../features/accounts/accountsApi';
import { Card } from '../../atoms/Card';
import { formatPaiseAsInr } from '../../../lib/money';

function getAccountIcon(type: string): string {
  if (type === 'bank') {
    return '🏦';
  }

  if (type === 'cash') {
    return '💵';
  }

  if (type === 'card') {
    return '💳';
  }

  return '👛';
}

export function AccountList() {
  const { data: accounts, isLoading, isError } = useListAccountsQuery();

  if (isLoading) {
    return <p className='text-sm text-[var(--text-secondary)]'>Loading accounts...</p>;
  }

  if (isError) {
    return (
      <p className='text-sm text-[var(--negative)]' role='alert'>
        Could not load accounts.
      </p>
    );
  }

  if (!accounts || accounts.length === 0) {
    return <p className='text-sm text-[var(--text-secondary)]'>No accounts yet. Tap Add to create your first account.</p>;
  }

  return (
    <ul className='m-0 flex list-none flex-col gap-3 p-0'>
      {accounts.map((account) => (
        <li key={account.id}>
          <Card className='p-4 active:scale-[0.98]'>
            <div className='flex items-center gap-3'>
              <div className='flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full bg-[var(--bg-elevated)] text-lg'>
                {getAccountIcon(account.type)}
              </div>

              <div className='min-w-0 flex-1'>
                <p className='truncate text-sm font-semibold text-[var(--text-primary)]'>{account.name}</p>
                <p className='mt-1 text-xs capitalize text-[var(--text-muted)]'>{account.type}</p>
              </div>

              <p className='tabular-nums text-sm font-bold text-[var(--text-primary)]'>{formatPaiseAsInr(account.balance_paise)}</p>
            </div>
          </Card>
        </li>
      ))}
    </ul>
  );
}
