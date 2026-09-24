export type ChatDraftKind = 'general' | 'transaction';
export type ChatDraftLifecycle = 'draft' | 'conversation';

export interface ChatDraftMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatDraft {
  id: string;
  kind: ChatDraftKind;
  lifecycle: ChatDraftLifecycle;
  transaction_id: string | null;
  thread_id: string | null;
  title: string;
  messages: ChatDraftMessage[];
  updated_at: string;
  expires_at: string | null;
}

interface SaveChatDraftInput {
  draftId?: string | null;
  kind: ChatDraftKind;
  lifecycle?: ChatDraftLifecycle;
  transactionId?: string | null;
  threadId?: string | null;
  messages: ChatDraftMessage[];
  expiresAt?: string | null;
  title?: string | null;
}

interface CreateChatDraftOptions {
  lifecycle?: ChatDraftLifecycle;
  expiresAt?: string | null;
  title?: string;
}

const STORAGE_KEY = 'affordabled_chat_drafts_v1';
const MAX_SAVED_MESSAGES = 80;
const DRAFT_DEFAULT_TTL_HOURS = 72;
const TITLE_MAX_WORDS = 8;
const TITLE_MAX_CHARS = 54;
const titleWorkersByDraftId = new Map<string, Worker>();

function createId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function getDefaultOccurredAtIso(): string {
  return new Date().toISOString();
}

function getDefaultDraftExpiryIso(baseIso: string = getDefaultOccurredAtIso()): string {
  const baseDate = new Date(baseIso);
  const baseTime = Number.isNaN(baseDate.getTime()) ? Date.now() : baseDate.getTime();
  return new Date(baseTime + DRAFT_DEFAULT_TTL_HOURS * 60 * 60 * 1000).toISOString();
}

function isValidKind(value: unknown): value is ChatDraftKind {
  return value === 'general' || value === 'transaction';
}

function isValidLifecycle(value: unknown): value is ChatDraftLifecycle {
  return value === 'draft' || value === 'conversation';
}

function normalizeMessages(messages: unknown): ChatDraftMessage[] {
  if (!Array.isArray(messages)) {
    return [];
  }

  return messages
    .filter((message): message is ChatDraftMessage => {
      if (!message || typeof message !== 'object') {
        return false;
      }

      const candidate = message as Record<string, unknown>;
      return (
        typeof candidate.id === 'string' &&
        (candidate.role === 'user' || candidate.role === 'assistant') &&
        typeof candidate.content === 'string'
      );
    })
    .slice(-MAX_SAVED_MESSAGES);
}

function getDefaultTitle(kind: ChatDraftKind, transactionId: string | null): string {
  if (kind === 'transaction') {
    if (!transactionId) {
      return 'Transaction chat';
    }

    return `Transaction ${transactionId.slice(0, 8)}`;
  }

  return 'General finance chat';
}

function getInitialTitle(kind: ChatDraftKind, transactionId: string | null, titleOverride?: string): string {
  if (typeof titleOverride === 'string') {
    return titleOverride.trim();
  }

  if (kind === 'general') {
    return '';
  }

  return getDefaultTitle(kind, transactionId);
}

function limitTitleLength(value: string): string {
  if (value.length <= TITLE_MAX_CHARS) {
    return value;
  }

  return `${value.slice(0, TITLE_MAX_CHARS - 3).trimEnd()}...`;
}

function normalizeGreetingPrefix(value: string): string {
  return value
    .replace(/^(hi|hello|hey|hii|yo)[\s,.:;!-]*/i, '')
    .replace(/^(please|kindly)\s+/i, '')
    .replace(/^(can|could|would)\s+you\s+/i, '')
    .replace(/^i\s+(want|need|would like)\s+to\s+/i, '')
    .replace(/^help\s+me\s+(to\s+)?/i, '')
    .trim();
}

