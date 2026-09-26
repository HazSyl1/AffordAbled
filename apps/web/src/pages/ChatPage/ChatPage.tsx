import { ImagePlus, Mic } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { BottomSheet } from '../../components/molecules/BottomSheet';
import { CreateTransactionForm } from '../../components/organisms/CreateTransactionForm';
import { Card } from '../../components/atoms/Card';
import { CollapseToggle } from '../../components/atoms/CollapseToggle';
import { Input } from '../../components/atoms/Input';
import { DASHBOARD_CHAT_UI_TEXT, SHEET_TITLES } from '../../constants';
import {
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
  const navigate = useNavigate();
  const [sendChatMessage, { isLoading: isSendingChatMessage }] = useSendChatMessageMutation();
  const [transcribeVoice, { isLoading: isTranscribingVoice }] = useTranscribeVoiceMutation();
  const [drafts, setDrafts] = useState<ChatDraft[]>(() => listChatDrafts());
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<ChatListFilter>('finance');
  const [isSideToolCollapsed, setIsSideToolCollapsed] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [chatError, setChatError] = useState<string | null>(null);
  const [showProposalSheet, setShowProposalSheet] = useState(false);
  const [proposalForSheet, setProposalForSheet] = useState<ChatTransactionProposal | null>(null);
  const [proposalSheetMode, setProposalSheetMode] = useState<'standard' | 'manual_low_confidence'>('standard');
  const voiceFileInputRef = useRef<HTMLInputElement | null>(null);
  const imageFileInputRef = useRef<HTMLInputElement | null>(null);
  const [openingGreeting] = useState(() => {
    const options = DASHBOARD_CHAT_UI_TEXT.rotatingGreetings;
    const selectedGreeting = options[Math.floor(Math.random() * options.length)];

    return selectedGreeting ?? DASHBOARD_CHAT_UI_TEXT.emptyState;
  });

  const selectedDraft = useMemo(
    () => drafts.find((draft) => draft.id === selectedDraftId) ?? null,
    [drafts, selectedDraftId],
  );

  const groupedDrafts = useMemo(() => {
    return {
      financeChats: drafts.filter((draft) => draft.lifecycle === 'conversation' && draft.kind === 'general'),
      draftChats: drafts.filter((draft) => draft.lifecycle === 'draft'),
    };
  }, [drafts]);

  const filteredItems = activeFilter === 'finance' ? groupedDrafts.financeChats : groupedDrafts.draftChats;
  const messageList = selectedDraft?.messages ?? [];
  const proposalInitialValues = useMemo(
    () => (proposalForSheet ? mapProposalToCreateTransactionValues(proposalForSheet) : undefined),
    [proposalForSheet],
  );

  const chatLayoutClass = isSideToolCollapsed
    ? 'grid-cols-1 md:grid-cols-[40px_minmax(0,1fr)]'
    : 'grid-cols-1 md:grid-cols-[340px_minmax(0,1fr)]';

  const refreshDrafts = (preferredDraftId: string | null = selectedDraftId) => {
    const nextDrafts = listChatDrafts();
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

    const createdDraft = createChatDraft('general', null, { lifecycle: 'conversation' });
    refreshDrafts(createdDraft.id);
    setActiveFilter('finance');
    return createdDraft;
  };

  const handleCreateNewChat = () => {
    setSelectedDraftId(null);
    setActiveFilter('finance');
    setChatInput('');
    setChatError(null);
  };

  const handleDeleteDraft = (draftId: string) => {
    deleteChatDraft(draftId);
    refreshDrafts(selectedDraftId === draftId ? null : selectedDraftId);
    setChatError(null);
  };

  const persistDraftMessages = (
    draft: ChatDraft,
    messages: ChatDraftMessage[],
    threadId?: string | null,
    lifecycleOverride?: ChatDraftLifecycle,
  ): ChatDraft => {
    const nextLifecycle = lifecycleOverride ?? draft.lifecycle;
    const savedDraft = saveChatDraft({
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
    queueChatDraftTitleGeneration(optimisticDraft.id);

    try {
      const response = await sendChatMessage({
        message: normalizedMessage,
        thread_id: optimisticDraft.thread_id ?? undefined,
      }).unwrap();

      const assistantMessage: ChatDraftMessage = {
        id: createLocalMessageId(),
        role: 'assistant',
        content: response.message,
      };

      if (optimisticDraft.lifecycle === 'draft' && response.transaction_logged) {
        deleteChatDraft(optimisticDraft.id);
        refreshDrafts(null);
        return;
      }

      if (response.pending_transaction_proposal || response.manual_transaction_input_required) {
        setProposalForSheet(response.pending_transaction_proposal ?? null);
        setProposalSheetMode(response.manual_transaction_input_required ? 'manual_low_confidence' : 'standard');
        setShowProposalSheet(true);
      }

      const nextLifecycle: ChatDraftLifecycle =
        optimisticDraft.lifecycle === 'draft' ? 'conversation' : optimisticDraft.lifecycle;

      persistDraftMessages(
        optimisticDraft,
        [...optimisticMessages, assistantMessage],
        response.thread_id,
        nextLifecycle,
      );

      if (nextLifecycle === 'conversation') {
        setActiveFilter('finance');
      }
    } catch {
      setChatError(DASHBOARD_CHAT_UI_TEXT.assistantError);
    }
  };

  const handleVoiceFileSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const voiceFile = event.target.files?.[0];
    event.target.value = '';

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

    const imagePrompt = `I uploaded an image file (${imageFile.name}). Help me log the transaction from this receipt/bill and ask for any missing fields.`;
    await handleSendMessage(imagePrompt);
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
          <div className='relative min-h-0 flex-1 bg-[var(--bg-card)]'>
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

              <div className='min-h-0 flex-1'>
                {filteredItems.length === 0 ? (
                  <p className='text-sm text-[var(--text-muted)]'>
                    {activeFilter === 'drafts'
                      ? DASHBOARD_CHAT_UI_TEXT.noDraftsLabel
                      : DASHBOARD_CHAT_UI_TEXT.noFinanceChatsLabel}
                  </p>
                ) : (
                  <ul className='m-0 h-full list-none space-y-2 overflow-y-auto p-0'>
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
                                  setSelectedDraftId(draft.id);
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
                'absolute inset-0 inline-flex h-full w-full items-center justify-center border-0 bg-[var(--bg-card)] p-0 text-lg font-semibold leading-none text-[var(--text-muted)] transition-[opacity,color] duration-200 ease-out active:bg-[var(--bg-card)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]',
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

              <div className='mb-3 min-h-0 flex-1 space-y-2 overflow-y-auto rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-3'>
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
                      : 'bg-[var(--bg-card)] text-[var(--text-primary)]'
                  }`}
                >
                  {message.content}
                </div>
              ))
            )}
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
              disabled={isTranscribingVoice || isSendingChatMessage}
              onClick={() => voiceFileInputRef.current?.click()}
            >
              <Mic className='h-4 w-4' strokeWidth={2.2} aria-hidden='true' />
            </button>
            <button
              type='button'
              className='inline-flex h-12 w-12 items-center justify-center rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-card)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)] disabled:cursor-not-allowed disabled:opacity-60'
              aria-label='Upload and send image note'
              disabled={isSendingChatMessage}
              onClick={() => imageFileInputRef.current?.click()}
            >
              <ImagePlus className='h-4 w-4' strokeWidth={2.2} aria-hidden='true' />
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
            ref={voiceFileInputRef}
            type='file'
            accept='audio/*'
            className='hidden'
            onChange={(event) => {
              void handleVoiceFileSelected(event);
            }}
          />
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

      <BottomSheet
        isOpen={showProposalSheet}
        onClose={() => {
          setShowProposalSheet(false);
          setProposalForSheet(null);
          setProposalSheetMode('standard');
        }}
        title={SHEET_TITLES.addTransaction}
      >
        <CreateTransactionForm
          mode='sheet'
          showHeading={false}
          initialValues={proposalInitialValues}
          prefillMode={proposalSheetMode}
          submitLabel={proposalForSheet ? 'Confirm & Add' : 'Add transaction'}
          onSuccess={() => {
            setShowProposalSheet(false);
            setProposalForSheet(null);
            setProposalSheetMode('standard');
            navigate('/transactions');
          }}
        />
      </BottomSheet>
    </div>
  );
}
