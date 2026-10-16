import { ImagePlus, LoaderCircle, Mic } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { useAppSelector } from '../../app/hooks';
import { BottomSheet } from '../../components/molecules/BottomSheet';
import { AssistantReplyIndicator } from '../../components/molecules/AssistantReplyIndicator';
import { AssistantMessageContent } from '../../components/molecules/AssistantMessageContent';
import { VoiceCaptureModal } from '../../components/molecules/VoiceCaptureModal';
import { TransactionSuccessOverlay } from '../../components/molecules/TransactionSuccessOverlay/TransactionSuccessOverlay';
import { CreateTransactionForm } from '../../components/organisms/CreateTransactionForm';
import { Card } from '../../components/atoms/Card';
import { CollapseToggle } from '../../components/atoms/CollapseToggle';
import { Input } from '../../components/atoms/Input';
import { DASHBOARD_CHAT_UI_TEXT, SHEET_TITLES, VOICE_CAPTURE_EVENT_NAME } from '../../constants';
import {
  useAnalyzeImageMutation,
  useLazyGetChatThreadQuery,
  type ChatTransactionProposal,
  useSendChatMessageMutation,
  useTranscribeVoiceMutation,
} from '../../features/chat/chatApi';
import { mapProposalToCreateTransactionValues } from '../../features/chat/chatProposal';
import {
  createChatDraft,
  deleteChatDraft,
  listChatDrafts,
  queueChatDraftTitleGeneration,
  saveChatDraft,
  type ChatDraft,
  type ChatDraftLifecycle,
  type ChatDraftMessage,
} from '../../features/chat/chatDrafts';
import { useVoiceCapture } from '../../features/chat/useVoiceCapture';

type ChatListFilter = 'finance' | 'drafts';

function createLocalMessageId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDraftDeadline(draft: ChatDraft): string | null {
  if (draft.lifecycle !== 'draft' || !draft.expires_at) {
    return null;
  }

  const timeRemainingMs = new Date(draft.expires_at).getTime() - Date.now();
  if (timeRemainingMs <= 0) {
    return 'Expires soon';
  }

  const hoursRemaining = Math.ceil(timeRemainingMs / (60 * 60 * 1000));
  if (hoursRemaining < 24) {
    return `Expires in ${hoursRemaining}h`;
  }

  const daysRemaining = Math.ceil(hoursRemaining / 24);
  return `Expires in ${daysRemaining}d`;
}

export function ChatPage() {
  const userId = useAppSelector((state) => state.auth.user?.id ?? null);

  if (!userId) {
    return <div className='p-6 text-sm text-[var(--text-muted)]'>Loading your chat…</div>;
  }

  return <ChatWorkspace key={userId} userId={userId} />;
}

