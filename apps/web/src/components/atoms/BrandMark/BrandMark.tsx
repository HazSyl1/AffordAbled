import type { ImgHTMLAttributes } from 'react';

export function BrandMark({ className, ...props }: ImgHTMLAttributes<HTMLImageElement>) {
  return <img src='/app-icon.png' alt='' aria-hidden='true' className={className} {...props} />;
}

