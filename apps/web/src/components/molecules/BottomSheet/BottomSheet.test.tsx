import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { createPortal } from 'react-dom';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { BottomSheet } from './BottomSheet';
import { TransactionSuccessOverlay } from '../TransactionSuccessOverlay/TransactionSuccessOverlay';

beforeEach(() => {
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    callback(0);
    return 1;
  });
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.body.removeAttribute('style');
});

describe('BottomSheet', () => {
  it('keeps the top sheet interactive when two sheets mount together', () => {
    const firstAction = vi.fn();
    const secondAction = vi.fn();
    render(<>
      <BottomSheet isOpen onClose={vi.fn()} title='First sheet'>
        <button type='button' onClick={firstAction}>First action</button>
      </BottomSheet>
      <BottomSheet isOpen onClose={vi.fn()} title='Second sheet'>
        <button type='button' onClick={secondAction}>Second action</button>
      </BottomSheet>
    </>);

    const layers = Array.from(document.body.querySelectorAll<HTMLElement>('[data-modal-layer]'));
    expect(layers).toHaveLength(2);
    expect(layers[0].inert).toBe(true);
    expect(layers[1].inert).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: 'Second action' }));
    expect(secondAction).toHaveBeenCalledOnce();
    expect(firstAction).not.toHaveBeenCalled();
  });

  it('does not make a higher custom popup inert', () => {
    const popupAction = vi.fn();
    render(<>
      <BottomSheet isOpen onClose={vi.fn()} title='Transaction'>
        <p>Transaction form</p>
      </BottomSheet>
      {createPortal(
        <div data-modal-layer>
          <button type='button' onClick={popupAction}>Confirm transaction</button>
        </div>,
        document.body,
      )}
    </>);

    const popup = screen.getByRole('button', { name: 'Confirm transaction' }).parentElement as HTMLElement;
    expect(popup.inert).not.toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Confirm transaction' }));
    expect(popupAction).toHaveBeenCalledOnce();
  });

  it('only closes from the backdrop itself', () => {
    const onClose = vi.fn();
    render(<BottomSheet isOpen onClose={onClose} title='Transaction'>
      <button type='button'>Save</button>
    </BottomSheet>);

    fireEvent.pointerDown(screen.getByRole('button', { name: 'Save' }));
    expect(onClose).not.toHaveBeenCalled();

    const overlay = screen.getByRole('dialog', { name: 'Transaction' }).parentElement;
    expect(overlay).not.toBeNull();
    fireEvent.pointerDown(overlay!);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('portals a post-chat transaction popup outside the inert app root', () => {
    const onContinue = vi.fn();
    const { container } = render(<>
      <BottomSheet isOpen onClose={vi.fn()} title='Assistant'>Chat</BottomSheet>
      <TransactionSuccessOverlay
        message='Transaction added'
        expiresAt={Date.now() + 12_000}
        onClose={vi.fn()}
        onContinue={onContinue}
      />
    </>);

    const successDialog = screen.getByRole('dialog', { name: 'Tasks completed' });
    expect(container.inert).toBe(true);
    expect(successDialog.parentElement).toBe(document.body);
    expect(successDialog.inert).not.toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'Continue chatting' }));
    expect(onContinue).toHaveBeenCalledOnce();
  });

  it('always releases the modal lock after a drag-close even without transitionend', () => {
    vi.useFakeTimers();
    const pageAction = vi.fn();
    function Harness() {
      const [open, setOpen] = useState(true);
      return <>
        <button type='button' onClick={pageAction}>Page action</button>
        <BottomSheet isOpen={open} onClose={() => setOpen(false)} title='Drag sheet'>Content</BottomSheet>
      </>;
    }

    const { container } = render(<Harness />);
    const handle = screen.getByRole('button', { name: 'Expand sheet' });
    Object.defineProperties(handle, {
      setPointerCapture: { configurable: true, value: vi.fn() },
      hasPointerCapture: { configurable: true, value: vi.fn(() => true) },
      releasePointerCapture: { configurable: true, value: vi.fn() },
    });
    const dialog = screen.getByRole('dialog', { name: 'Drag sheet' });
    vi.spyOn(dialog, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 300, width: 400, height: 500, top: 300, right: 400, bottom: 800, left: 0,
      toJSON: () => ({}),
    });

    fireEvent.pointerDown(handle, { pointerId: 7, isPrimary: true, button: 0, clientY: 100 });
    fireEvent.pointerUp(handle, { pointerId: 7, isPrimary: true, button: 0, clientY: 200 });
    expect(container.inert).not.toBe(true);

    act(() => vi.advanceTimersByTime(250));

    expect(screen.queryByRole('dialog', { name: 'Drag sheet' })).toBeNull();
    expect(document.body.querySelectorAll('[data-modal-layer]')).toHaveLength(0);
    expect(container.inert).not.toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Page action' }));
    expect(pageAction).toHaveBeenCalledOnce();
  });
});
