import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, LogOut, Mail, Sparkles, UserRound } from 'lucide-react';
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
import { MemorySuggestionsPanel } from '../../components/molecules/MemorySuggestionsPanel/MemorySuggestionsPanel';
import { useListAccountsQuery } from '../../features/accounts/accountsApi';
import { useListCategoriesQuery } from '../../features/categories/categoriesApi';
import { useForgetMemoryMutation, useListMemoriesQuery, useListMemorySuggestionsQuery } from '../../features/memory/memoryApi';
import { describeMemory } from '../../features/memory/memoryText';

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
  const { data: memorySuggestions = [] } = useListMemorySuggestionsQuery();
  const { data: memories = [] } = useListMemoriesQuery();
  const { data: categories = [] } = useListCategoriesQuery();
  const { data: accounts = [] } = useListAccountsQuery();
  const [forgetMemory, { isLoading: isForgetting }] = useForgetMemoryMutation();
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memoriesOpen, setMemoriesOpen] = useState(false);
  const [activeMemoryIndex, setActiveMemoryIndex] = useState(0);
  const categoryNames = new Map(categories.map((category) => [category.id, category.name]));
  const accountNames = new Map(accounts.map((account) => [account.id, account.name]));
  const confirmedMemories = memories.filter((memory) => memory.status === 'confirmed');

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
    <div className='mx-auto w-full min-w-0 max-w-[900px] space-y-5 overflow-x-clip px-4 py-5 md:px-6 md:py-8'>
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

        <form onSubmit={(event) => { void handleSave(event); }} className='min-w-0 space-y-5 px-5 py-6 md:px-7'>
          <div>
            <h3 className='text-base font-semibold text-[var(--text-primary)]'>Personal details</h3>
            <p className='mt-1 text-sm text-[var(--text-muted)]'>Update how your name appears across AffordAbled.</p>
          </div>
          <div className='grid min-w-0 gap-4 md:grid-cols-2'>
            <label className='block min-w-0 space-y-2'>
              <span className='flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]'>
                <UserRound className='h-4 w-4' aria-hidden='true' /> Full name
              </span>
              <Input value={name} maxLength={120} required autoComplete='name' onChange={(event) => { setNameDraft(event.target.value); setSaved(false); }} />
            </label>
            <label className='block min-w-0 space-y-2'>
              <span className='flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]'>
                <CalendarDays className='h-4 w-4' aria-hidden='true' /> Date of birth
              </span>
              <Input type='date' className='block w-full min-w-0 max-w-full' value={dateOfBirth} max={new Date().toISOString().slice(0, 10)} onChange={(event) => { setDateOfBirthDraft(event.target.value); setSaved(false); }} />
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

      <MemorySuggestionsPanel suggestions={memorySuggestions} />

      <Card className='flex flex-col gap-4 p-5 md:flex-row md:items-center md:justify-between md:p-6'>
        <div>
          <h2 className='text-base font-semibold text-[var(--text-primary)]'>Done for now?</h2>
          <p className='mt-1 text-sm text-[var(--text-muted)]'>You can always pick up where you left off.</p>
        </div>
        <Button type='button' variant='secondary' className='w-full md:w-auto' isLoading={isLoggingOut} onClick={() => { void handleLogout(); }}>
          <LogOut className='h-4 w-4' aria-hidden='true' /> Log out
        </Button>
      </Card>

      <Card className='space-y-4 p-0'>
        <button
          type='button'
          className='flex w-full items-center justify-between gap-3 rounded-[var(--card-radius)] px-5 py-4 text-left transition-colors hover:bg-[var(--bg-elevated)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--brand-primary)] md:px-6'
          aria-expanded={memoriesOpen}
          aria-controls='remembered-preferences'
          onClick={() => setMemoriesOpen((open) => !open)}
        >
          <span>
            <span className='block text-base font-semibold text-[var(--text-primary)]'>What I remember</span>
            <span className='mt-1 block text-sm text-[var(--text-muted)]'>Your confirmed preferences · {confirmedMemories.length}</span>
          </span>
          <ChevronDown className={`h-5 w-5 shrink-0 text-[var(--text-muted)] transition-transform ${memoriesOpen ? 'rotate-180' : ''}`} aria-hidden='true' />
        </button>
        {memoriesOpen ? <div id='remembered-preferences' className='space-y-4 border-t border-[var(--bg-border)] px-5 py-4 md:px-6'>
          <p className='text-sm text-[var(--text-muted)]'>Only confirmed preferences guide future suggestions. You can forget one whenever it no longer fits.</p>
          {memoryError ? <p role='alert' className='text-sm text-[var(--negative)]'>{memoryError}</p> : null}
          {confirmedMemories.length === 0 ? (
            <p className='rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-4 text-sm text-[var(--text-muted)]'>No confirmed preferences yet.</p>
          ) : <>
            <div className='min-h-36 rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-4' aria-live='polite' aria-atomic='true'>
              <p className='text-sm leading-relaxed text-[var(--text-primary)]'>{describeMemory(confirmedMemories[activeMemoryIndex], categoryNames, accountNames)}</p>
              <p className='mt-3 text-xs text-[var(--text-muted)]'>Based on {confirmedMemories[activeMemoryIndex].evidence_count} reviewed example{confirmedMemories[activeMemoryIndex].evidence_count === 1 ? '' : 's'}.</p>
            </div>
            <div className='flex items-center justify-between gap-3'>
              <Button type='button' variant='secondary' className='w-auto min-h-10 px-3 py-2' aria-label='Previous memory' disabled={confirmedMemories.length < 2}
                onClick={() => setActiveMemoryIndex((index) => (index - 1 + confirmedMemories.length) % confirmedMemories.length)}>
                <ChevronLeft className='h-4 w-4' aria-hidden='true' /> Previous
              </Button>
              <span className='text-xs tabular-nums text-[var(--text-muted)]'>{activeMemoryIndex + 1} / {confirmedMemories.length}</span>
              <Button type='button' variant='secondary' className='w-auto min-h-10 px-3 py-2' aria-label='Next memory' disabled={confirmedMemories.length < 2}
                onClick={() => setActiveMemoryIndex((index) => (index + 1) % confirmedMemories.length)}>
                Next <ChevronRight className='h-4 w-4' aria-hidden='true' />
              </Button>
            </div>
            <Button type='button' variant='ghost' className='w-full sm:w-auto' isLoading={isForgetting} onClick={() => {
              const memory = confirmedMemories[activeMemoryIndex];
              setMemoryError(null);
              void forgetMemory(memory.id).unwrap().then(() => {
                setActiveMemoryIndex((index) => Math.max(0, Math.min(index, confirmedMemories.length - 2)));
              }).catch(() => setMemoryError('Could not forget this preference. Please try again.'));
            }}>Forget this preference</Button>
          </>}
        </div> : null}
      </Card>
    </div>
  );
}
