import { X } from 'lucide-react';
import { createPortal } from 'react-dom';
import { useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useBodyScrollLock } from '../../../lib/useBodyScrollLock';
import { useModalFocus } from '../../../lib/useModalFocus';

export interface BottomSheetProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
}

export function BottomSheet({ isOpen, onClose, title, children }: BottomSheetProps) {
  const contentId = useId();
  const [isExpanded, setIsExpanded] = useState(false);
  const [draggedHeight, setDraggedHeight] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isDismissing, setIsDismissing] = useState(false);
  const sheetRef = useRef<HTMLDivElement>(null);
  const dragStartY = useRef<number | null>(null);
  const dragStartHeight = useRef<number | null>(null);
  const dragFrame = useRef<number | null>(null);
  const dismissTimer = useRef<number | null>(null);
  const closeCommitted = useRef(false);
  const activeDragTarget = useRef<HTMLButtonElement | null>(null);
  const activePointerId = useRef<number | null>(null);
  const onCloseRef = useRef(onClose);
  const pendingHeight = useRef<number | null>(null);
  const suppressHandleClick = useRef(false);
  // Release focus/inert and scroll locks as soon as dismissal starts. The visual exit can finish independently.
  const { containerRef: focusContainerRef, overlayRef } = useModalFocus(isOpen && !isDismissing, onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  const resetDrag = (target = activeDragTarget.current, pointerId = activePointerId.current) => {
    if (target && pointerId !== null && target.hasPointerCapture?.(pointerId)) {
      try { target.releasePointerCapture(pointerId); } catch { /* Pointer capture may already be released by iOS. */ }
    }
    activeDragTarget.current = null;
    activePointerId.current = null;
    dragStartY.current = null;
    dragStartHeight.current = null;
    if (dragFrame.current !== null) cancelAnimationFrame(dragFrame.current);
    dragFrame.current = null;
    pendingHeight.current = null;
    setIsDragging(false);
    setDraggedHeight(null);
  };

  const finishDismiss = () => {
    if (closeCommitted.current) return;
    closeCommitted.current = true;
    if (dismissTimer.current !== null) window.clearTimeout(dismissTimer.current);
    dismissTimer.current = null;
    resetDrag();
    onCloseRef.current();
  };

  const beginDismiss = () => {
    closeCommitted.current = false;
    setIsDismissing(true);
    if (dismissTimer.current !== null) window.clearTimeout(dismissTimer.current);
    // iOS WebViews can omit transitionend after a captured-pointer drag. Always complete the close.
    dismissTimer.current = window.setTimeout(finishDismiss, 240);
  };

  useEffect(() => {
    if (!isOpen) {
      const resetTimer = window.setTimeout(() => {
        setIsExpanded(false);
        setDraggedHeight(null);
        setIsDragging(false);
        setIsDismissing(false);
        dragStartY.current = null;
        dragStartHeight.current = null;
        if (dragFrame.current !== null) cancelAnimationFrame(dragFrame.current);
        dragFrame.current = null;
        pendingHeight.current = null;
        closeCommitted.current = false;
        if (dismissTimer.current !== null) window.clearTimeout(dismissTimer.current);
        dismissTimer.current = null;
        resetDrag();
      }, 0);
      return () => window.clearTimeout(resetTimer);
    }
    closeCommitted.current = false;
  }, [isOpen]);

  useEffect(() => () => {
    if (dismissTimer.current !== null) window.clearTimeout(dismissTimer.current);
    if (dragFrame.current !== null) cancelAnimationFrame(dragFrame.current);
    const target = activeDragTarget.current;
    const pointerId = activePointerId.current;
    if (target && pointerId !== null && target.hasPointerCapture?.(pointerId)) {
      try { target.releasePointerCapture(pointerId); } catch { /* The browser already released it. */ }
    }
  }, []);

  useBodyScrollLock(isOpen && !isDismissing);

  if (!isOpen) {
    return null;
  }

  return createPortal(
    <div
      ref={overlayRef}
      data-modal-layer
      className={`fixed inset-0 z-[100] isolate flex items-end justify-center bg-[var(--overlay)] transition-opacity duration-200 lg:items-center ${isDismissing ? 'pointer-events-none opacity-0' : 'opacity-100'}`}
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >

      <div className={[
        'relative z-10 flex w-full flex-col overflow-hidden rounded-t-3xl border-x border-t border-[var(--border)] bg-[var(--surface)] pb-[env(safe-area-inset-bottom)] transition-[border-radius,transform] duration-200 ease-[var(--ease-out)]',
        isExpanded ? 'h-[calc(100dvh-env(safe-area-inset-top))] max-h-none' : 'max-h-[85dvh]',
        isDismissing ? 'translate-y-full' : 'translate-y-0',
        'lg:h-auto lg:max-h-[70vh] lg:max-w-2xl lg:rounded-2xl lg:border lg:pb-0 lg:shadow-[var(--shadow-raised)]',
      ].join(' ')}
        ref={(node) => {
          sheetRef.current = node;
          focusContainerRef.current = node;
        }}
        role='dialog'
        aria-modal='true'
        aria-label={title ?? 'Bottom sheet'}
        tabIndex={-1}
        style={{
          height: draggedHeight ?? undefined,
          transition: isDragging ? 'none' : undefined,
        }}
        onTransitionEnd={(event) => {
          if (isDismissing && event.target === event.currentTarget && event.propertyName === 'transform') {
            finishDismiss();
          }
        }}
      >
        <div className='flex shrink-0 justify-center px-3 lg:hidden'>
          <button
            type='button'
            aria-label={isExpanded ? 'Collapse sheet' : 'Expand sheet'}
            aria-expanded={isExpanded}
            aria-controls={contentId}
            className='bottom-sheet-drag-handle group flex h-12 w-full touch-none select-none items-center justify-center rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]'
            onPointerDown={(event) => {
              if (!event.isPrimary || event.button !== 0) return;
              event.preventDefault();
              dragStartY.current = event.clientY;
              dragStartHeight.current = sheetRef.current?.getBoundingClientRect().height ?? null;
              activeDragTarget.current = event.currentTarget;
              activePointerId.current = event.pointerId;
              setIsDragging(true);
              if (dragStartHeight.current !== null) setDraggedHeight(dragStartHeight.current);
              try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* Continue without capture. */ }
            }}
            onPointerMove={(event) => {
              if (dragStartY.current === null || dragStartHeight.current === null) return;
              const deltaY = event.clientY - dragStartY.current;
              const minHeight = 160;
              const maxHeight = (window.visualViewport?.height ?? window.innerHeight) - 8;
              pendingHeight.current = Math.max(minHeight, Math.min(maxHeight, dragStartHeight.current - deltaY));
              if (dragFrame.current === null) {
                dragFrame.current = requestAnimationFrame(() => {
                  dragFrame.current = null;
                  if (pendingHeight.current !== null) setDraggedHeight(pendingHeight.current);
                });
              }
            }}
            onPointerUp={(event) => {
              if (dragStartY.current === null) return;
              const deltaY = event.clientY - dragStartY.current;
              resetDrag(event.currentTarget, event.pointerId);
              if (Math.abs(deltaY) > 24) {
                suppressHandleClick.current = true;
                if (deltaY > 72) {
                  beginDismiss();
                } else if (deltaY < -36) {
                  setIsExpanded(true);
                }
              }
            }}
            onPointerCancel={(event) => {
              resetDrag(event.currentTarget, event.pointerId);
            }}
            onClick={() => {
              if (suppressHandleClick.current) {
                suppressHandleClick.current = false;
                return;
              }
              setIsExpanded((expanded) => !expanded);
            }}
          >
            <span className='h-1.5 w-12 rounded-full bg-[var(--text-muted)] transition-colors group-hover:bg-[var(--text-secondary)]' />
          </button>
        </div>

        <div id={contentId} className='min-h-0 flex-1 touch-pan-y overflow-y-auto overscroll-contain px-4 pb-5 touch-scroll lg:px-5 lg:pb-5'>
          {title ? (
            <div className='mb-4 mt-4 flex items-center justify-between'>
              <h2 className='text-lg font-bold text-[var(--text-primary)]'>{title}</h2>
              <button
                type='button'
                aria-label='Close'
                data-modal-autofocus
                className='flex h-9 w-9 items-center justify-center rounded-full border border-[var(--bg-border)] bg-[var(--bg-elevated)] text-lg text-[var(--text-secondary)] hover:bg-[var(--bg-card)]'
                onClick={onClose}
              >
                <X className='h-4 w-4' aria-hidden='true' />
              </button>
            </div>
          ) : null}

          {children}
        </div>
      </div>
    </div>,
    document.body,
  );
}
