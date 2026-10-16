import { CalendarDays, LogOut, Mail, Sparkles, UserRound } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';

import { useAppDispatch, useAppSelector } from '../../app/hooks';
import { Button } from '../../components/atoms/Button';
import { Card } from '../../components/atoms/Card';
import { Input } from '../../components/atoms/Input';
import {
  useLazyGetProfileTransactionSummaryQuery,
  useLogoutMutation,
  useUpdateProfileMutation,
} from '../../features/auth/authApi';
import { clearCredentials, setUser } from '../../features/auth/authSlice';
import { apiClient } from '../../lib/apiClient';

function initials(name: string): string {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? '').join('') || 'U';
}

export function ProfilePage() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const currentUser = useAppSelector((state) => state.auth.user);
  const [nameDraft, setNameDraft] = useState<string | null>(null);
  const [dateOfBirthDraft, setDateOfBirthDraft] = useState<string | null>(null);
  const name = nameDraft ?? currentUser?.name ?? '';
  const dateOfBirth = dateOfBirthDraft ?? currentUser?.date_of_birth ?? '';
  const normalizedName = name.trim().replace(/\s+/g, ' ');
  const hasChanges = Boolean(
    currentUser &&
      (normalizedName !== currentUser.name.trim().replace(/\s+/g, ' ') ||
        dateOfBirth !== (currentUser.date_of_birth ?? '')),
  );
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [updateProfile, { isLoading: isSaving }] = useUpdateProfileMutation();
  const [logout, { isLoading: isLoggingOut }] = useLogoutMutation();
  const [loadSummary, { data: summary, isFetching: isLoadingSummary, isError: summaryFailed }] =
    useLazyGetProfileTransactionSummaryQuery();

  useEffect(() => {
    if (currentUser?.id) {
      void loadSummary();
    }
  }, [currentUser?.id, loadSummary]);

  const handleSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (normalizedName.length < 2) {
      setFormError('Enter a name with at least 2 characters.');
      return;
    }
    if (dateOfBirth && dateOfBirth >= new Date().toISOString().slice(0, 10)) {
      setFormError('Date of birth must be in the past.');
      return;
    }
    setFormError(null);
    setSaved(false);
    try {
      const updated = await updateProfile({ name: normalizedName, date_of_birth: dateOfBirth || null }).unwrap();
      dispatch(setUser(updated));
      setNameDraft(null);
      setDateOfBirthDraft(null);
      setSaved(true);
    } catch {
      setFormError('Could not save your profile. Please try again.');
    }
  };

  const handleLogout = async () => {
    await logout().unwrap().catch(() => undefined);
    dispatch(clearCredentials());
    dispatch(apiClient.util.resetApiState());
    navigate('/login', { replace: true });
  };

  const displayName = currentUser?.name?.trim() || 'Your profile';

  return (
    <div className='mx-auto w-full max-w-[900px] space-y-5 px-4 py-5 md:px-6 md:py-8'>
      <header>
        <p className='text-xs font-semibold uppercase tracking-[0.18em] text-[var(--brand-primary)]'>Your space</p>
        <h1 className='mt-1 text-2xl font-bold text-[var(--text-primary)]'>Profile</h1>
        <p className='mt-1 text-sm text-[var(--text-muted)]'>A home for the details behind your wallet.</p>
      </header>

      <Card className='overflow-hidden p-0'>
        <div className='bg-[color:rgba(168,85,247,0.10)] px-5 py-6 md:px-7'>
          <div className='flex items-center gap-4'>
            <div className='flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-[var(--brand-primary)] text-xl font-bold text-white' aria-hidden='true'>
              {initials(displayName)}
            </div>
            <div className='min-w-0'>
              <h2 className='truncate text-xl font-bold text-[var(--text-primary)]'>{displayName}</h2>
              <p className='mt-1 truncate text-sm text-[var(--text-secondary)]'>{currentUser?.email ?? 'Loading account…'}</p>
            </div>
          </div>
        </div>

        <form onSubmit={(event) => { void handleSave(event); }} className='space-y-5 px-5 py-6 md:px-7'>
          <div>
            <h3 className='text-base font-semibold text-[var(--text-primary)]'>Personal details</h3>
            <p className='mt-1 text-sm text-[var(--text-muted)]'>Update how your name appears across AffordAbled.</p>
          </div>
          <div className='grid gap-4 md:grid-cols-2'>
            <label className='block space-y-2'>
              <span className='flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]'>
                <UserRound className='h-4 w-4' aria-hidden='true' /> Full name
              </span>
              <Input value={name} maxLength={120} required autoComplete='name' onChange={(event) => { setNameDraft(event.target.value); setSaved(false); }} />
            </label>
            <label className='block space-y-2'>
              <span className='flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]'>
                <CalendarDays className='h-4 w-4' aria-hidden='true' /> Date of birth
              </span>
              <Input type='date' value={dateOfBirth} max={new Date().toISOString().slice(0, 10)} onChange={(event) => { setDateOfBirthDraft(event.target.value); setSaved(false); }} />
            </label>
          </div>
          <div>
            <p className='flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]'>
              <Mail className='h-4 w-4' aria-hidden='true' /> Email address
            </p>
            <p className='mt-2 rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] px-3 py-3 text-sm text-[var(--text-muted)]'>
              {currentUser?.email ?? 'Loading…'}
            </p>
          </div>
          {formError ? <p role='alert' className='text-sm text-[var(--negative)]'>{formError}</p> : null}
          {saved ? <p role='status' className='text-sm text-[var(--positive)]'>Profile saved.</p> : null}
          {hasChanges ? (
            <div className='flex justify-end'>
              <Button type='submit' className='w-auto min-w-36' isLoading={isSaving}>
                Save changes
              </Button>
            </div>
          ) : null}
        </form>
      </Card>

      <Card className='p-5 md:p-6'>
        <div className='flex items-start gap-3'>
          <div className='flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--brand-subtle)] text-[var(--brand-primary)]'>
            <Sparkles className='h-5 w-5' aria-hidden='true' />
          </div>
          <div className='min-w-0'>
            <h2 className='text-base font-semibold text-[var(--text-primary)]'>{displayName}'s transaction summary</h2>
            <p className='mt-1 text-xs text-[var(--text-muted)]'>A little observation from your latest five transactions.</p>
            <p className='mt-3 text-sm leading-relaxed text-[var(--text-secondary)]' aria-live='polite'>
              {summary?.message ?? (summaryFailed ? 'Your summary is unavailable right now.' : isLoadingSummary ? 'Finding your wallet’s latest plotline…' : 'Your wallet has a story to tell.')}
            </p>
          </div>
        </div>
      </Card>

      <Card className='flex flex-col gap-4 p-5 md:flex-row md:items-center md:justify-between md:p-6'>
        <div>
          <h2 className='text-base font-semibold text-[var(--text-primary)]'>Done for now?</h2>
          <p className='mt-1 text-sm text-[var(--text-muted)]'>You can always pick up where you left off.</p>
        </div>
        <Button type='button' variant='secondary' className='w-full md:w-auto' isLoading={isLoggingOut} onClick={() => { void handleLogout(); }}>
          <LogOut className='h-4 w-4' aria-hidden='true' /> Log out
        </Button>
      </Card>
    </div>
  );
}
