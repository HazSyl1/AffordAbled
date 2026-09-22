import { useListAccountsQuery } from '../../../features/accounts/accountsApi';
import { formatPaiseAsInr } from '../../../lib/money';

export function AccountList() {
  const { data: accounts, isLoading, isError } = useListAccountsQuery();

  if (isLoading) {
    return <p className="text-[var(--text-secondary)]">Loading accounts…</p>;
  }

  if (isError) {
    return (
      <p className="text-[var(--negative)]" role="alert">
        Could not load accounts.
      </p>
    );
  }

  if (!accounts || accounts.length === 0) {
    return <p className="text-[var(--text-secondary)]">No accounts yet — add your first one below.</p>;
  }

  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {accounts.map((account) => (
        <li
          key={account.id}
          className="grid grid-cols-[1fr_auto_auto] items-center gap-3 rounded-[var(--card-radius)] border border-[var(--bg-border)] bg-[var(--bg-card)] p-3"
        >
          <span className="font-semibold text-[var(--text-primary)]">{account.name}</span>
          <span className="text-sm capitalize text-[var(--text-secondary)]">{account.type}</span>
          <span className="tabular-nums text-[var(--text-primary)]">{formatPaiseAsInr(account.balance_paise)}</span>
        </li>
      ))}
    </ul>
  );
}
