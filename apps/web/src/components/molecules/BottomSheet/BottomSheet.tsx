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
    <div className='fixed inset-0 z-50 lg:hidden' role='dialog' aria-modal='true' aria-label={title ?? 'Bottom sheet'}>
      <button type='button' aria-label='Close' className='absolute inset-0 bg-black/60' onClick={onClose} />

      <div className='absolute inset-x-0 bottom-0 rounded-t-3xl border-x border-t border-[var(--bg-border)] bg-[var(--bg-card)] pb-[env(safe-area-inset-bottom)]'>
        <div className='flex justify-center pt-3 pb-4'>
          <div className='h-1 w-10 rounded-full bg-[var(--bg-border)]' />
        </div>

        <div className='max-h-[80vh] overflow-y-auto px-4 pb-6 touch-scroll' onClick={(event) => event.stopPropagation()}>
          {title ? <h2 className='mb-4 text-lg font-bold text-[var(--text-primary)]'>{title}</h2> : null}
          {children}
        </div>
      </div>
    </div>
  );
}
