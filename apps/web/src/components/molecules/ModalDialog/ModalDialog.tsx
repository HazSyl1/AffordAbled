import { createPortal } from 'react-dom';
import type { ReactNode } from 'react';

import { useBodyScrollLock } from '../../../lib/useBodyScrollLock';
import { useModalFocus } from '../../../lib/useModalFocus';

interface ModalDialogProps {
  isOpen: boolean;
  onClose: () => void;
  label: string;
  children: ReactNode;
  className?: string;
}

export function ModalDialog({ isOpen, onClose, label, children, className = '' }: ModalDialogProps) {
  useBodyScrollLock(isOpen);
  const { containerRef, overlayRef } = useModalFocus(isOpen, onClose);

  if (!isOpen) return null;

  return createPortal(
    <div ref={overlayRef} className='fixed inset-0 z-[80] flex items-center justify-center overflow-y-auto bg-[var(--overlay)] p-4'>
      <button type='button' aria-label='Close dialog' className='absolute inset-0' onClick={onClose} />
      <div
        ref={containerRef}
        role='dialog'
        aria-modal='true'
        aria-label={label}
        tabIndex={-1}
        className={['relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow-raised)]', className].join(' ')}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
