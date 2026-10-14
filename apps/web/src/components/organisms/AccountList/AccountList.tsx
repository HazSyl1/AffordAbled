import { useListAccountsQuery, useSetDefaultAccountMutation } from '../../../features/accounts/accountsApi';
import { Card } from '../../atoms/Card';
import { Button } from '../../atoms/Button';
import { formatPaiseAsInr } from '../../../lib/money';
import { useState } from 'react';

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
  const [setDefaultAccount, { isLoading: isSettingDefault }] = useSetDefaultAccountMutation();
  const [actionError, setActionError] = useState<string | null>(null);

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
            <div className='grid min-w-0 grid-cols-[2.75rem_minmax(0,1fr)] items-center gap-x-3 gap-y-2 sm:grid-cols-[2.75rem_minmax(0,1fr)_auto]'>
              <div className='row-span-2 flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full bg-[var(--bg-elevated)] text-lg sm:row-span-1'>
                {getAccountIcon(account.type)}
              </div>

              <div className='col-start-2 min-w-0 sm:col-start-2'>
                <div className='flex flex-wrap items-center gap-2'>
                  <p className='truncate text-sm font-semibold text-[var(--text-primary)]'>{account.name}</p>
                  {account.is_default ? (
                    <span className='rounded-full bg-[var(--brand-subtle)] px-2 py-0.5 text-[11px] font-semibold text-[var(--brand-primary)]'>Default</span>
                  ) : null}
                </div>
                <p className='mt-1 text-xs capitalize text-[var(--text-muted)]'>{account.type}</p>
              </div>

              <div className='col-start-2 flex min-w-0 items-center justify-end gap-2 sm:col-start-3'>
                {!account.is_default && account.is_active ? (
                  <Button
                    type='button'
                    variant='primary'
                    className='min-h-8 w-auto shrink-0 px-2 py-1 text-xs'
                    isLoading={isSettingDefault}
                    onClick={() => {
                      setActionError(null);
                      void setDefaultAccount(account.id)
                        .unwrap()
                        .catch(() => setActionError('Could not set the default account.'));
                    }}
                  >
                    Make default
                  </Button>
                ) : null}
                <p className='shrink-0 whitespace-nowrap tabular-nums text-sm font-bold text-[var(--text-primary)]'>
                  {formatPaiseAsInr(account.balance_paise)}
                </p>
              </div>
            </div>
          </Card>
        </li>
      ))}
      {actionError ? <li className='text-sm text-[var(--negative)]' role='alert'>{actionError}</li> : null}
    </ul>
  );
}
