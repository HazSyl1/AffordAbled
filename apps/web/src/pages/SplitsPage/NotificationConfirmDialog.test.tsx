// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Split, SplitNotificationStatus, SplitParticipant } from '../../features/splits/splitsApi';
import { NotificationConfirmDialog } from './NotificationConfirmDialog';

const mocks = vi.hoisted(() => ({
  loadStatus: vi.fn(),
  unwrap: vi.fn(),
  status: undefined as SplitNotificationStatus | undefined,
}));

vi.mock('../../features/splits/splitsApi', () => ({
  useLazyGetSplitNotificationStatusQuery: () => [
    mocks.loadStatus,
    { data: mocks.status, isFetching: false },
  ],
  useQueueSplitNotificationMutation: () => [
    () => ({ unwrap: mocks.unwrap }),
    { isLoading: false },
  ],
}));

const participant = {
  id: 'participant-1', name: 'Isha', share_paise: 10000, settled_paise: 2500,
  repayment_transaction_id: null, contact_id: 'contact-1', payments: [],
} satisfies SplitParticipant;

const split = {
  id: 'split-1', transaction_id: 'transaction-1', kind: 'expense_split', direction: 'to_you',
  title: 'Dinner', owner_share_paise: 10000, total_paise: 20000, outstanding_paise: 7500,
  created_at: '2026-11-07T10:00:00Z', participants: [participant], settlement_breakdown: null,
} satisfies Split;

function status(overrides: Partial<SplitNotificationStatus> = {}): SplitNotificationStatus {
  return {
    server_now: '2026-11-07T10:00:00Z', can_notify: true, blocked_reason: null,
    notification_count: 0, max_notifications: 3, last_sent_at: null, next_available_at: null,
    cooldown_remaining_seconds: 0, request_in_progress: false,
    message_preview: 'Hi Isha, pay Rs.75.00', recipient_phone_masked: '+91******3210', history: [],
    ...overrides,
  };
}

describe('NotificationConfirmDialog', () => {
  afterEach(cleanup);

  beforeEach(() => {
    mocks.loadStatus.mockReset();
    mocks.unwrap.mockReset();
    mocks.status = status();
    vi.stubGlobal('crypto', { randomUUID: () => 'notification-key' });
  });

  it('previews the confirmed amount and queues one SMS request', async () => {
    mocks.unwrap.mockResolvedValue({ notification_id: 'notification-1' });
    const onClose = vi.fn();
    const onQueued = vi.fn();
    render(<NotificationConfirmDialog split={split} participant={participant}
      onClose={onClose} onQueued={onQueued} />);

    expect(screen.getByText(/Remaining amount: ₹75.00/)).toBeInTheDocument();
    expect(screen.getByText('Hi Isha, pay Rs.75.00')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Send SMS' }));

    await waitFor(() => expect(mocks.unwrap).toHaveBeenCalledOnce());
    expect(onQueued).toHaveBeenCalledWith('Payment reminder queued for Isha.');
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('disables sending and explains a cooldown', () => {
    mocks.status = status({
      can_notify: false, blocked_reason: 'cooldown_active', cooldown_remaining_seconds: 3600,
    });
    render(<NotificationConfirmDialog split={split} participant={participant}
      onClose={vi.fn()} onQueued={vi.fn()} />);

    expect(screen.getByRole('button', { name: 'Send SMS' })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('cooldown period');
    expect(screen.getByText(/Available again in 60 minutes/)).toBeInTheDocument();
  });

  it('shows the backend error when queueing fails', async () => {
    mocks.unwrap.mockRejectedValue({ data: { detail: { message: 'Daily SMS limit reached.' } } });
    render(<NotificationConfirmDialog split={split} participant={participant}
      onClose={vi.fn()} onQueued={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Send SMS' }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Daily SMS limit reached.'));
  });
});
