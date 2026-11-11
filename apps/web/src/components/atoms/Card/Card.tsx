import type { HTMLAttributes } from 'react';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'elevated' | 'hero';
}

const VARIANT_CLASSES: Record<NonNullable<CardProps['variant']>, string> = {
  default: 'surface-card bg-[var(--surface)] shadow-[var(--shadow-soft)]',
  elevated: 'surface-card bg-[var(--surface-subtle)] shadow-[var(--shadow-raised)]',
  hero:
    'surface-card surface-card--decorated bg-[var(--brand-panel)] text-[var(--brand-panel-ink)] shadow-[var(--shadow-soft)]',
};

export function Card({ variant = 'default', className, ...rest }: CardProps) {
  const classes = ['rounded-2xl', VARIANT_CLASSES[variant], className].filter(Boolean).join(' ');
  return <div className={classes} {...rest} />;
}
