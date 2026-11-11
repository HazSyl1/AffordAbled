import type { SVGProps } from 'react';

export function BrandMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox='0 0 32 32' fill='none' aria-hidden='true' {...props}>
      <path d='M7.5 24.5 13.8 7.8c.8-2.1 3.8-2.1 4.6 0l6.1 16.7' stroke='currentColor' strokeWidth='3.2' strokeLinecap='round' />
      <path d='M10.7 18.2h10.7' stroke='currentColor' strokeWidth='3.2' strokeLinecap='round' />
      <path d='M5.5 26.5h21' stroke='currentColor' strokeWidth='2' strokeLinecap='round' opacity='.45' />
    </svg>
  );
}

