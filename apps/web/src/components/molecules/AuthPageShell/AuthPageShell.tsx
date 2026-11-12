import { ArrowLeft, Check } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { AffordableWordmark } from '../../brand/AffordableLogo';
import { ThemeControl } from '../ThemeControl';

interface AuthPageShellProps {
  children: ReactNode;
  catchphrase: string;
  description: string;
}

const highlights = [
  'Review every AI-assisted change',
  'Keep personal and shared money together',
  'Use chat, voice, receipts, or manual entry',
];

export function AuthPageShell({ children, catchphrase, description }: AuthPageShellProps) {
  return (
    <main className='min-h-[100dvh] bg-[var(--canvas)] p-4 sm:p-6'>
      <div className='mx-auto grid min-h-[calc(100dvh-2rem)] w-full max-w-6xl overflow-hidden rounded-2xl bg-[var(--surface)] shadow-[var(--shadow-soft)] sm:min-h-[calc(100dvh-3rem)] lg:grid-cols-[0.95fr_1.05fr]'>
        <section className='hidden flex-col justify-between bg-[var(--brand-panel)] p-10 text-[var(--brand-panel-ink)] lg:flex xl:p-14'>
          <Link to='/' className='inline-flex w-fit items-center gap-3 rounded-lg'>
            <AffordableWordmark size={40} />
          </Link>
          <div className='max-w-lg py-14'>
            <h1 className='text-5xl font-semibold leading-[1.05] tracking-[-0.04em]'>{catchphrase}</h1>
            <p className='mt-5 text-base leading-7 text-[var(--brand-panel-ink)]/65'>{description}</p>
            <ul className='mt-8 space-y-4'>
              {highlights.map((highlight) => <li key={highlight} className='flex items-center gap-3 text-sm text-[var(--brand-panel-ink-muted)]'><span className='flex h-6 w-6 items-center justify-center rounded-full bg-[var(--brand-panel-active)]'><Check className='h-3.5 w-3.5' aria-hidden='true' /></span>{highlight}</li>)}
            </ul>
          </div>
          <p className='text-xs text-[var(--brand-panel-ink)]/45'>Clarity before every important action.</p>
        </section>

        <section className='flex min-w-0 flex-col p-5 sm:p-8 lg:p-12 xl:p-16'>
          <div className='flex items-center justify-between'>
            <Link to='/' className='inline-flex min-h-11 items-center gap-2 rounded-lg text-sm font-medium text-[var(--ink-secondary)] hover:text-[var(--ink)] lg:hidden'><ArrowLeft className='h-4 w-4' aria-hidden='true' /> Home</Link>
            <div className='ml-auto'><ThemeControl compact /></div>
          </div>
          <div className='mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-10'>
            <div className='mb-8 lg:hidden'>
              <h1 className='text-3xl font-semibold tracking-[-0.03em] text-[var(--ink)]'>{catchphrase}</h1>
              <p className='mt-3 text-sm leading-6 text-[var(--ink-secondary)]'>{description}</p>
            </div>
            {children}
          </div>
        </section>
      </div>
    </main>
  );
}
