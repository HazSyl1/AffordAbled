// @vitest-environment node
import { describe, expect, it } from 'vitest';

import type { ChatResponse } from './chatApi';
import { resolveChatReminders } from './chatReminders';
import type { Split } from '../splits/splitsApi';

const split: Split = {
  id: 'dinner', transaction_id: 'transaction', kind: 'expense_split', direction: 'to_you',
  title: 'Dinner', owner_share_paise: 1000, total_paise: 3000, outstanding_paise: 2000,
  created_at: '2026-11-10T10:00:00Z', settlement_breakdown: null,
  participants: ['Rahul', 'Isha'].map((name) => ({
    id: name, name, share_paise: 1000, settled_paise: 0, contact_id: null,
    repayment_transaction_id: null, payments: [],
  })),
};
const response: ChatResponse = { thread_id: 'thread', message: 'Review reminder',
  tasks_completed: true, show_completion_popup: false };

describe('chat email reminder selection', () => {
  it('preserves the requested recipient when a split was also just created', () => {
    expect(resolveChatReminders({ ...response, created_split_ids: ['dinner'],
      reminder_requests: [{ split_id: 'dinner', participant_ids: ['Rahul'] }] }, [split]))
      .toEqual([{ split, participantIds: ['Rahul'] }]);
  });
  it('retains the existing reminder offer after creating a split', () => {
    expect(resolveChatReminders({ ...response, created_split_ids: ['dinner'] }, [split]))
      .toEqual([{ split, participantIds: undefined }]);
  });
  it('does not open reminders for settled or outgoing entries', () => {
    const request = { ...response, reminder_requests: [{ split_id: 'dinner', participant_ids: ['Rahul'] }] };
    expect(resolveChatReminders(request, [{ ...split, direction: 'by_you' }])).toEqual([]);
    expect(resolveChatReminders(request, [{ ...split, participants: split.participants.map(
      (person) => ({ ...person, settled_paise: person.share_paise }),
    ) }])).toEqual([]);
  });
});
