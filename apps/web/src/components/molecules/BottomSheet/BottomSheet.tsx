import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

export interface BottomSheetProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
}

export function BottomSheet({ isOpen, onClose, title, children }: BottomSheetProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [draggedHeight, setDraggedHeight] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isDismissing, setIsDismissing] = useState(false);
  const sheetRef = useRef<HTMLDivElement>(null);
  const dragStartY = useRef<number | null>(null);
  const dragStartHeight = useRef<number | null>(null);
  const suppressHandleClick = useRef(false);

  useEffect(() => {
    if (!isOpen) {
      setIsExpanded(false);
      setDraggedHeight(null);
      setIsDragging(false);
      setIsDismissing(false);
      dragStartY.current = null;
      dragStartHeight.current = null;
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
    <div className='fixed inset-0 z-[60] flex items-end justify-center lg:z-50 lg:items-center' role='dialog' aria-modal='true' aria-label={title ?? 'Bottom sheet'}>
      <button
        type='button'
        aria-label='Close'
        className={`absolute inset-0 bg-black/60 transition-opacity duration-200 ${isDismissing ? 'opacity-0' : 'opacity-100'}`}
        onClick={onClose}
      />

      <div className={[
        'relative flex w-full flex-col overflow-hidden rounded-t-3xl border-x border-t border-[var(--bg-border)] bg-[var(--bg-card)] pb-[env(safe-area-inset-bottom)] transition-[height,max-height,border-radius,transform] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]',
        isExpanded ? 'h-[calc(100dvh-env(safe-area-inset-top))] max-h-none' : 'max-h-[85dvh]',
        isDismissing ? 'translate-y-full' : 'translate-y-0',
        'lg:h-auto lg:max-h-[70vh] lg:max-w-2xl lg:rounded-3xl lg:border lg:pb-0 lg:shadow-[0_24px_60px_rgba(0,0,0,0.55)]',
      ].join(' ')}
        ref={sheetRef}
        style={{
          height: draggedHeight ?? undefined,
          transition: isDragging ? 'none' : undefined,
        }}
        onTransitionEnd={(event) => {
          if (isDismissing && event.target === event.currentTarget && event.propertyName === 'transform') {
            onClose();
          }
        }}
      >
        <div className='flex shrink-0 justify-center pt-2 pb-2 lg:hidden'>
          <button
            type='button'
            aria-label={isExpanded ? 'Collapse sheet' : 'Expand sheet'}
            aria-expanded={isExpanded}
            className='flex h-8 w-20 touch-none items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]'
            onPointerDown={(event) => {
              dragStartY.current = event.clientY;
              dragStartHeight.current = sheetRef.current?.getBoundingClientRect().height ?? null;
              setIsDragging(true);
              if (dragStartHeight.current !== null) setDraggedHeight(dragStartHeight.current);
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={(event) => {
              if (dragStartY.current === null || dragStartHeight.current === null) return;
              const deltaY = event.clientY - dragStartY.current;
              const minHeight = 160;
              const maxHeight = window.innerHeight - 8;
              setDraggedHeight(Math.max(minHeight, Math.min(maxHeight, dragStartHeight.current - deltaY)));
            }}
            onPointerUp={(event) => {
              if (dragStartY.current === null) return;
              const deltaY = event.clientY - dragStartY.current;
              dragStartY.current = null;
              dragStartHeight.current = null;
              setIsDragging(false);
              if (Math.abs(deltaY) > 24) {
                suppressHandleClick.current = true;
                if (deltaY > 72) {
                  setIsDismissing(true);
                } else if (deltaY < -36) {
                  setIsExpanded(true);
                }
              }
              setDraggedHeight(null);
            }}
            onPointerCancel={() => {
              dragStartY.current = null;
              dragStartHeight.current = null;
              setIsDragging(false);
              setDraggedHeight(null);
            }}
            onClick={() => {
              if (suppressHandleClick.current) {
                suppressHandleClick.current = false;
                return;
              }
              setIsExpanded((expanded) => !expanded);
            }}
          >
            <span className='h-1 w-10 rounded-full bg-[var(--bg-border)]' />
          </button>
        </div>

        <div className='min-h-0 flex-1 overflow-y-auto px-4 pb-5 touch-scroll lg:px-5 lg:pb-5' onClick={(event) => event.stopPropagation()}>
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
