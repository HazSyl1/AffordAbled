import type { HTMLAttributes } from 'react';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'elevated' | 'hero';
}

const VARIANT_CLASSES: Record<NonNullable<CardProps['variant']>, string> = {
  default: 'border border-[var(--bg-border)] bg-[var(--bg-card)]',
  elevated: 'border border-[var(--bg-border)] bg-[var(--bg-elevated)]',
  hero:
    'border border-[color:rgba(168,85,247,0.35)] bg-[linear-gradient(160deg,rgba(168,85,247,0.22),rgba(15,15,17,0.95)_45%,rgba(15,15,17,1)_100%)]',
};

export function Card({ variant = 'default', className, ...rest }: CardProps) {
  const classes = ['rounded-2xl', VARIANT_CLASSES[variant], className].filter(Boolean).join(' ');
  return <div className={classes} {...rest} />;
}
