// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Split, SplitNotificationStatus } from '../../features/splits/splitsApi';
import { NotificationConfirmDialog } from './NotificationConfirmDialog';

const mocks = vi.hoisted(() => ({
  loadStatus: vi.fn(),
  queue: vi.fn(),
  queueUnwrap: vi.fn(),
  rename: vi.fn(),
  renameUnwrap: vi.fn(),
  saveEmail: vi.fn(),
  saveEmailUnwrap: vi.fn(),
  status: undefined as SplitNotificationStatus | undefined,
}));

vi.mock('../../features/splits/splitsApi', () => ({
  useLazyGetSplitNotificationStatusQuery: () => [mocks.loadStatus, { data: mocks.status, isFetching: false }],
  useQueueSplitNotificationMutation: () => [mocks.queue, { isLoading: false }],
  useRenameSplitMutation: () => [mocks.rename, { isLoading: false }],
  useSetSplitContactDetailsMutation: () => [mocks.saveEmail, { isLoading: false }],
}));

const participants = [
  { id: 'participant-1', name: 'Isha', share_paise: 7500, settled_paise: 0,
    repayment_transaction_id: null, contact_id: 'contact-1', payments: [] },
  { id: 'participant-2', name: 'Ravi', share_paise: 5000, settled_paise: 0,
    repayment_transaction_id: null, contact_id: 'contact-2', payments: [] },
];
const split = {
  id: 'split-1', transaction_id: 'transaction-1', kind: 'expense_split', direction: 'to_you',
  title: 'Dinner', owner_share_paise: 7500, total_paise: 20000, outstanding_paise: 12500,
  created_at: '2026-11-07T10:00:00Z', participants, settlement_breakdown: null,
} satisfies Split;

function status(overrides: Partial<SplitNotificationStatus> = {}): SplitNotificationStatus {
  return {
    server_now: '2026-11-07T10:00:00Z', can_notify: true, blocked_reason: null,
    notification_count: 0, max_notifications: 3, limits_bypassed: false, last_sent_at: null, next_available_at: null,
    cooldown_remaining_seconds: 0, request_in_progress: false, channel: 'email',
    recipients: [
      { participant_id: 'participant-1', contact_id: 'contact-1', name: 'Isha',
        amount_paise: 7500, recipient: 'i***@example.com' },
      { participant_id: 'participant-2', contact_id: 'contact-2', name: 'Ravi',
        amount_paise: 5000, recipient: 'r***@example.com' },
    ],
    missing_recipients: [], history: [], ...overrides,
  };
}

describe('NotificationConfirmDialog', () => {
  afterEach(cleanup);

  beforeEach(() => {
    mocks.loadStatus.mockReset();
    mocks.queue.mockReset();
    mocks.queueUnwrap.mockReset();
    mocks.saveEmail.mockReset();
    mocks.saveEmailUnwrap.mockReset();
    mocks.rename.mockReset();
    mocks.renameUnwrap.mockReset();
    mocks.renameUnwrap.mockResolvedValue({});
    mocks.rename.mockReturnValue({ unwrap: mocks.renameUnwrap });
    mocks.queue.mockReturnValue({ unwrap: mocks.queueUnwrap });
    mocks.saveEmail.mockReturnValue({ unwrap: mocks.saveEmailUnwrap });
    mocks.status = status();
    vi.stubGlobal('crypto', { randomUUID: () => 'campaign-key' });
  });

  it('queues one split campaign containing separate recipient emails', async () => {
    mocks.queueUnwrap.mockResolvedValue({ notification_ids: ['one', 'two'] });
    const onClose = vi.fn();
    const onQueued = vi.fn();
    render(<NotificationConfirmDialog split={split} contacts={[]} onClose={onClose} onQueued={onQueued} />);

    expect(screen.getByText('Isha')).toBeInTheDocument();
    expect(screen.getByText('Ravi')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Send 2 emails' }));

    await waitFor(() => expect(mocks.queue).toHaveBeenCalledWith({
      splitId: 'split-1', idempotencyKey: 'campaign-key',
    }));
    expect(onQueued).toHaveBeenCalledWith('2 payment reminders queued for Dinner.');
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('lets the user edit the description, saving it to the split before queuing', async () => {
    mocks.queueUnwrap.mockResolvedValue({ notification_ids: ['one', 'two'] });
    const onQueued = vi.fn();
    render(<NotificationConfirmDialog split={split} contacts={[]} onClose={vi.fn()} onQueued={onQueued} />);

    const field = screen.getByRole('textbox', { name: /What is this payment for/ });
    expect(field).toHaveValue('Dinner');
    fireEvent.change(field, { target: { value: '  Goa   trip dinner ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send 2 emails' }));

    await waitFor(() => expect(mocks.rename).toHaveBeenCalledWith({ splitId: 'split-1', title: 'Goa trip dinner' }));
    await waitFor(() => expect(mocks.queue).toHaveBeenCalled());
    expect(mocks.rename.mock.invocationCallOrder[0]).toBeLessThan(mocks.queue.mock.invocationCallOrder[0]);
    expect(onQueued).toHaveBeenCalledWith('2 payment reminders queued for Goa trip dinner.');
  });

  it('does not rename when unchanged and blocks an empty description', () => {
    render(<NotificationConfirmDialog split={split} contacts={[]} onClose={vi.fn()} onQueued={vi.fn()} />);
    fireEvent.change(screen.getByRole('textbox', { name: /What is this payment for/ }), { target: { value: '   ' } });
    expect(screen.getByRole('button', { name: 'Send 2 emails' })).toBeDisabled();
    expect(mocks.rename).not.toHaveBeenCalled();
  });

  it('disables the whole split campaign during cooldown', () => {
    mocks.status = status({
      can_notify: false, blocked_reason: 'cooldown_active', cooldown_remaining_seconds: 3600,
    });
    render(<NotificationConfirmDialog split={split} contacts={[]} onClose={vi.fn()} onQueued={vi.fn()} />);

    expect(screen.getByRole('button', { name: 'Send 2 emails' })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('cooldown period');
  });

  it('shows the backend error when queueing fails', async () => {
    mocks.queueUnwrap.mockRejectedValue({ data: { detail: { message: 'Daily notification limit reached.' } } });
    render(<NotificationConfirmDialog split={split} contacts={[]} onClose={vi.fn()} onQueued={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Send 2 emails' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Daily notification limit reached.'));
  });

  it('collects all missing emails before the split campaign can be sent', async () => {
    mocks.status = status({
      can_notify: false, blocked_reason: 'participant_emails_required',
      recipients: [
        { participant_id: 'participant-1', contact_id: 'contact-1', name: 'Isha',
          amount_paise: 7500, recipient: null },
      ],
      missing_recipients: [
        { participant_id: 'participant-1', contact_id: 'contact-1', name: 'Isha',
          amount_paise: 7500, recipient: null },
      ],
    });
    mocks.saveEmailUnwrap.mockResolvedValue({ id: 'contact-1' });
    render(<NotificationConfirmDialog split={split}
      contacts={[{ id: 'contact-1', name: 'Isha', email: null, phone_e164: '+919876543210', dietary_preference: null }]}
      onClose={vi.fn()} onQueued={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Isha'), { target: { value: 'ISHA@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save emails' }));

    await waitFor(() => expect(mocks.saveEmail).toHaveBeenCalledWith({
      contact_id: 'contact-1', name: 'Isha', email: 'isha@example.com', phone_e164: '+919876543210',
    }));
    expect(mocks.loadStatus).toHaveBeenCalledWith({ splitId: 'split-1' }, false);
  });
});
