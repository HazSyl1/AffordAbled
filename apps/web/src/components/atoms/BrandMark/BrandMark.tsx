import type { SVGProps } from 'react';
import { AffordableLogo } from '../../brand/AffordableLogo';

export function BrandMark({ className, ...props }: SVGProps<SVGSVGElement>) {
  const { width = 40, height = width, style, ...logoProps } = props;
  const size = typeof width === 'number' ? width : Number.parseFloat(width) || 40;
  return <AffordableLogo className={className} size={size} style={{ width, height, ...style }} {...logoProps} />;
}