function summarizeGeneralTitle(firstUserMessage: string): string {
  const compactMessage = firstUserMessage.replace(/\s+/g, ' ').trim();
  if (!compactMessage) {
    return 'General finance chat';
  }

  const primarySegment = compactMessage
    .split(/[.!?\n]/)
    .map((segment) => segment.trim())
    .find((segment) => segment.length > 0);

  const sourceText = primarySegment ?? compactMessage;
  const normalizedText = normalizeGreetingPrefix(sourceText);
  const titleSource = normalizedText.length > 0 ? normalizedText : sourceText;
  const words = titleSource.split(' ').filter((word) => word.length > 0);

  if (words.length === 0) {
    return 'General finance chat';
  }

  const truncatedWords = words.slice(0, TITLE_MAX_WORDS);
  let summary = truncatedWords.join(' ');

  if (words.length > TITLE_MAX_WORDS) {
    summary = `${summary}...`;
  }

  const titleCaseSummary = `${summary.charAt(0).toUpperCase()}${summary.slice(1)}`;
  return limitTitleLength(titleCaseSummary);
}

function buildTitle(kind: ChatDraftKind, transactionId: string | null, messages: ChatDraftMessage[]): string {
  const firstUserMessage = messages.find((message) => message.role === 'user')?.content.trim();
  if (firstUserMessage) {
    if (kind === 'general') {
      return summarizeGeneralTitle(firstUserMessage);
    }

    return limitTitleLength(firstUserMessage);
  }

  if (kind === 'general') {
    return '';
  }

  return getDefaultTitle(kind, transactionId);
}

function normalizeDraft(rawDraft: unknown): ChatDraft | null {
  if (!rawDraft || typeof rawDraft !== 'object') {
    return null;
  }

  const candidate = rawDraft as Record<string, unknown>;
  if (typeof candidate.id !== 'string') {
    return null;
  }

  if (!isValidKind(candidate.kind)) {
    return null;
  }

  const lifecycle = isValidLifecycle(candidate.lifecycle) ? candidate.lifecycle : 'conversation';
  const transactionId = typeof candidate.transaction_id === 'string' ? candidate.transaction_id : null;
  const threadId = typeof candidate.thread_id === 'string' ? candidate.thread_id : null;
  const updatedAt = typeof candidate.updated_at === 'string' ? candidate.updated_at : getDefaultOccurredAtIso();
  const messages = normalizeMessages(candidate.messages);
  const title =
    typeof candidate.title === 'string' && candidate.title.trim().length > 0
      ? candidate.title
      : buildTitle(candidate.kind, transactionId, messages);

  let expiresAt: string | null = typeof candidate.expires_at === 'string' ? candidate.expires_at : null;
  if (lifecycle === 'draft' && !expiresAt) {
    expiresAt = getDefaultDraftExpiryIso(updatedAt);
  }

  if (lifecycle === 'conversation') {
    expiresAt = null;
  }

  return {
    id: candidate.id,
    kind: candidate.kind,
    lifecycle,
    transaction_id: transactionId,
    thread_id: threadId,
    title,
    messages,
    updated_at: updatedAt,
    expires_at: expiresAt,
  };
}

function parseDrafts(rawValue: string | null): ChatDraft[] {
  if (!rawValue) {
    return [];
  }

  try {
    const parsedValue = JSON.parse(rawValue);
    if (!Array.isArray(parsedValue)) {
      return [];
    }

    return parsedValue.map((candidate) => normalizeDraft(candidate)).filter((draft): draft is ChatDraft => draft !== null);
  } catch {
    return [];
  }
}

function readDrafts(): ChatDraft[] {
  if (typeof window === 'undefined') {
    return [];
  }

  return parseDrafts(window.localStorage.getItem(STORAGE_KEY));
}

function writeDrafts(drafts: ChatDraft[]): void {
  if (typeof window === 'undefined') {
    return;
  }

  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(drafts));
}

function isDraftExpired(draft: ChatDraft): boolean {
  if (draft.lifecycle !== 'draft' || !draft.expires_at) {
    return false;
  }

  return new Date(draft.expires_at).getTime() <= Date.now();
}

