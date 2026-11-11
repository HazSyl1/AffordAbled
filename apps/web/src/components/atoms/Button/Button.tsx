import type { ButtonHTMLAttributes } from 'react';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost';
  isLoading?: boolean;
}

const VARIANT_CLASSES: Record<NonNullable<ButtonProps['variant']>, string> = {
  primary:
    'bg-[var(--accent)] text-[var(--on-accent)] shadow-[var(--shadow-soft)] hover:bg-[var(--accent-hover)] hover:shadow-[var(--shadow-raised)] active:bg-[var(--accent-active)] active:scale-[0.98] active:shadow-[var(--shadow-inset)]',
  secondary:
    'border border-[color:var(--border)] bg-[var(--surface)] text-[var(--ink)] shadow-[var(--shadow-soft)] hover:bg-[var(--surface-subtle)] hover:shadow-[var(--shadow-raised)] active:scale-[0.98] active:shadow-[var(--shadow-inset)]',
  ghost: 'bg-transparent text-[var(--ink-secondary)] hover:bg-[var(--surface-subtle)] hover:text-[var(--ink)] active:scale-[0.98]',
};

export function Button({ variant = 'primary', isLoading = false, disabled, children, className, ...rest }: ButtonProps) {
  const classes = [
    'inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-[var(--btn-radius)] px-4 py-2.5 text-sm font-semibold transition-[background-color,color,border-color,transform] duration-150 ease-[var(--ease-out)] disabled:cursor-not-allowed disabled:opacity-50',
    VARIANT_CLASSES[variant],
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <button className={classes} disabled={disabled || isLoading} {...rest}>
      {isLoading ? 'Please wait...' : children}
    </button>
  );
}
