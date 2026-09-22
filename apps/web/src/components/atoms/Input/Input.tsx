import { forwardRef } from 'react';
import type { InputHTMLAttributes } from 'react';

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, ...rest },
  ref,
) {
  const classes = [
    'w-full rounded-[var(--input-radius)] border border-[var(--bg-border)] bg-[var(--bg-card)] px-3 py-2 text-[var(--text-primary)] outline-none focus:outline-2 focus:outline-[var(--brand-primary)] focus:outline-offset-1',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  return <input ref={ref} className={classes} {...rest} />;
});
