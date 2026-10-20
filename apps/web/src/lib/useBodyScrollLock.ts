import { useEffect } from 'react';

const activeLocks = new Set<symbol>();
let previousBodyOverflow = '';

function acquireBodyScrollLock(): () => void {
  const lock = Symbol('body-scroll-lock');
  if (activeLocks.size === 0) {
    previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
  }
  activeLocks.add(lock);

  return () => {
    activeLocks.delete(lock);
    if (activeLocks.size === 0) {
      document.body.style.overflow = previousBodyOverflow;
      previousBodyOverflow = '';
    }
  };
}

/** Keeps the document from scrolling while one or more modal surfaces are open. */
export function useBodyScrollLock(locked: boolean): void {
  useEffect(() => {
    if (!locked) return undefined;
    return acquireBodyScrollLock();
  }, [locked]);
}
