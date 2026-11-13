import { useEffect, useRef } from 'react';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

interface ModalLayer {
  id: symbol;
  overlay: HTMLElement;
}

interface ElementAccessibilityState {
  inert: boolean;
  ariaHidden: string | null;
}

const modalStack: ModalLayer[] = [];
const backgroundState = new Map<HTMLElement, ElementAccessibilityState>();

function restoreAccessibilityState(element: HTMLElement, state: ElementAccessibilityState): void {
  element.inert = state.inert;
  if (state.ariaHidden === null) element.removeAttribute('aria-hidden');
  else element.setAttribute('aria-hidden', state.ariaHidden);
}

function syncModalLayers(): void {
  for (let index = modalStack.length - 1; index >= 0; index -= 1) {
    if (!modalStack[index].overlay.isConnected) modalStack.splice(index, 1);
  }
  const connectedLayers = modalStack.filter(({ overlay }) => overlay.isConnected);
  const topLayer = connectedLayers.at(-1);
  const registeredOverlays = new Set(connectedLayers.map(({ overlay }) => overlay));

  for (const element of Array.from(document.body.children)) {
    if (!(element instanceof HTMLElement)) continue;

    if (element.dataset.modalLayer !== undefined) {
      if (registeredOverlays.has(element)) {
        const isTopLayer = element === topLayer?.overlay;
        element.inert = !isTopLayer;
        if (isTopLayer) element.removeAttribute('aria-hidden');
        else element.setAttribute('aria-hidden', 'true');
      }
      continue;
    }

    if (connectedLayers.length > 0) {
      if (!backgroundState.has(element)) {
        backgroundState.set(element, {
          inert: element.inert,
          ariaHidden: element.getAttribute('aria-hidden'),
        });
      }
      element.inert = true;
      element.setAttribute('aria-hidden', 'true');
    }
  }

  if (connectedLayers.length === 0) {
    for (const [element, state] of backgroundState) {
      if (element.isConnected) restoreAccessibilityState(element, state);
    }
    backgroundState.clear();
  }
}

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
    if (!overlay) return;
    const layerId = Symbol('modal-layer');
    // Clear any disconnected layer/background state before registering a newly opened modal.
    syncModalLayers();
    modalStack.push({ id: layerId, overlay });
    syncModalLayers();

    const focusFrame = window.requestAnimationFrame(() => {
      const preferredTarget = containerRef.current?.querySelector<HTMLElement>('[data-modal-autofocus]');
      const firstTarget = containerRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      (preferredTarget ?? firstTarget ?? containerRef.current)?.focus();
    });

    const handleKeyDown = (event: KeyboardEvent) => {
      if (modalStack.at(-1)?.id !== layerId) return;
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
      const stackIndex = modalStack.findIndex(({ id }) => id === layerId);
      const wasTopLayer = stackIndex === modalStack.length - 1;
      if (stackIndex >= 0) modalStack.splice(stackIndex, 1);
      overlay.inert = false;
      overlay.removeAttribute('aria-hidden');
      syncModalLayers();
      if (wasTopLayer && previouslyFocused?.isConnected) {
        window.requestAnimationFrame(() => previouslyFocused.focus());
      }
    };
  }, [isActive]);

  return { containerRef, overlayRef };
}
