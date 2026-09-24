import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { ButtonHTMLAttributes } from 'react';

interface CollapseToggleProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> {
  ariaLabel: string;
  direction: 'left' | 'right';
}

export function CollapseToggle({ ariaLabel, direction, className, ...rest }: CollapseToggleProps) {
  const Icon = direction === 'left' ? ChevronLeft : ChevronRight;

  return (
    <button
      type='button'
      className={[
        'inline-flex h-10 w-10 items-center justify-center rounded-full border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-elevated)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      aria-label={ariaLabel}
      {...rest}
    >
      <Icon className='h-5 w-5' strokeWidth={2.2} aria-hidden='true' />
    </button>
  );
}
