import { Plus, UserRound } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';

import { useAppDispatch, useAppSelector } from '../../../app/hooks';
import { useLazyGetMeQuery } from '../../../features/auth/authApi';
import { setUser } from '../../../features/auth/authSlice';
import { discardLegacyUnscopedChatDrafts } from '../../../features/chat/chatDrafts';
import { ACCOUNTS_NAV_ITEM, LAYOUT_UI_TEXT, NAV_ITEMS } from '../../../constants';
import { AffordableLogo, AffordableWordmark } from '../../brand/AffordableLogo';
import { CollapseToggle } from '../../atoms/CollapseToggle';
import { ThemeControl } from '../../molecules/ThemeControl';
import { CreateLauncher } from '../../organisms/CreateLauncher';

interface LayoutProps { children: ReactNode }

const MOBILE_ITEMS = [NAV_ITEMS[0], NAV_ITEMS[1], NAV_ITEMS[3], NAV_ITEMS[2]];
const MOBILE_COLUMNS = [1, 2, 4, 5] as const;

export function Layout({ children }: LayoutProps) {
  const dispatch = useAppDispatch();
  const accessToken = useAppSelector((state) => state.auth.accessToken);
  const currentUser = useAppSelector((state) => state.auth.user);
  const [loadMe] = useLazyGetMeQuery();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const location = useLocation();
  const isDashboard = location.pathname === '/dashboard';

  useEffect(() => {
    if (!isDashboard) return;
    document.body.dataset.routeSurface = 'dashboard';
    return () => { delete document.body.dataset.routeSurface; };
  }, [isDashboard]);

  useEffect(() => {
    if (!accessToken || currentUser) return;
    let isMounted = true;
    loadMe().unwrap().then((user) => {
      if (!isMounted) return;
      discardLegacyUnscopedChatDrafts();
      dispatch(setUser(user));
    }).catch(() => undefined);
    return () => { isMounted = false; };
  }, [accessToken, currentUser, dispatch, loadMe]);

  const asideWidth = isCollapsed ? 'md:w-[72px]' : 'md:w-60';
  const mainOffset = isCollapsed ? 'md:pl-[88px]' : 'md:pl-64';
  const userDisplayName = currentUser?.name?.trim() || LAYOUT_UI_TEXT.accountLabel;
  const initials = userDisplayName.split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('');

  return (
    <div className='min-h-[100dvh] bg-[var(--canvas)]'>
      <a href='#main-content' className='fixed left-3 top-3 z-[100] -translate-y-20 rounded-lg bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-[var(--canvas)] transition-transform focus:translate-y-0'>Skip to content</a>

      <aside className={[
        'fixed inset-y-3 left-3 z-40 hidden flex-col overflow-hidden rounded-2xl bg-[var(--brand-panel)] text-[var(--brand-panel-ink)] shadow-[var(--shadow-soft)] md:flex',
        'transition-[width] duration-200 ease-[var(--ease-out)]',
        asideWidth,
      ].join(' ')}>
        <Link
          to='/dashboard'
          aria-label='Go to Dashboard'
          className={['flex h-20 items-center gap-3 px-4 no-underline', isCollapsed ? 'justify-center' : ''].join(' ')}
        >
          {!isCollapsed ? <AffordableWordmark size={40} className='min-w-0' /> : <AffordableLogo size={40} />}
        </Link>

        <button
          type='button'
          className={[
            'mx-3 mb-4 inline-flex min-h-11 items-center rounded-xl bg-[var(--accent)] font-semibold text-[var(--on-accent)] transition-[background-color,transform] duration-150 hover:bg-[var(--accent-hover)] active:scale-[0.98]',
            isCollapsed ? 'justify-center px-0' : 'gap-2 px-3',
          ].join(' ')}
          aria-label='Add to your wallet'
          onClick={() => setIsCreateOpen(true)}
        >
          <Plus className='h-5 w-5' aria-hidden='true' /> {!isCollapsed ? 'Create' : null}
        </button>

        <nav className='flex-1 space-y-1 px-3' aria-label='Primary navigation'>
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return <NavLink key={item.path} to={item.path} title={isCollapsed ? item.label : undefined}
              className={({ isActive }) => [
                'flex min-h-11 items-center rounded-xl text-sm font-medium transition-[background-color,color] duration-150',
                isCollapsed ? 'justify-center px-0' : 'gap-3 px-3',
                isActive ? 'bg-[var(--brand-panel-active)] text-[var(--brand-panel-ink)]' : 'text-[var(--brand-panel-ink-muted)] hover:bg-[var(--brand-panel-hover)] hover:text-[var(--brand-panel-ink)]',
              ].join(' ')}>
              <Icon className='h-[19px] w-[19px] shrink-0' strokeWidth={2} aria-hidden='true' />
              {!isCollapsed ? item.label : null}
            </NavLink>;
          })}
          <NavLink to={ACCOUNTS_NAV_ITEM.path} title={isCollapsed ? 'Wallet' : undefined}
            className={({ isActive }) => [
              'flex min-h-11 items-center rounded-xl text-sm font-medium transition-[background-color,color] duration-150',
              isCollapsed ? 'justify-center px-0' : 'gap-3 px-3',
              isActive ? 'bg-[var(--brand-panel-active)] text-[var(--brand-panel-ink)]' : 'text-[var(--brand-panel-ink-muted)] hover:bg-[var(--brand-panel-hover)] hover:text-[var(--brand-panel-ink)]',
            ].join(' ')}>
            <ACCOUNTS_NAV_ITEM.icon className='h-[19px] w-[19px] shrink-0' strokeWidth={2} aria-hidden='true' />
            {!isCollapsed ? 'Wallet' : null}
          </NavLink>
        </nav>

        <div className='border-t border-[var(--brand-panel-border)] p-3'>
          <div className={['flex items-center gap-2', isCollapsed ? 'flex-col' : ''].join(' ')}>
            <NavLink to='/profile' aria-label='Open settings' className={[
              'flex min-h-11 min-w-0 flex-1 items-center rounded-xl text-[var(--brand-panel-ink-muted)] transition-[background-color,color] duration-150 hover:bg-[var(--brand-panel-hover)] hover:text-[var(--brand-panel-ink)]',
              isCollapsed ? 'w-11 justify-center' : 'gap-3 px-2',
            ].join(' ')}>
              <span className='flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--brand-panel-active)] text-xs font-semibold'>{initials || <UserRound className='h-4 w-4' />}</span>
              {!isCollapsed ? <span className='min-w-0'>
                <span className='block truncate text-sm font-medium'>{userDisplayName}</span>
                <span className='block text-xs opacity-60'>Settings</span>
              </span> : null}
            </NavLink>
            <ThemeControl compact tone='panel' />
            <CollapseToggle className='shrink-0 text-[var(--brand-panel-ink-muted)]' ariaLabel={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'} direction={isCollapsed ? 'right' : 'left'} onClick={() => setIsCollapsed((value) => !value)} />
          </div>
        </div>
      </aside>

      <main id='main-content' className={[
        'min-h-[100dvh] pb-[calc(5.5rem+env(safe-area-inset-bottom))] md:pb-4 md:pr-4 md:pt-4',
        'transition-[padding] duration-200 ease-[var(--ease-out)]',
        mainOffset,
      ].join(' ')}>{children}</main>

      <nav className='fixed inset-x-0 bottom-0 z-50 border-t border-[var(--border)] bg-[var(--surface)]/95 pb-[env(safe-area-inset-bottom)] md:hidden' aria-label='Primary navigation'>
        <ul className='m-0 grid h-[4.5rem] list-none grid-cols-5 p-0'>
          {MOBILE_ITEMS.map((item, index) => {
            const Icon = item.icon;
            return <li key={item.path} className='flex' style={{ gridColumn: MOBILE_COLUMNS[index] }}>
              <NavLink to={item.path} className={({ isActive }) => [
                'flex w-full flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors duration-150',
                isActive ? 'text-[var(--accent)]' : 'text-[var(--ink-muted)]',
              ].join(' ')}>
                <Icon className='h-5 w-5' strokeWidth={2} aria-hidden='true' /> {item.label}
              </NavLink>
            </li>;
          })}
          <li className='col-start-3 row-start-1 flex items-center justify-center'>
            <button type='button' aria-label='Add to your wallet' className='flex h-[52px] w-[52px] -translate-y-3 items-center justify-center rounded-2xl bg-[var(--accent)] text-[var(--on-accent)] shadow-[var(--shadow-raised)] transition-transform duration-200 active:scale-[0.97] active:shadow-[var(--shadow-inset)]' onClick={() => setIsCreateOpen(true)}>
              <Plus className='h-6 w-6' strokeWidth={2.3} aria-hidden='true' />
            </button>
          </li>
        </ul>
      </nav>

      <CreateLauncher isOpen={isCreateOpen} onClose={() => setIsCreateOpen(false)} />
    </div>
  );
}
