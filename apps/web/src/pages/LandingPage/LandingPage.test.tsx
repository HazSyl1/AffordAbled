import '@testing-library/jest-dom/vitest';

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LandingPage } from './LandingPage';

function renderPage() {
  return render(<MemoryRouter><LandingPage /></MemoryRouter>);
}

describe('LandingPage', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it('showcases the new reminder and plan features', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: 'Send UPI payment reminders' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Plans and daily usage' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Branded UPI reminders, in one tap' })).toBeInTheDocument();
  });

  it('moves through carousel slides with the controls and dots', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Next feature' }));
    expect(screen.getByRole('heading', { name: 'Remind a whole split at once' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Previous feature' }));
    fireEvent.click(screen.getByRole('button', { name: 'Previous feature' }));
    expect(screen.getByRole('heading', { name: 'Settle group trips with exact math' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: /Know exactly what you have left today/ }));
    expect(screen.getByRole('group', { name: '3 of 4' })).toBeInTheDocument();
  });

  it('advances automatically and stops when paused', () => {
    renderPage();
    act(() => { vi.advanceTimersByTime(6100); });
    expect(screen.getByRole('group', { name: '2 of 4' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Pause automatic rotation' }));
    act(() => { vi.advanceTimersByTime(20000); });
    expect(screen.getByRole('group', { name: '2 of 4' })).toBeInTheDocument();
  });
});
