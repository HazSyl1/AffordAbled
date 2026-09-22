import type { ButtonHTMLAttributes } from 'react';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary';
  isLoading?: boolean;
}

const VARIANT_CLASSES: Record<NonNullable<ButtonProps['variant']>, string> = {
  primary: 'bg-[var(--brand-primary)] text-white hover:bg-[var(--brand-hover)]',
  secondary:
    'bg-transparent text-[var(--text-primary)] border border-[var(--bg-border)] hover:bg-[var(--bg-elevated)]',
};

export function Button({ variant = 'primary', isLoading = false, disabled, children, className, ...rest }: ButtonProps) {
  const classes = [
    'inline-flex items-center justify-center gap-2 rounded-[var(--btn-radius)] px-4 py-2 font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60',
    VARIANT_CLASSES[variant],
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <button className={classes} disabled={disabled || isLoading} {...rest}>
      {isLoading ? 'Please wait…' : children}
    </button>
  );
}
