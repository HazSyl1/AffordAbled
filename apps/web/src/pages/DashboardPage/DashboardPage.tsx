import { AccountList } from '../../components/organisms/AccountList';
import { CreateAccountForm } from '../../components/organisms/CreateAccountForm';
import { Button } from '../../components/atoms/Button';
import { useLogoutMutation } from '../../features/auth/authApi';
import { clearCredentials } from '../../features/auth/authSlice';
import { useAppDispatch } from '../../app/hooks';

export function DashboardPage() {
  const dispatch = useAppDispatch();
  const [logout] = useLogoutMutation();

  const handleLogout = async () => {
    try {
      await logout().unwrap();
    } finally {
      dispatch(clearCredentials());
    }
  };

  return (
    <div className="mx-auto max-w-[640px] px-4 py-6">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-[var(--text-primary)]">Accounts</h1>
        <Button variant="secondary" onClick={handleLogout}>
          Log out
        </Button>
      </header>

      <section className="mb-6">
        <AccountList />
      </section>

      <section className="mb-6">
        <CreateAccountForm />
      </section>
    </div>
  );
}
