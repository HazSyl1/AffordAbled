import { Moon, Sun } from 'lucide-react';

import { useTheme, type ThemeMode } from '../../../features/theme/themeContext';

const OPTIONS: { value: ThemeMode; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
];

export function ThemeControl({ compact = false, tone = 'default' }: { compact?: boolean; tone?: 'default' | 'panel' }) {
  const { mode, setMode } = useTheme();

  if (compact) {
    const next: ThemeMode = mode === 'light' ? 'dark' : 'light';
    const Icon = mode === 'light' ? Sun : Moon;
    return (
      <button
        type='button'
        className={[
          'inline-flex h-8 w-14 items-center rounded-full p-1 transition-[background-color,color,box-shadow] duration-150',
          tone === 'panel'
            ? 'bg-[var(--brand-panel-hover)] text-[var(--brand-panel-ink-muted)] hover:text-[var(--brand-panel-ink)]'
            : 'bg-[var(--surface-subtle)] text-[var(--ink-muted)] hover:text-[var(--ink)]',
        ].join(' ')}
        role='switch'
        aria-checked={mode === 'dark'}
        aria-label={`Appearance: ${mode}. Switch to ${next}.`}
        title={`Appearance: ${mode}`}
        onClick={() => setMode(next)}
      >
        <span className={[
          'flex h-6 w-6 items-center justify-center rounded-full bg-[var(--surface)] shadow-[var(--shadow-soft)] transition-transform duration-200 ease-[var(--ease-out)]',
          mode === 'dark' ? 'translate-x-6' : 'translate-x-0',
        ].join(' ')}>
          <Icon className='h-3.5 w-3.5' aria-hidden='true' />
        </span>
      </button>
    );
  }

  return (
    <div className='grid grid-cols-2 gap-1 rounded-xl bg-[var(--surface-subtle)] p-1' role='group' aria-label='Appearance'>
      {OPTIONS.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type='button'
          aria-pressed={mode === value}
          className={[
            'inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-3 text-sm font-medium transition-[background-color,color,box-shadow] duration-150',
            mode === value ? 'bg-[var(--surface)] text-[var(--ink)] shadow-[var(--shadow-soft)]' : 'text-[var(--ink-muted)] hover:text-[var(--ink)]',
          ].join(' ')}
          onClick={() => setMode(value)}
        >
          <Icon className='h-4 w-4' aria-hidden='true' /> {label}
        </button>
      ))}
    </div>
  );
}

