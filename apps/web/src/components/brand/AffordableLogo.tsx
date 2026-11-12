import type { SVGProps } from 'react';
import { useTheme } from '../../features/theme/themeContext';
import './AffordableLogo.css';

export type AffordableLogoVariant = 'dark' | 'light' | 'glyph' | 'auto';

interface AffordableLogoProps extends Omit<SVGProps<SVGSVGElement>, 'width' | 'height'> {
  variant?: AffordableLogoVariant;
  size?: number;
}

export function AffordableLogo({ variant = 'auto', size = 40, ...props }: AffordableLogoProps) {
  const { mode } = useTheme();
  const themeVariant = variant === 'auto' || variant === 'glyph' ? mode : variant;
  const asset = variant === 'glyph'
    ? `/brand/affordable-glyph-${themeVariant}.svg`
    : `/brand/affordable-icon-${themeVariant}.svg`;

  return (
    <svg
      aria-hidden='true'
      viewBox='0 0 64 64'
      width={size}
      height={size}
      focusable='false'
      {...props}
      style={{ display: 'block', flexShrink: 0, ...props.style }}
    >
      <image href={asset} width='64' height='64' />
    </svg>
  );
}

export function AffordableWordmark({
  variant = 'auto',
  size = 40,
  supportingText = true,
  className = '',
}: {
  variant?: AffordableLogoVariant;
  size?: number;
  supportingText?: boolean;
  className?: string;
}) {
  return (
    <span className={`affordable-wordmark ${className}`}>
      <AffordableLogo variant={variant} size={size} />
      <span className='affordable-wordmark-copy'>
        <span className='affordable-wordmark-name'>AFFORDABLE</span>
        {supportingText && <span className='affordable-wordmark-tagline'>YOUR FINANCIAL AI</span>}
      </span>
    </span>
  );
}
