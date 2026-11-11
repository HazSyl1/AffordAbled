import { useEffect, useRef } from 'react';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export function useModalFocus(isActive: boolean, onClose: () => void) {
  const containerRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!isActive) return;

    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overlay = overlayRef.current;
    const backgroundState = Array.from(document.body.children)
      .filter((element): element is HTMLElement => element instanceof HTMLElement && element !== overlay)
      .map((element) => ({ element, inert: element.inert, ariaHidden: element.getAttribute('aria-hidden') }));

    backgroundState.forEach(({ element }) => {
      element.inert = true;
      element.setAttribute('aria-hidden', 'true');
    });

    const focusFrame = window.requestAnimationFrame(() => {
      const preferredTarget = containerRef.current?.querySelector<HTMLElement>('[data-modal-autofocus]');
      const firstTarget = containerRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      (preferredTarget ?? firstTarget ?? containerRef.current)?.focus();
    });

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab' || !containerRef.current) return;

      const focusable = Array.from(containerRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
        .filter((element) => !element.hasAttribute('disabled') && element.getAttribute('aria-hidden') !== 'true');
      if (focusable.length === 0) {
        event.preventDefault();
        containerRef.current.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener('keydown', handleKeyDown);
      backgroundState.forEach(({ element, inert, ariaHidden }) => {
        element.inert = inert;
        if (ariaHidden === null) element.removeAttribute('aria-hidden');
        else element.setAttribute('aria-hidden', ariaHidden);
      });
      if (previouslyFocused?.isConnected) window.requestAnimationFrame(() => previouslyFocused.focus());
    };
  }, [isActive]);

  return { containerRef, overlayRef };
}
