import { forwardRef } from 'react';
import type { InputHTMLAttributes } from 'react';

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ className, ...rest }, ref) {
  const classes = [
    'min-h-11 w-full rounded-[var(--input-radius)] border border-[color:var(--border)] bg-[var(--surface)] px-3 py-2.5 text-base text-[var(--ink)] shadow-[var(--shadow-inset)] outline-none transition-[border-color,box-shadow] duration-200 placeholder:text-[var(--ink-muted)] focus:border-[var(--accent)] focus:shadow-[0_0_0_3px_var(--accent-soft),var(--shadow-inset)]',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return <input ref={ref} className={classes} {...rest} />;
});
