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
      <header className='-mx-4 mb-5 border-b border-[var(--bg-border)] bg-[var(--canvas)] px-4 py-4 md:mx-0 md:border-none md:bg-transparent md:px-0 md:py-0'>
        <div className='flex items-start justify-between gap-3'>
          <div>
            <h1 className='text-2xl font-semibold tracking-[-0.025em] text-[var(--text-primary)]'>Wallet</h1>
            <p className='mt-1 text-sm text-[var(--text-secondary)]'>Track the places where you keep money.</p>
          </div>

          <div className='flex gap-2'>
            <Button type='button' className='w-auto px-3 lg:hidden' onClick={() => setIsAddAccountSheetOpen(true)}>
              + Add
            </Button>
            <Button type='button' variant='secondary' className='w-auto px-3' onClick={() => navigate('/dashboard')}>
              Home
            </Button>
          </div>
        </div>
      </header>

      <section className='mb-6'>
        <Card variant='hero' className='p-5'>
          <p className='text-sm text-[var(--brand-panel-ink)]/60'>Combined balance</p>
          <p className='money mt-2 text-4xl font-semibold tracking-[-0.03em] text-[var(--brand-panel-ink)]'>{formatPaiseAsInr(totalBalancePaise)}</p>
          <p className='mt-1 text-sm text-[var(--brand-panel-ink)]/65'>
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