function dedupeDrafts(drafts: ChatDraft[]): ChatDraft[] {
  const sortedDrafts = [...drafts].sort(
    (first, second) => new Date(second.updated_at).getTime() - new Date(first.updated_at).getTime(),
  );

  const seenThreadIds = new Set<string>();
  const seenTransactionKeys = new Set<string>();
  const dedupedDrafts: ChatDraft[] = [];

  for (const draft of sortedDrafts) {
    if (draft.thread_id) {
      if (seenThreadIds.has(draft.thread_id)) {
        continue;
      }

      seenThreadIds.add(draft.thread_id);
    }

    if (draft.kind === 'transaction' && draft.transaction_id) {
      const transactionKey = `${draft.lifecycle}:${draft.kind}:${draft.transaction_id}`;
      if (seenTransactionKeys.has(transactionKey)) {
        continue;
      }

      seenTransactionKeys.add(transactionKey);
    }

    dedupedDrafts.push(draft);
  }

  return dedupedDrafts;
}

export function listChatDrafts(): ChatDraft[] {
  const drafts = readDrafts();
  const unexpiredDrafts = drafts.filter((draft) => !isDraftExpired(draft));
  const dedupedDrafts = dedupeDrafts(unexpiredDrafts);

  if (dedupedDrafts.length !== drafts.length) {
    writeDrafts(dedupedDrafts);
  }

  return dedupedDrafts.sort(
    (first, second) => new Date(second.updated_at).getTime() - new Date(first.updated_at).getTime(),
  );
}

export function getChatDraftById(draftId: string): ChatDraft | null {
  return listChatDrafts().find((draft) => draft.id === draftId) ?? null;
}

export function createChatDraft(
  kind: ChatDraftKind,
  transactionId: string | null = null,
  options: CreateChatDraftOptions = {},
): ChatDraft {
  const nowIso = getDefaultOccurredAtIso();
  const lifecycle = options.lifecycle ?? 'conversation';
  const expiresAt = lifecycle === 'draft' ? options.expiresAt ?? getDefaultDraftExpiryIso(nowIso) : null;

  const newDraft: ChatDraft = {
    id: createId(),
    kind,
    lifecycle,
    transaction_id: transactionId,
    thread_id: null,
    title: getInitialTitle(kind, transactionId, options.title),
    messages: [],
    updated_at: nowIso,
    expires_at: expiresAt,
  };

  const drafts = listChatDrafts().filter((draft) => draft.id !== newDraft.id);
  writeDrafts([newDraft, ...drafts]);
  return newDraft;
}

