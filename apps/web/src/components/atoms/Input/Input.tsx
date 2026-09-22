import { forwardRef } from 'react';
import type { InputHTMLAttributes } from 'react';

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ className, ...rest }, ref) {
  const classes = [
    'w-full min-h-12 rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] px-3 py-3 text-base text-[var(--text-primary)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--brand-primary)] focus:ring-1 focus:ring-[var(--brand-primary)]',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return <input ref={ref} className={classes} {...rest} />;
});
