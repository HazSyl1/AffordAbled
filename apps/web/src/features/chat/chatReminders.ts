import type { ChatResponse } from './chatApi';
import type { Split } from '../splits/splitsApi';

export interface PendingChatReminder {
  split: Split;
  participantIds?: string[];
}

export function resolveChatReminders(response: ChatResponse, splits: Split[]): PendingChatReminder[] {
  const requests = new Map((response.reminder_requests ?? []).map((request) => [request.split_id, request]));
  const createdIds = new Set(response.created_split_ids ?? []);
  return splits.filter((split) => (requests.has(split.id) || createdIds.has(split.id))
    && split.direction === 'to_you' && !split.settlement_breakdown
    && split.participants.some((person) => person.share_paise > person.settled_paise))
    .map((split) => ({ split, participantIds: requests.get(split.id)?.participant_ids }));
}