export function saveChatDraft(input: SaveChatDraftInput): ChatDraft {
  const nowIso = getDefaultOccurredAtIso();
  const drafts = listChatDrafts();
  const existingDraftById = input.draftId ? drafts.find((draft) => draft.id === input.draftId) ?? null : null;
  const existingDraftByThread =
    !existingDraftById && input.threadId ? drafts.find((draft) => draft.thread_id === input.threadId) ?? null : null;
  const existingDraftByTransaction =
    !existingDraftById && !existingDraftByThread && input.kind === 'transaction' && input.transactionId
      ? drafts.find((draft) => draft.kind === 'transaction' && draft.transaction_id === input.transactionId) ?? null
      : null;

  const existingDraft = existingDraftById ?? existingDraftByThread ?? existingDraftByTransaction;
  const draftId = existingDraft?.id ?? input.draftId ?? createId();
  const normalizedMessages = normalizeMessages(input.messages);
  const kind = existingDraft?.kind ?? input.kind;
  const lifecycle = input.lifecycle ?? existingDraft?.lifecycle ?? 'conversation';
  const transactionId = existingDraft?.transaction_id ?? input.transactionId ?? null;
  const threadId = input.threadId ?? existingDraft?.thread_id ?? null;
  const expiresAt =
    lifecycle === 'draft' ? input.expiresAt ?? existingDraft?.expires_at ?? getDefaultDraftExpiryIso(nowIso) : null;
  const explicitTitle = typeof input.title === 'string' ? input.title.trim() : null;
  const hasExplicitTitle = explicitTitle !== null;
  const existingTitle = existingDraft?.title?.trim() ?? '';

  let nextTitle = existingTitle;
  if (hasExplicitTitle) {
    nextTitle = explicitTitle ?? '';
  } else if (!nextTitle) {
    nextTitle = kind === 'general' ? '' : buildTitle(kind, transactionId, normalizedMessages);
  }

  const updatedDraft: ChatDraft = {
    id: draftId,
    kind,
    lifecycle,
    transaction_id: transactionId,
    thread_id: threadId,
    title: nextTitle,
    messages: normalizedMessages,
    updated_at: nowIso,
    expires_at: expiresAt,
  };

  const nextDrafts = [
    updatedDraft,
    ...drafts.filter((draft) => {
      if (draft.id === draftId) {
        return false;
      }

      if (threadId && draft.thread_id === threadId) {
        return false;
      }

      if (
        kind === 'transaction' &&
        transactionId &&
        draft.kind === 'transaction' &&
        draft.transaction_id === transactionId &&
        draft.lifecycle === lifecycle
      ) {
        return false;
      }

      return true;
    }),
  ].sort((first, second) => new Date(second.updated_at).getTime() - new Date(first.updated_at).getTime());

  writeDrafts(nextDrafts);
  return updatedDraft;
}

export function deleteChatDraft(draftId: string): void {
  const nextDrafts = listChatDrafts().filter((draft) => draft.id !== draftId);
  writeDrafts(nextDrafts);
}

export function deleteChatDraftByThreadId(threadId: string): void {
  const nextDrafts = listChatDrafts().filter((draft) => draft.thread_id !== threadId);
  writeDrafts(nextDrafts);
}

export function queueChatDraftTitleGeneration(draftId: string): void {
  if (typeof window === 'undefined') {
    return;
  }

  const draft = getChatDraftById(draftId);
  if (!draft || draft.kind !== 'general') {
    return;
  }

  if (draft.title.trim().length > 0 || titleWorkersByDraftId.has(draftId)) {
    return;
  }

  const firstUserMessage = draft.messages.find((message) => message.role === 'user')?.content.trim();
  if (!firstUserMessage) {
    return;
  }

  if (typeof Worker === 'undefined') {
    const fallbackTitle = summarizeGeneralTitle(firstUserMessage).trim();
    if (!fallbackTitle) {
      return;
    }

    saveChatDraft({
      draftId: draft.id,
      kind: draft.kind,
      lifecycle: draft.lifecycle,
      transactionId: draft.transaction_id,
      threadId: draft.thread_id,
      messages: draft.messages,
      expiresAt: draft.expires_at,
      title: fallbackTitle,
    });
    return;
  }

  const worker = new Worker(new URL('./chatTitle.worker.ts', import.meta.url), { type: 'module' });
  titleWorkersByDraftId.set(draftId, worker);

  const cleanup = () => {
    worker.terminate();
    titleWorkersByDraftId.delete(draftId);
  };

  worker.onmessage = (event: MessageEvent<{ title?: string }>) => {
    cleanup();

    const generatedTitle = event.data?.title?.trim();
    if (!generatedTitle) {
      return;
    }

    const latestDraft = getChatDraftById(draftId);
    if (!latestDraft || latestDraft.kind !== 'general' || latestDraft.title.trim().length > 0) {
      return;
    }

    saveChatDraft({
      draftId: latestDraft.id,
      kind: latestDraft.kind,
      lifecycle: latestDraft.lifecycle,
      transactionId: latestDraft.transaction_id,
      threadId: latestDraft.thread_id,
      messages: latestDraft.messages,
      expiresAt: latestDraft.expires_at,
      title: generatedTitle,
    });
  };

  worker.onerror = () => {
    cleanup();
  };

  worker.postMessage({ firstUserMessage });
}
