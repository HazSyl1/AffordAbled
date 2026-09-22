import type { HTMLAttributes } from 'react';

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: 'neutral' | 'positive' | 'negative' | 'info';
}

const TONE_CLASS: Record<NonNullable<BadgeProps['tone']>, string> = {
  neutral: 'bg-[var(--bg-elevated)] text-[var(--text-secondary)]',
  positive: 'bg-[color:rgba(74,222,128,0.14)] text-[var(--positive)]',
  negative: 'bg-[color:rgba(248,113,113,0.14)] text-[var(--negative)]',
  info: 'bg-[color:rgba(96,165,250,0.14)] text-[var(--info)]',
};

export function Badge({ tone = 'neutral', className, ...rest }: BadgeProps) {
  const classes = [
    'inline-flex min-h-6 items-center rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-wide',
    TONE_CLASS[tone],
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return <span className={classes} {...rest} />;
}
