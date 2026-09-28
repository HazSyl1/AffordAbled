import { MessageCircle, Mic } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';

import { CollapseToggle } from '../../atoms/CollapseToggle';
import { useAppDispatch, useAppSelector } from '../../../app/hooks';
import { useLazyGetMeQuery } from '../../../features/auth/authApi';
import { setUser } from '../../../features/auth/authSlice';
import {
  ACCOUNTS_NAV_ITEM,
  APP_NAME,
  APP_TAGLINE,
  LAYOUT_UI_TEXT,
  NAV_ITEMS,
} from '../../../constants';

interface LayoutProps {
  children: ReactNode;
}

export function Layout({ children }: LayoutProps) {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const accessToken = useAppSelector((state) => state.auth.accessToken);
  const currentUser = useAppSelector((state) => state.auth.user);
  const [loadMe] = useLazyGetMeQuery();
  const [isDesktopSidebarCollapsed, setIsDesktopSidebarCollapsed] = useState(false);

  const desktopSidebarWidthClass = isDesktopSidebarCollapsed ? 'md:w-16' : 'md:w-56';
  const desktopMainOffsetClass = isDesktopSidebarCollapsed ? 'md:ml-24' : 'md:ml-64';
  const desktopMotionClass = 'md:transition-[width,margin] md:duration-500 md:ease-[cubic-bezier(0.22,1,0.36,1)]';
  const desktopNavItemClass = 'justify-start gap-2 px-3';
  const accountIconClass = 'h-[18px] w-[18px] shrink-0';
  const AccountIcon = ACCOUNTS_NAV_ITEM.icon;
  const userDisplayName = currentUser?.name?.trim() || LAYOUT_UI_TEXT.accountLabel;

  useEffect(() => {
    if (!accessToken || currentUser) {
      return;
    }

    let isMounted = true;

    loadMe()
      .unwrap()
      .then((user) => {
        if (isMounted) {
          dispatch(setUser(user));
        }
      })
      .catch(() => {
        // Keep existing fallback label if profile fetch fails.
      });

    return () => {
      isMounted = false;
    };
  }, [accessToken, currentUser, dispatch, loadMe]);

  return (
    <div className='min-h-screen bg-[var(--bg-app)]'>
      <aside
        className={[
          'fixed bottom-4 left-4 top-4 z-30 hidden rounded-3xl border border-[var(--bg-border)] bg-[color:rgba(15,15,17,0.86)] shadow-[0_18px_60px_rgba(0,0,0,0.35)] backdrop-blur-xl md:flex md:flex-col',
          desktopMotionClass,
          desktopSidebarWidthClass,
        ].join(' ')}
      >
        <div
          className={[
            'flex h-[6.5rem] flex-col justify-start pb-5 pt-7 transition-[padding] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]',
            isDesktopSidebarCollapsed ? 'px-3' : 'px-5',
          ].join(' ')}
        >
          <div className='relative h-[1.9rem]' title={APP_NAME}>
            <p
              className={[
                'absolute inset-0 font-extrabold uppercase leading-tight tracking-[0.04em] text-[var(--text-primary)] transition-opacity duration-150 ease-out',
                isDesktopSidebarCollapsed ? 'invisible opacity-0' : 'visible opacity-100 text-[1.32rem]',
              ].join(' ')}
            >
              {APP_NAME}
            </p>
            <p
              className={[
                'absolute inset-0 text-center text-lg font-extrabold uppercase leading-tight tracking-[0.04em] text-[var(--text-primary)] transition-opacity duration-150 ease-out',
                isDesktopSidebarCollapsed ? 'visible opacity-100' : 'invisible opacity-0',
              ].join(' ')}
            >
              AF
            </p>
          </div>
          <p
            className={[
              'mt-1 text-sm font-medium text-[var(--text-muted)] transition-opacity duration-150 ease-out',
              isDesktopSidebarCollapsed ? 'invisible opacity-0' : 'visible opacity-100',
            ].join(' ')}
          >
            {APP_TAGLINE}
          </p>
        </div>

        <nav className={['flex-1 space-y-2 transition-[padding] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]', isDesktopSidebarCollapsed ? 'px-2' : 'px-3'].join(' ')}>
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;

            return (
              <NavLink
                key={item.path}
                to={item.path}
                aria-label={item.label}
                className={({ isActive }) =>
                  [
                    'flex min-h-11 items-center rounded-xl text-sm font-semibold transition-colors',
                    desktopNavItemClass,
                    isActive
                      ? 'bg-[var(--brand-subtle)] text-[var(--brand-primary)]'
                      : 'text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]',
                  ].join(' ')
                }
              >
                <Icon className={accountIconClass} strokeWidth={2.1} aria-hidden='true' />
                {!isDesktopSidebarCollapsed ? item.label : null}
              </NavLink>
            );
          })}

          <NavLink
            to={ACCOUNTS_NAV_ITEM.path}
            aria-label={ACCOUNTS_NAV_ITEM.label}
            className={({ isActive }) =>
              [
                'flex min-h-11 items-center rounded-xl text-sm font-semibold transition-colors',
                desktopNavItemClass,
                isActive
                  ? 'bg-[var(--brand-subtle)] text-[var(--brand-primary)]'
                  : 'text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]',
              ].join(' ')
            }
          >
            <AccountIcon className={accountIconClass} strokeWidth={2.1} aria-hidden='true' />
            {!isDesktopSidebarCollapsed ? ACCOUNTS_NAV_ITEM.label : null}
          </NavLink>
        </nav>

        <div
          className={[
            'h-16 border-t border-[var(--bg-border)] py-3 transition-[padding] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]',
            isDesktopSidebarCollapsed ? 'px-2' : 'px-4',
          ].join(' ')}
        >
          <div className={['flex h-full items-center gap-2', isDesktopSidebarCollapsed ? 'justify-center' : 'justify-between'].join(' ')}>
            {!isDesktopSidebarCollapsed ? (
              <div className='min-w-0'>
                <p className='truncate text-xs text-[var(--text-muted)]'>{LAYOUT_UI_TEXT.signedInLabel}</p>
                <p className='truncate text-sm font-semibold text-[var(--text-secondary)]'>{userDisplayName}</p>
              </div>
            ) : null}

            <CollapseToggle
              className='shrink-0'
              ariaLabel={
                isDesktopSidebarCollapsed
                  ? LAYOUT_UI_TEXT.expandSidebarAriaLabel
                  : LAYOUT_UI_TEXT.collapseSidebarAriaLabel
              }
              direction={isDesktopSidebarCollapsed ? 'right' : 'left'}
              onClick={() => setIsDesktopSidebarCollapsed((previousValue) => !previousValue)}
            />
          </div>
        </div>
      </aside>

      <main
        className={[
          'pb-[calc(5rem+env(safe-area-inset-bottom))] md:mr-4 md:pb-0 md:pt-4',
          desktopMotionClass,
          desktopMainOffsetClass,
        ].join(' ')}
      >
        {children}
      </main>

      <nav className='fixed bottom-0 left-0 right-0 z-50 border-t border-[var(--bg-border)] bg-[color:rgba(15,15,17,0.9)] pb-[env(safe-area-inset-bottom)] backdrop-blur-xl md:hidden'>
        <ul
          className='m-0 grid h-16 list-none p-0'
          style={{ gridTemplateColumns: `repeat(${NAV_ITEMS.length}, minmax(0, 1fr))` }}
        >
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;

            return (
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
                      <Icon className='h-5 w-5' strokeWidth={2.1} aria-hidden='true' />
                      {isActive ? <span className='mt-1 text-[11px]'>{item.label}</span> : null}
                    </>
                  )}
                </NavLink>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className='md:hidden'>
        <button
          type='button'
          className='fixed bottom-[88px] right-4 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-[var(--brand-primary)] text-white shadow-[0_4px_20px_rgba(168,85,247,0.4)] active:scale-[0.98]'
          aria-label={LAYOUT_UI_TEXT.openChatAriaLabel}
          onClick={() => navigate('/chat')}
        >
          <MessageCircle className='h-6 w-6' strokeWidth={2.2} aria-hidden='true' />
        </button>
        <button
          type='button'
          className='fixed bottom-[152px] right-4 z-40 flex h-11 w-11 items-center justify-center rounded-full border border-[var(--bg-border)] bg-[var(--bg-elevated)] text-[var(--text-secondary)] active:scale-[0.98]'
          aria-label={LAYOUT_UI_TEXT.startVoiceAriaLabel}
        >
          <Mic className='h-5 w-5' strokeWidth={2.2} aria-hidden='true' />
        </button>
      </div>
    </div>
  );
}
