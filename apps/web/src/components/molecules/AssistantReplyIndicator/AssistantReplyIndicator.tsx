import type { HTMLAttributes } from 'react';

interface AssistantReplyIndicatorProps extends HTMLAttributes<HTMLDivElement> {
  label: string;
}

export function AssistantReplyIndicator({ label, className, ...rest }: AssistantReplyIndicatorProps) {
  const classes = [
    'mr-auto flex max-w-[92%] items-center gap-2 rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] px-3 py-2 text-xs text-[var(--text-secondary)]',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={classes} role='status' aria-live='polite' {...rest}>
      <span>{label}</span>
      <span className='inline-flex items-end gap-1' aria-hidden='true'>
        <span className='h-1.5 w-1.5 rounded-full bg-[var(--brand-primary)] animate-bounce [animation-delay:-0.3s]' />
        <span className='h-1.5 w-1.5 rounded-full bg-[var(--brand-primary)] animate-bounce [animation-delay:-0.15s]' />
        <span className='h-1.5 w-1.5 rounded-full bg-[var(--brand-primary)] animate-bounce' />
      </span>
    </div>
  );
}
