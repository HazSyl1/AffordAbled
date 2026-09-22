import type { ButtonHTMLAttributes } from 'react';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost';
  isLoading?: boolean;
}

const VARIANT_CLASSES: Record<NonNullable<ButtonProps['variant']>, string> = {
  primary:
    'bg-[var(--brand-primary)] text-white hover:bg-[var(--brand-hover)] active:bg-[var(--brand-active)] active:scale-[0.98]',
  secondary:
    'border border-[var(--bg-border)] bg-transparent text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] active:scale-[0.98]',
  ghost: 'bg-[var(--bg-elevated)] text-[var(--text-primary)] hover:bg-[var(--bg-card)] active:scale-[0.98]',
};

export function Button({ variant = 'primary', isLoading = false, disabled, children, className, ...rest }: ButtonProps) {
  const classes = [
    'inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-base font-semibold transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-60',
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
