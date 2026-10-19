import { ArrowRight, Sparkles, Wallet } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { APP_NAME } from '../../../constants';

interface AuthPageShellProps {
  children: ReactNode;
  catchphrase: string;
  description: string;
}

const highlights = [
  'Log expenses by chat, voice, or receipt',
  'Keep accounts, transactions, and shared costs together',
  'See useful patterns in your spending',
];

export function AuthPageShell({ children, catchphrase, description }: AuthPageShellProps) {
  return (
    <main className='min-h-screen px-4 py-6 sm:px-6 sm:py-10'>
      <div className='mx-auto grid min-h-[calc(100vh-3rem)] w-full max-w-6xl overflow-hidden rounded-[2rem] border border-[var(--bg-border)] bg-[color:rgba(15,15,17,0.82)] shadow-[0_24px_100px_rgba(0,0,0,0.32)] lg:grid-cols-[1.05fr_0.95fr]'>
        <section className='relative hidden flex-col justify-between overflow-hidden p-10 lg:flex xl:p-14'>
          <div className='absolute -left-24 top-20 h-72 w-72 rounded-full bg-[var(--brand-primary)]/15 blur-3xl' aria-hidden='true' />
          <div className='absolute -bottom-32 right-0 h-96 w-96 rounded-full bg-blue-500/10 blur-3xl' aria-hidden='true' />
          <Link to='/' className='relative z-10 inline-flex w-fit items-center gap-3 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]'>
            <span className='flex h-11 w-11 items-center justify-center rounded-2xl bg-[var(--brand-primary)] text-white shadow-lg shadow-purple-950/40'>
              <Wallet className='h-6 w-6' aria-hidden='true' />
            </span>
            <span className='text-lg font-bold tracking-[0.12em] text-[var(--text-primary)]'>{APP_NAME}</span>
          </Link>

          <div className='relative z-10 max-w-xl py-14'>
            <span className='mb-5 inline-flex items-center gap-2 rounded-full border border-[var(--brand-primary)]/30 bg-[var(--brand-primary)]/10 px-3 py-1.5 text-xs font-semibold text-purple-200'>
              <Sparkles className='h-4 w-4' aria-hidden='true' /> Your money, with a little more clarity
            </span>
            <h1 className='text-4xl font-bold leading-tight tracking-tight text-[var(--text-primary)] xl:text-5xl'>{catchphrase}</h1>
            <p className='mt-5 max-w-lg text-base leading-7 text-[var(--text-secondary)]'>{description}</p>
            <ul className='mt-8 space-y-4'>
              {highlights.map((highlight) => (
                <li key={highlight} className='flex items-start gap-3 text-sm text-[var(--text-secondary)]'>
                  <span className='mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-400/15 text-emerald-300'>✓</span>
                  {highlight}
                </li>
              ))}
            </ul>
          </div>

          <p className='relative z-10 text-xs text-[var(--text-muted)]'>A calmer way to keep track of everyday money.</p>
        </section>

        <section className='flex min-w-0 flex-col justify-center border-[var(--bg-border)] p-5 sm:p-8 lg:border-l lg:p-10 xl:p-14'>
          <Link to='/' className='mb-8 inline-flex w-fit items-center gap-2 rounded-lg text-sm font-bold tracking-[0.1em] text-[var(--text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)] lg:hidden'>
            <span className='flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--brand-primary)] text-white'>
              <Wallet className='h-5 w-5' aria-hidden='true' />
            </span>
            {APP_NAME}
          </Link>
          <div className='mb-7 lg:hidden'>
            <h1 className='text-2xl font-bold leading-tight text-[var(--text-primary)]'>{catchphrase}</h1>
            <p className='mt-2 text-sm leading-6 text-[var(--text-secondary)]'>{description}</p>
          </div>
          {children}
          <p className='mt-8 flex items-center gap-2 text-xs text-[var(--text-muted)]'>
            <ArrowRight className='h-3.5 w-3.5' aria-hidden='true' /> Pick up where you left off, whenever you’re ready.
          </p>
        </section>
      </div>
    </main>
  );
}
