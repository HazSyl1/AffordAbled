import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';

import {
  ACCOUNTS_NAV_ITEM,
  APP_NAME,
  APP_TAGLINE,
  NAV_ITEMS,
} from '../../../constants';

interface LayoutProps {
  children: ReactNode;
}

export function Layout({ children }: LayoutProps) {
  return (
    <div className='min-h-screen bg-[var(--bg-app)]'>
      <aside className='fixed left-0 top-0 hidden h-full w-60 border-r border-[var(--bg-border)] bg-[var(--bg-card)] lg:flex lg:flex-col'>
        <div className='px-5 pb-5 pt-7'>
          <p className='text-2xl font-extrabold uppercase tracking-[0.12em] text-[var(--text-primary)]'>{APP_NAME}</p>
          <p className='mt-1 text-sm font-medium text-[var(--text-muted)]'>{APP_TAGLINE}</p>
        </div>

        <nav className='flex-1 space-y-2 px-3'>
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                [
                  'flex min-h-11 items-center gap-2 rounded-xl px-3 text-sm font-semibold transition-colors',
                  isActive
                    ? 'bg-[var(--brand-subtle)] text-[var(--brand-primary)]'
                    : 'text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]',
                ].join(' ')
              }
            >
              <span aria-hidden='true'>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}

          <NavLink
            to={ACCOUNTS_NAV_ITEM.path}
            className={({ isActive }) =>
              [
                'flex min-h-11 items-center gap-2 rounded-xl px-3 text-sm font-semibold transition-colors',
                isActive
                  ? 'bg-[var(--brand-subtle)] text-[var(--brand-primary)]'
                  : 'text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]',
              ].join(' ')
            }
          >
            <span aria-hidden='true'>{ACCOUNTS_NAV_ITEM.icon}</span>
            {ACCOUNTS_NAV_ITEM.label}
          </NavLink>
        </nav>

        <div className='border-t border-[var(--bg-border)] px-5 py-4'>
          <p className='text-xs text-[var(--text-muted)]'>Signed in</p>
          <p className='text-sm font-semibold text-[var(--text-secondary)]'>Personal Wallet</p>
        </div>
      </aside>

      <main className='pb-[calc(5rem+env(safe-area-inset-bottom))] lg:ml-60 lg:pb-8'>{children}</main>

      <nav className='fixed bottom-0 left-0 right-0 z-50 border-t border-[var(--bg-border)] bg-[color:rgba(15,15,17,0.9)] pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden'>
        <ul className='m-0 grid h-16 list-none grid-cols-4 p-0'>
          {NAV_ITEMS.map((item) => (
            <li key={item.path} className='flex'>
              <NavLink
                to={item.path}
                className={({ isActive }) =>
                  [
                    'flex w-full flex-col items-center justify-center text-xs font-semibold transition-colors',
                    isActive ? 'text-[var(--brand-primary)]' : 'text-[var(--text-muted)]',
                  ].join(' ')
                }
              >
                {({ isActive }) => (
                  <>
                    <span className='text-lg leading-none' aria-hidden='true'>
                      {item.icon}
                    </span>
                    {isActive ? <span className='mt-1 text-[11px]'>{item.label}</span> : null}
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className='lg:hidden'>
        <button
          type='button'
          className='fixed bottom-[88px] right-4 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-[var(--brand-primary)] text-2xl text-white shadow-[0_4px_20px_rgba(168,85,247,0.4)] active:scale-[0.98]'
          aria-label='Open chat'
        >
          💬
        </button>
        <button
          type='button'
          className='fixed bottom-[152px] right-4 z-40 flex h-11 w-11 items-center justify-center rounded-full border border-[var(--bg-border)] bg-[var(--bg-elevated)] text-lg text-[var(--text-secondary)] active:scale-[0.98]'
          aria-label='Start voice input'
        >
          🎤
        </button>
      </div>
    </div>
  );
}
