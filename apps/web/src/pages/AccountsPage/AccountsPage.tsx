import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Button } from '../../components/atoms/Button';
import { Card } from '../../components/atoms/Card';
import { BottomSheet } from '../../components/molecules/BottomSheet';
import { AccountList } from '../../components/organisms/AccountList';
import { CreateAccountForm } from '../../components/organisms/CreateAccountForm';
import { useListAccountsQuery } from '../../features/accounts/accountsApi';
import { SHEET_TITLES } from '../../constants';
import { formatPaiseAsInr } from '../../lib/money';

export function AccountsPage() {
  const navigate = useNavigate();
  const { data: accounts, isLoading: isLoadingAccounts } = useListAccountsQuery();
  const [isAddAccountSheetOpen, setIsAddAccountSheetOpen] = useState(false);

  const totalBalancePaise = useMemo(() => {
    return (accounts ?? []).reduce((total, account) => total + account.balance_paise, 0);
  }, [accounts]);

  return (
    <div className='mx-auto w-full max-w-[1100px] px-4 py-4 md:px-6 md:py-6'>
      <header className='sticky top-[env(safe-area-inset-top)] z-10 -mx-4 mb-5 border-b border-[var(--bg-border)] bg-[color:rgba(9,9,11,0.9)] px-4 py-4 backdrop-blur-xl md:static md:mx-0 md:border-none md:bg-transparent md:px-0 md:py-0'>
        <div className='flex items-start justify-between gap-3'>
          <div>
            <h1 className='text-xl font-bold text-[var(--text-primary)]'>Accounts</h1>
            <p className='text-xs text-[var(--text-secondary)]'>Track balances across all your wallets.</p>
          </div>

          <div className='flex gap-2'>
            <Button type='button' className='w-auto px-3 lg:hidden' onClick={() => setIsAddAccountSheetOpen(true)}>
              + Add
            </Button>
            <Button type='button' variant='secondary' className='w-auto px-3' onClick={() => navigate('/')}>
              Home
            </Button>
          </div>
        </div>
      </header>

      <section className='mb-6'>
        <Card variant='hero' className='p-5'>
          <p className='text-xs uppercase tracking-wide text-[var(--text-secondary)]'>Total Balance</p>
          <p className='mt-2 text-4xl font-bold text-[var(--text-primary)]'>{formatPaiseAsInr(totalBalancePaise)}</p>
          <p className='mt-1 text-sm text-[var(--text-secondary)]'>
            {isLoadingAccounts
              ? 'Loading accounts...'
              : `Across ${(accounts ?? []).length} ${(accounts ?? []).length === 1 ? 'account' : 'accounts'}`}
          </p>
        </Card>
      </section>

      <section className='mb-6'>
        <h2 className='mb-3 text-base font-semibold text-[var(--text-primary)]'>Your Accounts</h2>
        <AccountList />
      </section>

      <section className='hidden lg:block'>
        <Card className='p-5'>
          <CreateAccountForm />
        </Card>
      </section>

      <BottomSheet
        isOpen={isAddAccountSheetOpen}
        onClose={() => setIsAddAccountSheetOpen(false)}
        title={SHEET_TITLES.addAccount}
      >
        <CreateAccountForm onSuccess={() => setIsAddAccountSheetOpen(false)} showHeading={false} />
      </BottomSheet>
    </div>
  );
}