function ChatWorkspace({ userId }: { userId: string }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [sendChatMessage, { isLoading: isSendingChatMessage }] = useSendChatMessageMutation();
  const [getChatThread] = useLazyGetChatThreadQuery();
  const [transcribeVoice, { isLoading: isTranscribingVoice }] = useTranscribeVoiceMutation();
  const [analyzeImage, { isLoading: isAnalyzingImage }] = useAnalyzeImageMutation();
  const [drafts, setDrafts] = useState<ChatDraft[]>(() => listChatDrafts(userId));
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<ChatListFilter>('finance');
  const [isSideToolCollapsed, setIsSideToolCollapsed] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [chatError, setChatError] = useState<string | null>(null);
  const [showProposalSheet, setShowProposalSheet] = useState(false);
  const [proposalForSheet, setProposalForSheet] = useState<ChatTransactionProposal | null>(null);
  const [proposalQueue, setProposalQueue] = useState<ChatTransactionProposal[]>([]);
  const [proposalBatchTotal, setProposalBatchTotal] = useState(0);
  const [proposalBatchCompleted, setProposalBatchCompleted] = useState(0);
  const [proposalSheetMode, setProposalSheetMode] = useState<'standard' | 'manual_low_confidence'>('standard');
  const [taskSuccess, setTaskSuccess] = useState<{ message: string; expiresAt: number } | null>(null);
  const imageFileInputRef = useRef<HTMLInputElement | null>(null);
  const chatMessagesRef = useRef<HTMLDivElement | null>(null);
  const transactionRedirectTimerRef = useRef<number | null>(null);
  const selectedThreadRequestRef = useRef(0);
  const [openingGreeting] = useState(() => {
    const options = DASHBOARD_CHAT_UI_TEXT.rotatingGreetings;
    const selectedGreeting = options[Math.floor(Math.random() * options.length)];

    return selectedGreeting ?? DASHBOARD_CHAT_UI_TEXT.emptyState;
  });

  const scopedDrafts = drafts;
  const selectedDraft = useMemo(
    () => scopedDrafts.find((draft) => draft.id === selectedDraftId) ?? null,
    [scopedDrafts, selectedDraftId],
  );

  const groupedDrafts = useMemo(() => {
    return {
      // Transaction-specific threads are reached from that transaction's
      // “Chat about this transaction” action, rather than cluttering the
      // general finance-chat list.
      financeChats: scopedDrafts.filter((draft) => draft.kind === 'general' && draft.lifecycle === 'conversation'),
      draftChats: scopedDrafts.filter((draft) => draft.lifecycle === 'draft'),
    };
  }, [scopedDrafts]);

  const filteredItems = activeFilter === 'finance' ? groupedDrafts.financeChats : groupedDrafts.draftChats;
  const messageList = selectedDraft?.messages ?? [];
  const isAssistantResponding = isSendingChatMessage;
  const proposalInitialValues = useMemo(
    () => (proposalForSheet ? mapProposalToCreateTransactionValues(proposalForSheet) : undefined),
    [proposalForSheet],
  );

  const chatLayoutClass = isSideToolCollapsed
    ? 'grid-cols-1 md:grid-cols-[40px_minmax(0,1fr)]'
    : 'grid-cols-1 md:grid-cols-[340px_minmax(0,1fr)]';

  const refreshDrafts = (preferredDraftId: string | null = selectedDraftId) => {
    const nextDrafts = listChatDrafts(userId);
    setDrafts(nextDrafts);

    if (!preferredDraftId) {
      setSelectedDraftId(null);
      return;
    }

    const exists = nextDrafts.some((draft) => draft.id === preferredDraftId);
    setSelectedDraftId(exists ? preferredDraftId : null);
  };

  const ensureSelectedDraft = (): ChatDraft => {
    if (selectedDraft) {
      return selectedDraft;
    }

    const createdDraft = createChatDraft(userId, 'general', null, { lifecycle: 'conversation' });
    refreshDrafts(createdDraft.id);
    setActiveFilter('finance');
    return createdDraft;
  };

  const handleCreateNewChat = () => {
    selectedThreadRequestRef.current += 1;
    setSelectedDraftId(null);
    setActiveFilter('finance');
    setChatInput('');
    setChatError(null);
  };

  const handleDeleteDraft = (draftId: string) => {
    if (selectedDraftId === draftId) {
      selectedThreadRequestRef.current += 1;
    }
    deleteChatDraft(userId, draftId);
    refreshDrafts(selectedDraftId === draftId ? null : selectedDraftId);
    setChatError(null);
  };

  const clearTaskSuccessTimer = () => {
    if (transactionRedirectTimerRef.current !== null) {
      window.clearTimeout(transactionRedirectTimerRef.current);
      transactionRedirectTimerRef.current = null;
    }
  };

  const closeTaskSuccess = () => {
    clearTaskSuccessTimer();
    setTaskSuccess(null);
    navigate('/');
  };

  const continueChatting = () => {
    clearTaskSuccessTimer();
    setTaskSuccess(null);
  };

  const handleSelectDraft = async (draft: ChatDraft) => {
    const requestId = selectedThreadRequestRef.current + 1;
    selectedThreadRequestRef.current = requestId;
    setSelectedDraftId(draft.id);
    setChatError(null);

    if (!draft.thread_id) {
      return;
    }

    try {
      const detail = await getChatThread(draft.thread_id).unwrap();
      if (selectedThreadRequestRef.current !== requestId) {
        return;
      }

      const messages: ChatDraftMessage[] = detail.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
      }));
      const hydratedDraft = saveChatDraft({
        userId,
        draftId: draft.id,
        kind: draft.kind,
        lifecycle: draft.lifecycle,
        transactionId: draft.transaction_id,
        threadId: draft.thread_id,
        messages: messages.length > 0 ? messages : draft.messages,
        expiresAt: draft.expires_at,
        title: detail.thread.title ?? draft.title,
        preserveUpdatedAt: true,
      });

      setDrafts(listChatDrafts(userId));
      setSelectedDraftId(hydratedDraft.id);
    } catch {
      // A locally stored conversation remains usable if server history is
      // unavailable (for example, when the user disabled storage).
    }
  };

  const persistDraftMessages = (
    draft: ChatDraft,
    messages: ChatDraftMessage[],
    threadId?: string | null,
    lifecycleOverride?: ChatDraftLifecycle,
  ): ChatDraft => {
    const nextLifecycle = lifecycleOverride ?? draft.lifecycle;
    const savedDraft = saveChatDraft({
      userId,
      draftId: draft.id,
      kind: draft.kind,
      lifecycle: nextLifecycle,
      transactionId: draft.transaction_id,
      threadId: threadId ?? draft.thread_id,
      messages,
      expiresAt: nextLifecycle === 'draft' ? draft.expires_at : null,
    });

    refreshDrafts(savedDraft.id);
    return savedDraft;
  };

  const handleSendMessage = async (messageOverride?: string) => {
    const normalizedMessage = (messageOverride ?? chatInput).trim();
    if (!normalizedMessage || isSendingChatMessage) {
      return;
    }
    setIsSideToolCollapsed(true);

    const draft = ensureSelectedDraft();
    const userMessage: ChatDraftMessage = {
      id: createLocalMessageId(),
      role: 'user',
      content: normalizedMessage,
    };

    if (!messageOverride) {
      setChatInput('');
    }
    setChatError(null);

    const optimisticMessages = [...draft.messages, userMessage];
    const optimisticDraft = persistDraftMessages(draft, optimisticMessages);
    queueChatDraftTitleGeneration(userId, optimisticDraft.id);

    try {
      const response = await sendChatMessage({
        message: normalizedMessage,
        thread_id: optimisticDraft.thread_id ?? undefined,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }).unwrap();

      const insightSummary = (response.insights ?? [])
        .map((insight) => `• ${insight.title}: ${insight.detail}`)
        .join('\n');
      const assistantMessage: ChatDraftMessage = {
        id: createLocalMessageId(),
        role: 'assistant',
        content: insightSummary ? `${response.message}\n${insightSummary}` : response.message,
      };

      if (response.pending_transaction_proposal || response.manual_transaction_input_required) {
        const proposalBatch = response.pending_transaction_proposals ?? [];
        setProposalQueue(proposalBatch);
        setProposalBatchTotal(proposalBatch.length);
        setProposalBatchCompleted(0);
        setProposalForSheet(proposalBatch[0] ?? response.pending_transaction_proposal ?? null);
        setProposalSheetMode(response.manual_transaction_input_required ? 'manual_low_confidence' : 'standard');
        setShowProposalSheet(true);
      }

      const nextLifecycle: ChatDraftLifecycle =
        optimisticDraft.lifecycle === 'draft' ? 'conversation' : optimisticDraft.lifecycle;

      const completedMessages = [...optimisticMessages, assistantMessage];
      if (response.tasks_completed) {
        // Keep the server-backed thread, but move its local entry from the
        // general chat list to the created transaction. It can be reopened
        // from that transaction's dedicated chat action.
        let savedDraft: ChatDraft;
        if (response.transaction_logged && response.created_transaction_id) {
          deleteChatDraft(userId, optimisticDraft.id);
          savedDraft = saveChatDraft({
            userId,
            kind: 'transaction',
            lifecycle: 'conversation',
            transactionId: response.created_transaction_id,
            threadId: response.thread_id,
            messages: completedMessages,
          });
        } else {
          savedDraft = persistDraftMessages(optimisticDraft, completedMessages, response.thread_id, nextLifecycle);
        }
        refreshDrafts(savedDraft.id);
        setActiveFilter('finance');
        if (response.show_completion_popup) {
          clearTaskSuccessTimer();
          setTaskSuccess({ message: assistantMessage.content, expiresAt: Date.now() + 8_000 });
          transactionRedirectTimerRef.current = window.setTimeout(() => {
            transactionRedirectTimerRef.current = null;
            setTaskSuccess(null);
            navigate('/');
          }, 8_000);
        }
        return;
      }

      persistDraftMessages(optimisticDraft, completedMessages, response.thread_id, nextLifecycle);

      if (nextLifecycle === 'conversation') {
        setActiveFilter('finance');
      }
    } catch {
      setChatError(DASHBOARD_CHAT_UI_TEXT.assistantError);
    }
  };

  const handleRecordedVoice = async (voiceFile: File) => {
    if (!voiceFile) {
      return;
    }

    try {
      setChatError(null);
      const transcription = await transcribeVoice({ audio: voiceFile, locale: 'en-IN' }).unwrap();
      const transcript = transcription.transcript.trim();

      if (!transcript) {
        setChatError(DASHBOARD_CHAT_UI_TEXT.voiceError);
        return;
      }

      await handleSendMessage(transcript);
    } catch {
      setChatError(DASHBOARD_CHAT_UI_TEXT.voiceError);
    }
  };

  const {
    cancelCapture,
    elapsedSeconds,
    isOpen: isVoiceCaptureOpen,
    isProcessing: isVoiceCaptureProcessing,
    startCapture,
    stopCapture,
  } = useVoiceCapture({
    maxDurationSeconds: DASHBOARD_CHAT_UI_TEXT.voiceRecordingMaxDurationSeconds,
    onRecorded: handleRecordedVoice,
    onError: (reason) => {
      if (reason === 'permission_denied') {
        setChatError(DASHBOARD_CHAT_UI_TEXT.voicePermissionError);
        return;
      }
      if (reason === 'unsupported') {
        setChatError(DASHBOARD_CHAT_UI_TEXT.voiceUnsupportedError);
        return;
      }
      setChatError(DASHBOARD_CHAT_UI_TEXT.voiceError);
    },
  });

  useEffect(() => {
    return () => {
      if (transactionRedirectTimerRef.current !== null) {
        window.clearTimeout(transactionRedirectTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const container = chatMessagesRef.current;
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    }
  }, [messageList.length, isAssistantResponding]);

  useEffect(() => {
    const handleVoiceCaptureRequest = (event: Event) => {
      const customEvent = event as CustomEvent<{ handled?: boolean }>;
      if (customEvent.detail) {
        customEvent.detail.handled = true;
      }

      setChatError(null);
      void startCapture();
    };

    window.addEventListener(VOICE_CAPTURE_EVENT_NAME, handleVoiceCaptureRequest as EventListener);
    return () => {
      window.removeEventListener(VOICE_CAPTURE_EVENT_NAME, handleVoiceCaptureRequest as EventListener);
    };
  }, [startCapture]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('voice') !== '1') {
      return;
    }

    if (!isVoiceCaptureOpen && !isVoiceCaptureProcessing) {
      void startCapture();
    }

    params.delete('voice');
    const nextSearch = params.toString();
    navigate(
      {
        pathname: '/chat',
        search: nextSearch ? '?' + nextSearch : '',
      },
      { replace: true },
    );
  }, [isVoiceCaptureOpen, isVoiceCaptureProcessing, location.search, navigate, startCapture]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const transactionId = params.get('transaction_id')?.trim();
    if (!transactionId) {
      return;
    }

    const existingDraft = listChatDrafts(userId).find(
      (draft) => draft.kind === 'transaction' && draft.transaction_id === transactionId,
    );
    const transactionDraft =
      existingDraft ?? createChatDraft(userId, 'transaction', transactionId, { lifecycle: 'conversation' });
    const nextDrafts = listChatDrafts(userId);

    queueMicrotask(() => {
      setDrafts(nextDrafts);
      setSelectedDraftId(transactionDraft.id);
      setActiveFilter('finance');
      setChatInput('');
      setChatError(null);
    });

    params.delete('transaction_id');
    const nextSearch = params.toString();
    navigate(
      {
        pathname: '/chat',
        search: nextSearch ? `?${nextSearch}` : '',
      },
      { replace: true },
    );
  }, [location.search, navigate, userId]);

  const handleImageFileSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const imageFile = event.target.files?.[0];
    event.target.value = '';

    if (!imageFile) {
      return;
    }

    if (!imageFile.type.startsWith('image/')) {
      setChatError('Please select a valid image file.');
      return;
    }

    try {
      setChatError(null);
      const analysis = await analyzeImage({ image: imageFile }).unwrap();
      const imagePrompt = analysis.prompt.trim();

      if (!imagePrompt) {
        setChatError(DASHBOARD_CHAT_UI_TEXT.imageError);
        return;
      }

      await handleSendMessage(imagePrompt);
    } catch {
      setChatError(DASHBOARD_CHAT_UI_TEXT.imageError);
    }
  };

  return (
    <div className='flex h-[calc(100vh-5.5rem)] w-full flex-col px-4 py-4 md:h-[calc(100vh-2rem)] md:px-4 md:pb-0 md:pt-0'>
      <header className='mb-4 md:hidden'>
        <div>
          <h1 className='text-xl font-bold text-[var(--text-primary)]'>Finance Chat</h1>
          <p className='text-sm text-[var(--text-muted)]'>Continue where you left off or start a fresh chat.</p>
        </div>
      </header>

      <div
        className={[
          'grid min-h-0 flex-1 gap-4 md:gap-0 md:transition-[grid-template-columns] md:duration-500 md:ease-[cubic-bezier(0.22,1,0.36,1)]',
          chatLayoutClass,
        ].join(' ')}
      >
        <Card
          className={[
            'flex min-h-0 flex-col overflow-hidden transition-[padding,background-color] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] md:rounded-r-none md:border-r-0',
            isSideToolCollapsed ? 'p-0' : 'p-3',
          ].join(' ')}
        >
          <div className='relative flex min-h-0 flex-1 flex-col bg-[var(--bg-card)]'>
            <div
              className={[
                'flex min-h-0 flex-1 flex-col transition-opacity duration-150 ease-out',
                isSideToolCollapsed ? 'pointer-events-none invisible opacity-0' : 'pointer-events-auto visible opacity-100',
              ].join(' ')}
            >
              <div className='mb-3 flex items-center gap-2'>
                <button
                  type='button'
                  className={[
                    'inline-flex min-h-12 items-center rounded-full px-5 text-sm font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]',
                    activeFilter === 'finance'
                      ? 'bg-[var(--brand-primary)] text-white'
                      : 'bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:bg-[var(--bg-card)]',
                  ].join(' ')}
                  onClick={() => setActiveFilter('finance')}
                  aria-pressed={activeFilter === 'finance'}
                >
                  {DASHBOARD_CHAT_UI_TEXT.financePillLabel}
                </button>
                <button
                  type='button'
                  className={[
                    'inline-flex min-h-12 items-center rounded-full px-5 text-sm font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]',
                    activeFilter === 'drafts'
                      ? 'bg-[var(--brand-primary)] text-white'
                      : 'bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:bg-[var(--bg-card)]',
                  ].join(' ')}
                  onClick={() => setActiveFilter('drafts')}
                  aria-pressed={activeFilter === 'drafts'}
                >
                  {DASHBOARD_CHAT_UI_TEXT.draftsPillLabel}
                </button>
              </div>

              {activeFilter === 'drafts' ? (
                <p className='mb-2 text-xs text-[var(--text-muted)]'>{DASHBOARD_CHAT_UI_TEXT.draftExpiryDisclaimer}</p>
              ) : null}

              <div className='min-h-0 flex-1 overflow-y-auto'>
                {filteredItems.length === 0 ? (
                  <p className='text-sm text-[var(--text-muted)]'>
                    {activeFilter === 'drafts'
                      ? DASHBOARD_CHAT_UI_TEXT.noDraftsLabel
                      : DASHBOARD_CHAT_UI_TEXT.noFinanceChatsLabel}
                  </p>
                ) : (
                  <ul className='m-0 list-none space-y-2 p-0'>
                    {filteredItems.map((draft) => {
                      const isActive = draft.id === selectedDraftId;
                      const deadline = formatDraftDeadline(draft);

                      return (
                        <li key={draft.id}>
                          <div
                            className={[
                              'rounded-xl border px-2 py-2 transition-colors',
                              isActive
                                ? 'border-[var(--brand-primary)] bg-[var(--brand-subtle)]'
                                : 'border-[var(--bg-border)] bg-[var(--bg-elevated)]',
                            ].join(' ')}
                          >
                            <div className='flex items-start gap-2'>
                              <button
                                type='button'
                                onClick={() => {
                                  void handleSelectDraft(draft);
                                }}
                                className='min-w-0 flex-1 text-left'
                              >
                                <p className='truncate text-sm font-semibold text-[var(--text-primary)]'>{draft.title}</p>
                                <p className='mt-1 text-xs text-[var(--text-muted)]'>
                                  {draft.messages.length} msgs - {formatTimestamp(draft.updated_at)}
                                </p>
                                {deadline ? <p className='mt-1 text-[11px] text-[var(--negative)]'>{deadline}</p> : null}
                              </button>

                              {draft.lifecycle === 'draft' ? (
                                <button
                                  type='button'
                                  aria-label='Discard draft'
                                  className='inline-flex h-8 w-8 items-center justify-center rounded-full border border-[var(--bg-border)] bg-[var(--bg-card)] text-sm leading-none text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]'
                                  onClick={() => handleDeleteDraft(draft.id)}
                                >
                                  X
                                </button>
                              ) : null}
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>

              <div className='mt-3 border-t border-[var(--bg-border)] pt-3'>
                <div className='flex w-full items-center gap-3'>
                  <button
                    type='button'
                    className='inline-flex h-10 min-h-10 min-w-0 flex-1 items-center justify-center rounded-full bg-[var(--brand-primary)] px-4 text-sm font-semibold text-white transition-colors hover:bg-[var(--brand-hover)] active:bg-[var(--brand-active)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]'
                    onClick={handleCreateNewChat}
                  >
                    {DASHBOARD_CHAT_UI_TEXT.newChatActionLabel}
                  </button>
                  <CollapseToggle
                    className='h-10 w-10 shrink-0'
                    ariaLabel={DASHBOARD_CHAT_UI_TEXT.collapseSideToolAriaLabel}
                    direction='left'
                    onClick={() => setIsSideToolCollapsed(true)}
                  />
                </div>
              </div>
            </div>

            <button
              type='button'
              aria-label={DASHBOARD_CHAT_UI_TEXT.expandSideToolAriaLabel}
              className={[
                'absolute inset-0 z-10 inline-flex h-full w-full items-center justify-center border-0 bg-[var(--bg-card)] p-0 text-lg font-semibold leading-none text-[var(--text-muted)] transition-[opacity,color] duration-200 ease-out active:bg-[var(--bg-card)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]',
                isSideToolCollapsed ? 'pointer-events-auto opacity-100 hover:text-[var(--text-primary)]' : 'pointer-events-none opacity-0',
              ].join(' ')}
              onClick={() => setIsSideToolCollapsed(false)}
            >
              &gt;
            </button>
          </div>
        </Card>

        <Card className='flex min-h-0 flex-col p-4 md:rounded-l-none'>
          <div className='mb-3'>
            {(selectedDraft?.title ?? '').trim().length > 0 ? (
              <h2 className='text-lg font-semibold text-[var(--text-primary)]'>{selectedDraft?.title}</h2>
            ) : null}
            {selectedDraft ? (
              <>
                <p className='text-xs text-[var(--text-muted)]'>
                  {selectedDraft.lifecycle === 'draft' ? 'Draft' : DASHBOARD_CHAT_UI_TEXT.financePillLabel} -{' '}
                  {formatTimestamp(selectedDraft.updated_at)}
                </p>
                {selectedDraft.lifecycle === 'draft' && selectedDraft.expires_at ? (
                  <p className='text-xs text-[var(--negative)]'>Expires at {formatTimestamp(selectedDraft.expires_at)}</p>
                ) : null}
              </>
            ) : null}
          </div>

              <div
                ref={chatMessagesRef}
                className='mb-3 min-h-0 flex-1 space-y-2 overflow-y-auto rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-3'
              >
                {messageList.length === 0 ? (
                  <div className='flex h-full flex-col items-center justify-center px-5 text-center'>
                    <p className='mb-2 text-base font-semibold text-[var(--text-primary)]'>{openingGreeting}</p>
                    <p className='max-w-xl text-sm text-[var(--text-muted)]'>{DASHBOARD_CHAT_UI_TEXT.emptyState}</p>
                  </div>
                ) : (
              messageList.map((message) => (
                <div
                  key={message.id}
                  className={`max-w-[92%] rounded-xl px-3 py-2 text-sm ${
                    message.role === 'user'
                      ? 'ml-auto bg-[var(--brand-primary)] text-white'
                      : 'whitespace-pre-line bg-[var(--bg-card)] text-[var(--text-primary)]'
                  }`}
                >
                  {message.role === 'assistant' ? (
                    <AssistantMessageContent content={message.content} />
                  ) : (
                    message.content
                  )}
                </div>
              ))
            )}

            {isAssistantResponding ? <AssistantReplyIndicator label={DASHBOARD_CHAT_UI_TEXT.assistantReplyingLabel} /> : null}
          </div>

          {chatError ? (
            <p className='mb-2 text-sm text-[var(--negative)]' role='alert'>
              {chatError}
            </p>
          ) : null}

          <div className='flex items-center gap-2'>
            <button
              type='button'
              className='inline-flex h-12 w-12 items-center justify-center rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-card)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)] disabled:cursor-not-allowed disabled:opacity-60'
              aria-label='Transcribe and send voice note'
              disabled={isVoiceCaptureOpen || isTranscribingVoice}
              onClick={() => {
                void startCapture();
              }}
            >
              <Mic className='h-4 w-4' strokeWidth={2.2} aria-hidden='true' />
            </button>
            <button
              type='button'
              className='inline-flex h-12 w-12 items-center justify-center rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-card)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)] disabled:cursor-not-allowed disabled:opacity-60'
              aria-label='Upload and send image note'
              disabled={isSendingChatMessage || isAnalyzingImage}
              onClick={() => imageFileInputRef.current?.click()}
            >
              {isAnalyzingImage ? (
                <LoaderCircle className='h-4 w-4 animate-spin' strokeWidth={2.2} aria-hidden='true' />
              ) : (
                <ImagePlus className='h-4 w-4' strokeWidth={2.2} aria-hidden='true' />
              )}
            </button>
            <Input
              value={chatInput}
              placeholder={DASHBOARD_CHAT_UI_TEXT.inputPlaceholder}
              onChange={(event) => setChatInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  void handleSendMessage();
                }
              }}
            />
            <button
              type='button'
              className='inline-flex h-12 min-w-16 items-center justify-center rounded-xl bg-[var(--brand-primary)] px-4 text-sm font-semibold text-white transition-colors hover:bg-[var(--brand-hover)] active:bg-[var(--brand-active)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)] disabled:cursor-not-allowed disabled:opacity-60'
              disabled={chatInput.trim().length === 0 || isSendingChatMessage}
              onClick={() => {
                void handleSendMessage();
              }}
            >
              {DASHBOARD_CHAT_UI_TEXT.sendButton}
            </button>
          </div>

          <input
            ref={imageFileInputRef}
            type='file'
            accept='image/*'
            className='hidden'
            onChange={(event) => {
              void handleImageFileSelected(event);
            }}
          />
        </Card>
      </div>

      <VoiceCaptureModal
        cancelLabel={DASHBOARD_CHAT_UI_TEXT.voiceRecordingCancelButton}
        isOpen={isVoiceCaptureOpen}
        isProcessing={isVoiceCaptureProcessing}
        elapsedSeconds={elapsedSeconds}
        onCancel={cancelCapture}
        onStop={stopCapture}
        title={DASHBOARD_CHAT_UI_TEXT.voiceRecordingTitle}
        recordingLabel={DASHBOARD_CHAT_UI_TEXT.voiceRecordingActiveLabel}
        processingLabel={DASHBOARD_CHAT_UI_TEXT.voiceRecordingProcessingLabel}
        stopLabel={DASHBOARD_CHAT_UI_TEXT.voiceRecordingStopButton}
      />

      {taskSuccess ? (
        <TransactionSuccessOverlay
          message={taskSuccess.message}
          expiresAt={taskSuccess.expiresAt}
          onClose={closeTaskSuccess}
          onContinue={continueChatting}
        />
      ) : null}

      <BottomSheet
        isOpen={showProposalSheet}
        onClose={() => {
          setShowProposalSheet(false);
          setProposalForSheet(null);
          setProposalQueue([]);
          setProposalBatchTotal(0);
          setProposalBatchCompleted(0);
          setProposalSheetMode('standard');
        }}
        title={
          proposalBatchTotal > 1
            ? `${SHEET_TITLES.addTransaction} (${proposalBatchCompleted + 1} of ${proposalBatchTotal})`
            : SHEET_TITLES.addTransaction
        }
      >
        <CreateTransactionForm
          mode='sheet'
          showHeading={false}
          initialValues={proposalInitialValues}
          proposalCategory={
            proposalForSheet && proposalForSheet.type !== 'transfer'
              ? {
                  id: proposalForSheet.category_id,
                  name: proposalForSheet.category_name,
                  type: proposalForSheet.type === 'expense' ? 'expense' : 'income',
                }
              : undefined
          }
          prefillMode={proposalSheetMode}
          submitLabel={proposalForSheet ? 'Confirm & Add' : 'Add transaction'}
          onSuccess={() => {
            if (proposalQueue.length > 1) {
              const remainingQueue = proposalQueue.slice(1);
              setProposalQueue(remainingQueue);
              setProposalBatchCompleted((completed) => completed + 1);
              setProposalForSheet(remainingQueue[0]);
              refreshDrafts(selectedDraftId);
              return;
            }
            if (proposalBatchTotal > 0) {
              setShowProposalSheet(false);
              setProposalForSheet(null);
              setProposalQueue([]);
              setProposalBatchTotal(0);
              setProposalBatchCompleted(0);
              setProposalSheetMode('standard');
              refreshDrafts(selectedDraftId);
              return;
            }
            setShowProposalSheet(false);
            setProposalForSheet(null);
            setProposalQueue([]);
            setProposalBatchTotal(0);
            setProposalBatchCompleted(0);
            setProposalSheetMode('standard');
            refreshDrafts(selectedDraftId);
            navigate('/transactions');
          }}
        />
      </BottomSheet>
    </div>
  );
}
