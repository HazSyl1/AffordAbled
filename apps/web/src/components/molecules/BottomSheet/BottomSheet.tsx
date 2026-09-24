import { useEffect } from 'react';
import type { ReactNode } from 'react';

export interface BottomSheetProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
}

export function BottomSheet({ isOpen, onClose, title, children }: BottomSheetProps) {
  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen]);

  if (!isOpen) {
    return null;
  }

  return (
    <div className='fixed inset-0 z-50 flex items-end justify-center lg:items-center' role='dialog' aria-modal='true' aria-label={title ?? 'Bottom sheet'}>
      <button type='button' aria-label='Close' className='absolute inset-0 bg-black/60' onClick={onClose} />

      <div className='relative w-full rounded-t-3xl border-x border-t border-[var(--bg-border)] bg-[var(--bg-card)] pb-[env(safe-area-inset-bottom)] lg:max-w-2xl lg:rounded-3xl lg:border lg:pb-0 lg:shadow-[0_24px_60px_rgba(0,0,0,0.55)]'>
        <div className='flex justify-center pt-3 pb-4 lg:hidden'>
          <div className='h-1 w-10 rounded-full bg-[var(--bg-border)]' />
        </div>

        <div className='max-h-[80vh] overflow-y-auto px-4 pb-6 touch-scroll lg:max-h-[70vh] lg:px-5 lg:pb-5' onClick={(event) => event.stopPropagation()}>
          {title ? (
            <div className='mb-4 mt-4 flex items-center justify-between'>
              <h2 className='text-lg font-bold text-[var(--text-primary)]'>{title}</h2>
              <button
                type='button'
                aria-label='Close'
                className='flex h-9 w-9 items-center justify-center rounded-full border border-[var(--bg-border)] bg-[var(--bg-elevated)] text-lg text-[var(--text-secondary)] hover:bg-[var(--bg-card)]'
                onClick={onClose}
              >
                ×
              </button>
            </div>
          ) : null}

          {children}
        </div>
      </div>
    </div>
  );
}
