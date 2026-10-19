import { ImagePlus, LoaderCircle, Mic } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useAppSelector } from '../../app/hooks';
import type { AuthUser } from '../auth/authSlice';
import { Badge } from '../../components/atoms/Badge';
import { Button } from '../../components/atoms/Button';
import { Card } from '../../components/atoms/Card';
import { Input } from '../../components/atoms/Input';
import { AssistantReplyIndicator } from '../../components/molecules/AssistantReplyIndicator';
import { AssistantMessageContent } from '../../components/molecules/AssistantMessageContent';
import { BottomSheet } from '../../components/molecules/BottomSheet';
import { VoiceCaptureModal } from '../../components/molecules/VoiceCaptureModal';
import { TransactionSuccessOverlay } from '../../components/molecules/TransactionSuccessOverlay/TransactionSuccessOverlay';
import { MemorySuggestionsPanel } from '../../components/molecules/MemorySuggestionsPanel/MemorySuggestionsPanel';
import { CreateTransactionForm } from '../../components/organisms/CreateTransactionForm';
import { useListAccountsQuery } from '../accounts/accountsApi';
import { useListCategoriesQuery } from '../categories/categoriesApi';
import {
  useAnalyzeImageMutation,
  type ChatTransactionProposal,
  useSendChatMessageMutation,
  useTranscribeVoiceMutation,
} from '../chat/chatApi';
import { mapProposalToCreateTransactionValues } from '../chat/chatProposal';
import {
  deleteChatDraft,
  deleteChatDraftByThreadId,
  queueChatDraftTitleGeneration,
  saveChatDraft,
} from '../chat/chatDrafts';
import { useVoiceCapture } from '../chat/useVoiceCapture';
import { useListTransactionsQuery } from '../transactions/transactionsApi';
import { useListSplitsQuery } from '../splits/splitsApi';
import { useListMemorySuggestionsQuery } from '../memory/memoryApi';
import type { TransactionType } from '../transactions/transactionsApi';
import {
  DASHBOARD_CHAT_UI_TEXT,
  DASHBOARD_QUICK_ACTIONS,
  type DashboardQuickActionKey,
  SHEET_TITLES,
  VOICE_CAPTURE_EVENT_NAME,
} from '../../constants';
import { formatPaiseAsInr } from '../../lib/money';

interface PendingSplit {
  id: string;
  name: string;
  split_count: number;
  total_pending_paise: number;
  avatar_color: string;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

const TYPE_BADGE_TONE: Record<TransactionType, 'negative' | 'positive' | 'info'> = {
  expense: 'negative',
  income: 'positive',
  transfer: 'info',
  refund: 'positive',
};

function createLocalId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function formatTransactionTime(value: string): string {
  return new Date(value).toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function DashboardPage() {
  const currentUser = useAppSelector((state) => state.auth.user);
  return <DashboardContent key={currentUser?.id ?? 'profile-loading'} currentUser={currentUser} />;
}

function DashboardContent({ currentUser }: { currentUser: AuthUser | null }) {
  const navigate = useNavigate();
  const [currentHour, setCurrentHour] = useState(() => new Date().getHours());
  const { data: accounts, isLoading: isLoadingAccounts } = useListAccountsQuery();
  const { data: transactions, isLoading: isLoadingTransactions } = useListTransactionsQuery();
  const { data: splits, isLoading: isLoadingSplits } = useListSplitsQuery();
  const { data: categories } = useListCategoriesQuery();
  const [sendChatMessage, { isLoading: isSendingChatMessage }] = useSendChatMessageMutation();
  const [transcribeVoice, { isLoading: isTranscribingVoice }] = useTranscribeVoiceMutation();
  const [analyzeImage, { isLoading: isAnalyzingImage }] = useAnalyzeImageMutation();
  const [showAddSheet, setShowAddSheet] = useState(false);
  const [showChatSheet, setShowChatSheet] = useState(false);
  const [isImageProcessing, setIsImageProcessing] = useState(false);
  const [showSaveDraftPrompt, setShowSaveDraftPrompt] = useState(false);
  const [proposalForSheet, setProposalForSheet] = useState<ChatTransactionProposal | null>(null);
  const [proposalQueue, setProposalQueue] = useState<ChatTransactionProposal[]>([]);
  const [proposalBatchTotal, setProposalBatchTotal] = useState(0);
  const [proposalBatchCompleted, setProposalBatchCompleted] = useState(0);
  const [proposalSheetMode, setProposalSheetMode] = useState<'standard' | 'manual_low_confidence'>('standard');
  const [chatInput, setChatInput] = useState('');
  const [chatThreadId, setChatThreadId] = useState<string | null>(null);
  const [chatDraftId, setChatDraftId] = useState<string | null>(null);
  const [chatTransactionId, setChatTransactionId] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatError, setChatError] = useState<string | null>(null);
  const [manualFallbackMessage, setManualFallbackMessage] = useState<string | null>(null);
  const receiptUploadRef = useRef(false);
  const [transactionSuccess, setTransactionSuccess] = useState<{ message: string; expiresAt: number; transactionId: string | null } | null>(null);
  const [editingTransactionId, setEditingTransactionId] = useState<string | null>(null);
  const [editingTransactionValues, setEditingTransactionValues] = useState<Record<string, string> | undefined>();
  const [showMemorySuggestions, setShowMemorySuggestions] = useState(true);
  const [isNotificationCenterOpen, setIsNotificationCenterOpen] = useState(false);
  const { data: memorySuggestions = [] } = useListMemorySuggestionsQuery(undefined, { pollingInterval: 10_000 });
  useEffect(() => {
    if (memorySuggestions.length === 0) return;
    const reminderTimer = window.setInterval(() => {
      setShowMemorySuggestions(true);
    }, 5 * 60 * 1000);
    return () => window.clearInterval(reminderTimer);
  }, [memorySuggestions.length]);

  const imageFileInputRef = useRef<HTMLInputElement | null>(null);
  const transactionRedirectTimerRef = useRef<number | null>(null);
  const [openingGreeting] = useState(() => {
    const options = DASHBOARD_CHAT_UI_TEXT.rotatingGreetings;
    return options[Math.floor(Math.random() * options.length)] ?? DASHBOARD_CHAT_UI_TEXT.emptyState;
  });

  const pendingSplits = useMemo<PendingSplit[]>(() => {
    const byName = new Map<string, PendingSplit>();
    for (const split of splits ?? []) {
      for (const participant of split.participants) {
        const due = participant.share_paise - participant.settled_paise;
        if (due <= 0) continue;
        const key = participant.name.toLocaleLowerCase();
        const current = byName.get(key) ?? {
          id: key, name: participant.name, split_count: 0,
          total_pending_paise: 0, avatar_color: '#a855f7',
        };
        current.split_count += 1;
        current.total_pending_paise += due;
        byName.set(key, current);
      }
    }
    return [...byName.values()].sort((a, b) => b.total_pending_paise - a.total_pending_paise);
  }, [splits]);

  const proposalInitialValues = useMemo(
    () => (proposalForSheet ? mapProposalToCreateTransactionValues(proposalForSheet) : undefined),
    [proposalForSheet],
  );

  const openManualTransactionFallback = (message: string) => {
    receiptUploadRef.current = false;
    setProposalForSheet(null);
    setProposalQueue([]);
    setProposalBatchTotal(0);
    setProposalBatchCompleted(0);
    setProposalSheetMode('standard');
    setEditingTransactionId(null);
    setEditingTransactionValues(undefined);
    setManualFallbackMessage(message);
    setShowAddSheet(true);
  };

  const categoryNameById = useMemo(() => {
    return new Map((categories ?? []).map((category) => [category.id, category.name]));
  }, [categories]);

  const totalBalancePaise = useMemo(() => {
    return (accounts ?? []).reduce((total, account) => total + account.balance_paise, 0);
  }, [accounts]);

  const visibleTransactions = useMemo(() => {
    return (transactions ?? [])
      .filter((transaction) => transaction.deleted_at === null)
      .sort((a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime());
  }, [transactions]);

  const recentTransactions = useMemo(() => {
    return visibleTransactions.slice(0, 5);
  }, [visibleTransactions]);

  const thisMonthSummary = useMemo(() => {
    const now = new Date();
    const month = now.getMonth();
    const year = now.getFullYear();

    let expensesPaise = 0;
    let incomePaise = 0;
    const byCategory = new Map<string, number>();

    for (const transaction of visibleTransactions) {
      const occurredAt = new Date(transaction.occurred_at);
      if (occurredAt.getMonth() !== month || occurredAt.getFullYear() !== year) {
        continue;
      }

      if (transaction.type === 'expense') {
        expensesPaise += transaction.amount_paise;
        const categoryKey = transaction.category_id ?? 'uncategorized';
        byCategory.set(categoryKey, (byCategory.get(categoryKey) ?? 0) + transaction.amount_paise);
      }

      if (transaction.type === 'income' || transaction.type === 'refund') {
        incomePaise += transaction.amount_paise;
      }
    }

    const topCategories = Array.from(byCategory.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([categoryId, amountPaise]) => ({
        categoryId,
        name: categoryId === 'uncategorized' ? 'Uncategorized' : categoryNameById.get(categoryId) ?? 'Unknown',
        amountPaise,
      }));

    const progress = incomePaise > 0 ? Math.min(100, Math.round((expensesPaise / incomePaise) * 100)) : 100;

    return {
      expensesPaise,
      incomePaise,
      progress,
      topCategories,
    };
  }, [categoryNameById, visibleTransactions]);

  const isLoading = isLoadingAccounts || isLoadingTransactions;
  const isAssistantResponding = isSendingChatMessage;
  const greetingName = currentUser?.name?.trim().split(/\s+/)[0] || 'there';
  const greeting = currentHour < 12 ? 'Good morning' : currentHour < 17 ? 'Good afternoon' : 'Good evening';

  useEffect(() => {
    const updateGreetingHour = () => setCurrentHour(new Date().getHours());
    const intervalId = window.setInterval(updateGreetingHour, 60_000);
    return () => window.clearInterval(intervalId);
  }, []);

  useEffect(() => {
    return () => {
      if (transactionRedirectTimerRef.current !== null) {
        window.clearTimeout(transactionRedirectTimerRef.current);
      }
    };
  }, []);

  const persistGeneralDraft = (
    messages: ChatMessage[],
    threadId: string | null,
    draftIdOverride: string | null = chatDraftId,
    lifecycle: 'conversation' | 'draft' = 'conversation',
    kind: 'general' | 'transaction' = chatTransactionId ? 'transaction' : 'general',
    transactionId: string | null = chatTransactionId,
  ): string | null => {
    if (messages.length === 0 || !currentUser?.id) {
      return draftIdOverride;
    }

    const savedDraft = saveChatDraft({
      userId: currentUser.id,
      draftId: draftIdOverride,
      kind,
      // A dashboard chat has been sent to the assistant, so keep it in the
      // conversation list even when it is an analytics or split question.
      lifecycle,
      transactionId,
      threadId,
      messages,
    });

    setChatDraftId(savedDraft.id);
    return savedDraft.id;
  };

  const resetChatSession = () => {
    setShowChatSheet(false);
    setShowAddSheet(false);
    setProposalForSheet(null);
    setProposalQueue([]);
    setProposalBatchTotal(0);
    setProposalBatchCompleted(0);
    setProposalSheetMode('standard');
    setChatInput('');
    setChatDraftId(null);
    setChatTransactionId(null);
    setChatThreadId(null);
    setChatMessages([]);
    setChatError(null);
  };

  const clearTransactionRedirectTimer = () => {
    if (transactionRedirectTimerRef.current !== null) {
      window.clearTimeout(transactionRedirectTimerRef.current);
      transactionRedirectTimerRef.current = null;
    }
  };

  const closeTransactionSuccess = () => {
    clearTransactionRedirectTimer();
    if (memorySuggestions.length > 0) {
      setTransactionSuccess(null);
      setShowMemorySuggestions(true);
      return;
    }
    setTransactionSuccess(null);
    resetChatSession();
    navigate('/');
  };

  const continueChatting = () => {
    clearTransactionRedirectTimer();
    setTransactionSuccess(null);
    setShowChatSheet(true);
  };

  const editCompletedTransaction = () => {
    const transaction = visibleTransactions.find((item) => item.id === transactionSuccess?.transactionId);
    if (!transaction) return;
    clearTransactionRedirectTimer();
    setTransactionSuccess(null);
    setEditingTransactionId(transaction.id);
    setEditingTransactionValues({
      accountId: transaction.account_id,
      type: transaction.type,
      amountRupees: String(transaction.amount_paise / 100),
      occurredAt: transaction.occurred_at,
      categoryId: transaction.category_id ?? '',
      toAccountId: transaction.to_account_id ?? '',
      merchant: transaction.merchant ?? '',
      note: transaction.note ?? '',
    });
    setShowAddSheet(true);
  };

  const sendMessageToAssistant = async (messageText: string) => {
    const normalizedMessage = messageText.trim();
    if (!normalizedMessage) {
      return;
    }

    setChatError(null);
    const userMessage: ChatMessage = { id: createLocalId(), role: 'user', content: normalizedMessage };
    const userMessageList = [...chatMessages, userMessage];
    setChatMessages(userMessageList);
    const currentDraftId = persistGeneralDraft(userMessageList, chatThreadId, chatDraftId);

    try {
      const response = await sendChatMessage({
        message: normalizedMessage,
        thread_id: chatThreadId ?? undefined,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }).unwrap();

      setChatThreadId(response.thread_id);
      const insightSummary = (response.insights ?? [])
        .map((insight) => `• ${insight.title}: ${insight.detail}`)
        .join('\n');
      const receiptTransactionLogged = receiptUploadRef.current && response.transaction_logged;
      if (receiptTransactionLogged) receiptUploadRef.current = false;
      const assistantMessage: ChatMessage = {
        id: createLocalId(),
        role: 'assistant',
        content: insightSummary ? `${response.message}\n${insightSummary}` : receiptTransactionLogged
          ? `${response.message}\nWould you like to split this expense? If yes, tell me who shared it.`
          : response.message,
      };
      const fullMessageList = [...userMessageList, assistantMessage];
      setChatMessages(fullMessageList);

      if (response.transaction_logged) {
        if (response.created_transaction_id && currentDraftId && currentUser?.id) {
          deleteChatDraft(currentUser.id, currentDraftId);
        }
        if (currentUser?.id && response.created_transaction_id) {
          const savedDraft = saveChatDraft({
            userId: currentUser.id,
            kind: 'transaction',
            lifecycle: 'conversation',
            transactionId: response.created_transaction_id,
            threadId: response.thread_id,
            messages: fullMessageList,
          });
          setChatDraftId(savedDraft.id);
          setChatTransactionId(response.created_transaction_id);
        } else {
          persistGeneralDraft(fullMessageList, response.thread_id, currentDraftId);
        }
      } else {
        persistGeneralDraft(fullMessageList, response.thread_id, currentDraftId);
      }

      if (response.show_completion_popup && !receiptTransactionLogged) {
        clearTransactionRedirectTimer();
        setTransactionSuccess({ message: assistantMessage.content, expiresAt: Date.now() + 12_000, transactionId: response.created_transaction_id ?? null });
        transactionRedirectTimerRef.current = window.setTimeout(() => {
          transactionRedirectTimerRef.current = null;
          setTransactionSuccess(null);
          resetChatSession();
          navigate('/');
        }, 12_000);
        return;
      }

      if (response.pending_transaction_proposal || response.manual_transaction_input_required) {
        const proposalBatch = response.pending_transaction_proposals ?? [];
        setProposalQueue(proposalBatch);
        setProposalBatchTotal(proposalBatch.length);
        setProposalBatchCompleted(0);
        setProposalForSheet(proposalBatch[0] ?? response.pending_transaction_proposal ?? null);
        setProposalSheetMode(response.manual_transaction_input_required ? 'manual_low_confidence' : 'standard');
        setShowAddSheet(true);
      }
    } catch {
      setChatError(DASHBOARD_CHAT_UI_TEXT.assistantError);
      openManualTransactionFallback('The assistant could not finish this request. You can enter the transaction manually. If the request may have reached the server, check Transactions first to avoid adding it twice.');
    }
  };

  const handleChatSubmit = async () => {
    const normalizedMessage = chatInput.trim();
    if (!normalizedMessage || isSendingChatMessage) {
      return;
    }

    setChatInput('');
    await sendMessageToAssistant(normalizedMessage);
  };

  const handleRecordedVoice = async (audioFile: File) => {
    if (!audioFile) {
      return;
    }

    setChatError(null);

    try {
      const transcription = await transcribeVoice({
        audio: audioFile,
        locale: 'en-IN',
      }).unwrap();

      const transcript = transcription.transcript.trim();
      if (!transcript) {
        setChatError(DASHBOARD_CHAT_UI_TEXT.voiceError);
        openManualTransactionFallback('Voice transcription returned no text. Enter the transaction details manually.');
        return;
      }

      setShowChatSheet(true);
      // Transcription is complete; close the voice modal while the assistant
      // processes the resulting chat message.
      void sendMessageToAssistant(transcript);
    } catch {
      setChatError(DASHBOARD_CHAT_UI_TEXT.voiceError);
      openManualTransactionFallback('Voice processing failed. Enter the transaction details manually.');
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

  const handleImageFileSelected = async (imageFile: File | null) => {
    if (!imageFile) {
      return;
    }

    if (!imageFile.type.startsWith('image/')) {
      setChatError('Please select a valid image file.');
      return;
    }

    try {
      setIsImageProcessing(true);
      setChatError(null);
      const analysis = await analyzeImage({ image: imageFile }).unwrap();
      const imagePrompt = analysis.prompt.trim();

      if (!imagePrompt) {
        setChatError(DASHBOARD_CHAT_UI_TEXT.imageError);
        openManualTransactionFallback('The receipt could not be read. Enter the transaction details manually.');
        return;
      }

      setIsImageProcessing(false);
      setShowChatSheet(true);
      receiptUploadRef.current = true;
      await sendMessageToAssistant(imagePrompt);
    } catch {
      setChatError(DASHBOARD_CHAT_UI_TEXT.imageError);
      openManualTransactionFallback('Receipt processing failed. Enter the transaction details manually.');
    } finally {
      setIsImageProcessing(false);
    }
  };

  const handleCloseChat = () => {
    if (chatMessages.length > 0) {
      setShowSaveDraftPrompt(true);
      return;
    }

    resetChatSession();
  };

  const handleSaveDraftAndClose = () => {
    persistGeneralDraft(chatMessages, chatThreadId, chatDraftId, 'draft');
    setShowSaveDraftPrompt(false);
    resetChatSession();
  };

  const handleAddChatAndClose = () => {
    // Promotion is explicit: transaction-specific chats stay out of the main
    // list unless the user chooses Add to Chats.
    if (currentUser?.id && chatTransactionId) {
      if (chatThreadId) {
        deleteChatDraftByThreadId(currentUser.id, chatThreadId);
      } else if (chatDraftId) {
        deleteChatDraft(currentUser.id, chatDraftId);
      }
      const promotedDraftId = persistGeneralDraft(
        chatMessages,
        chatThreadId,
        null,
        'conversation',
        'general',
        null,
      );
      if (promotedDraftId) {
        queueChatDraftTitleGeneration(currentUser.id, promotedDraftId);
      }
    } else {
      persistGeneralDraft(chatMessages, chatThreadId, chatDraftId, 'conversation', 'general');
    }
    setShowSaveDraftPrompt(false);
    resetChatSession();
  };

  const handleDiscardDraftAndClose = () => {
    if (currentUser?.id && chatDraftId) {
      deleteChatDraft(currentUser.id, chatDraftId);
    } else if (currentUser?.id && chatThreadId) {
      deleteChatDraftByThreadId(currentUser.id, chatThreadId);
    }

    setShowSaveDraftPrompt(false);
    resetChatSession();
  };

  const handleQuickActionClick = (actionKey: DashboardQuickActionKey) => {
    if (actionKey === 'add') {
      setProposalForSheet(null);
      setProposalSheetMode('standard');
      setShowAddSheet(true);
      return;
    }

    if (actionKey === 'chat') {
      setShowChatSheet(true);
      return;
    }

    if (actionKey === 'voice') {
      setChatError(null);
      void startCapture();
      return;
    }

    if (actionKey === 'image') {
      imageFileInputRef.current?.click();
    }
  };

  const renderChatAssistantContent = () => (
    <div className='space-y-3'>
      <div className='max-h-[42vh] space-y-2 overflow-y-auto rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-3'>
        {chatMessages.length === 0 ? (
          <div className='flex min-h-40 flex-col items-center justify-center px-5 text-center'>
            <p className='mb-2 text-base font-semibold text-[var(--text-primary)]'>{openingGreeting}</p>
            <p className='text-sm text-[var(--text-muted)]'>{DASHBOARD_CHAT_UI_TEXT.emptyState}</p>
          </div>
        ) : (
          chatMessages.map((message) => (
            <div
              key={message.id}
              className={`max-w-[92%] rounded-xl px-3 py-2 text-sm ${
                message.role === 'user'
                  ? 'ml-auto bg-[var(--brand-primary)] text-white'
                  : 'bg-[var(--bg-card)] text-[var(--text-primary)]'
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
        <p className='text-sm text-[var(--negative)]' role='alert'>
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
              void handleChatSubmit();
            }
          }}
        />
        <button
          type='button'
          className='inline-flex h-12 min-w-16 items-center justify-center rounded-xl bg-[var(--brand-primary)] px-4 text-sm font-semibold text-white transition-colors hover:bg-[var(--brand-hover)] active:bg-[var(--brand-active)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)] disabled:cursor-not-allowed disabled:opacity-60'
          disabled={chatInput.trim().length === 0 || isSendingChatMessage}
          onClick={() => {
            void handleChatSubmit();
          }}
        >
          {DASHBOARD_CHAT_UI_TEXT.sendButton}
        </button>
      </div>

      <p className='text-xs text-[var(--text-muted)]'>{DASHBOARD_CHAT_UI_TEXT.voiceHint}</p>
      <p className='text-xs text-[var(--text-muted)]'>{DASHBOARD_CHAT_UI_TEXT.transactionDetailHint}</p>
      <Button type='button' variant='secondary' className='min-h-9 w-auto px-3 py-2 text-xs' onClick={() => navigate('/chat')}>
        {DASHBOARD_CHAT_UI_TEXT.openFinanceChat}
      </Button>
    </div>
  );

  return (
    <div className='mx-auto w-full max-w-[1200px] px-4 py-4 md:px-6 md:py-6'>
      <header className='sticky top-[env(safe-area-inset-top)] z-20 -mx-4 mb-4 border-b border-[var(--bg-border)] bg-[color:rgba(9,9,11,0.8)] px-4 py-4 pt-[calc(1rem+env(safe-area-inset-top))] backdrop-blur-xl md:static md:mx-0 md:mb-5 md:border-none md:bg-transparent md:px-0 md:pt-0'>
        <div className='flex items-center justify-between'>
          <div>
            <h1 className='text-lg font-semibold text-[var(--text-secondary)]'>
              {greeting}, {greetingName} 👋
            </h1>
            <p className='mt-0.5 text-xs text-[var(--text-muted)]'>Here is your wallet snapshot for today.</p>
          </div>
          <button
            type='button'
            className='relative flex h-11 w-11 items-center justify-center rounded-full border border-[var(--bg-border)] bg-[var(--bg-card)] text-lg text-[var(--text-secondary)] active:scale-[0.98]'
            aria-label='Notifications'
            onClick={() => {
              setIsNotificationCenterOpen(true);
              setShowMemorySuggestions(true);
            }}
          >
            🔔
            {memorySuggestions.length > 0 ? (
              <span className='absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-[var(--brand-primary)] px-1 text-[10px] font-bold text-white'>
                {memorySuggestions.length}
              </span>
            ) : null}
          </button>
        </div>
      </header>

      {isLoading ? (
        <div className='space-y-4'>
          <div className='h-44 rounded-3xl border border-[var(--bg-border)] bg-[var(--bg-card)] animate-pulse' />
          <div className='space-y-3 rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4'>
            {[1, 2, 3].map((item) => (
              <div key={item} className='flex items-center gap-3'>
                <div className='h-10 w-10 rounded-full bg-[var(--bg-elevated)] animate-pulse' />
                <div className='flex-1 space-y-2'>
                  <div className='h-3 w-2/3 rounded-full bg-[var(--bg-elevated)] animate-pulse' />
                  <div className='h-2 w-1/2 rounded-full bg-[var(--bg-elevated)] animate-pulse' />
                </div>
                <div className='h-3 w-16 rounded-full bg-[var(--bg-elevated)] animate-pulse' />
              </div>
            ))}
          </div>
        </div>
      ) : (
        <>
          <section className='mb-4'>
            <Card variant='hero' className='relative overflow-hidden p-5'>
              <div className='absolute -right-8 -top-8 h-28 w-28 rounded-full bg-[color:rgba(168,85,247,0.18)]' />
              <div className='absolute -bottom-10 right-12 h-24 w-24 rounded-full bg-[color:rgba(96,165,250,0.12)]' />

              <p className='relative text-xs uppercase tracking-wide text-[var(--text-secondary)]'>Total Balance</p>
              <p className='relative mt-2 text-4xl font-bold text-[var(--text-primary)]'>{formatPaiseAsInr(totalBalancePaise)}</p>
              <p className='relative mt-1 text-sm text-[var(--text-secondary)]'>Across {(accounts ?? []).length} accounts</p>

              <div className='relative mt-4 flex flex-wrap gap-2'>
                {(accounts ?? []).slice(0, 4).map((account) => (
                  <span
                    key={account.id}
                    className='rounded-full border border-[color:rgba(168,85,247,0.35)] bg-[color:rgba(168,85,247,0.12)] px-2.5 py-1 text-xs text-[var(--text-primary)]'
                  >
                    {account.name}
                  </span>
                ))}
              </div>
            </Card>
          </section>

          <section className='mb-4 space-y-2'>
            <div className='grid grid-cols-4 gap-2'>
              {DASHBOARD_QUICK_ACTIONS.map((action) => {
                const isDisabled =
                  (action.key === 'voice' && (isVoiceCaptureOpen || isTranscribingVoice)) ||
                  (action.key === 'image' && (isAnalyzingImage || isSendingChatMessage || isTranscribingVoice));
                const Icon = action.icon;

                return (
                  <Button
                    key={action.key}
                    type='button'
                    variant='ghost'
                    className='min-h-12 flex-col gap-1 rounded-2xl px-2 py-2 text-sm'
                    disabled={isDisabled}
                    onClick={() => handleQuickActionClick(action.key)}
                  >
                    <Icon className='h-[18px] w-[18px]' strokeWidth={2.2} aria-hidden='true' />
                    {action.label}
                  </Button>
                );
              })}
            </div>

            {chatError ? <p className='text-xs text-[var(--negative)]'>{chatError}</p> : null}
          </section>

          <div className='space-y-4 lg:grid lg:grid-cols-2 lg:items-stretch lg:gap-4 lg:space-y-0'>
            <section className='h-full'>
              <Card className='h-full p-4'>
                <div className='mb-3 flex items-center justify-between'>
                  <h2 className='text-base font-semibold text-[var(--text-primary)]'>Spending Overview</h2>
                  <span className='text-xs text-[var(--text-muted)]'>This month</span>
                </div>

                <div className='mb-3 rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-3'>
                  <div className='mb-2 flex items-center justify-between text-xs'>
                    <span className='text-[var(--text-secondary)]'>Spent</span>
                    <span className='font-semibold text-[var(--negative)]'>{formatPaiseAsInr(thisMonthSummary.expensesPaise)}</span>
                  </div>
                  <div className='mb-3 h-2 rounded-full bg-[var(--bg-border)]'>
                    <div
                      className='h-2 rounded-full bg-[var(--brand-primary)] transition-all'
                      style={{ width: `${thisMonthSummary.progress}%` }}
                    />
                  </div>
                  <div className='flex items-center justify-between text-xs'>
                    <span className='text-[var(--text-secondary)]'>Income</span>
                    <span className='font-semibold text-[var(--positive)]'>{formatPaiseAsInr(thisMonthSummary.incomePaise)}</span>
                  </div>
                </div>

                <div className='space-y-2'>
                  {thisMonthSummary.topCategories.length > 0 ? (
                    thisMonthSummary.topCategories.map((category) => (
                      <div key={category.categoryId} className='flex items-center justify-between text-sm'>
                        <span className='text-[var(--text-secondary)]'>{category.name}</span>
                        <span className='font-semibold text-[var(--text-primary)]'>{formatPaiseAsInr(category.amountPaise)}</span>
                      </div>
                    ))
                  ) : (
                    <p className='text-sm text-[var(--text-muted)]'>No expense data this month.</p>
                  )}
                </div>
              </Card>
            </section>

            <section className='h-full'>
              <Card className='h-full p-4'>
                <div className='mb-3 flex items-center justify-between'>
                  <h2 className='text-base font-semibold text-[var(--text-primary)]'>Recent Transactions</h2>
                  <Button
                    type='button'
                    variant='secondary'
                    className='min-h-8 w-auto rounded-lg px-2 py-1 text-xs'
                    onClick={() => navigate('/transactions')}
                  >
                    See all →
                  </Button>
                </div>

                {recentTransactions.length === 0 ? (
                  <p className='text-sm text-[var(--text-muted)]'>No transactions yet.</p>
                ) : (
                  <ul className='m-0 flex list-none flex-col gap-2 p-0'>
                    {recentTransactions.map((transaction) => {
                      const categoryName = transaction.category_id ? categoryNameById.get(transaction.category_id) : null;

                      return (
                        <li key={transaction.id} className='rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-3'>
                          <div className='flex items-center justify-between gap-3'>
                            <div className='min-w-0'>
                              <p className='truncate text-sm font-semibold text-[var(--text-primary)]'>
                                {transaction.merchant ?? categoryName ?? 'Transaction'}
                              </p>
                              <p className='mt-0.5 text-xs text-[var(--text-muted)]'>{formatTransactionTime(transaction.occurred_at)}</p>
                            </div>

                            <div className='text-right'>
                              <p className='text-sm font-semibold text-[var(--text-primary)]'>{formatPaiseAsInr(transaction.amount_paise)}</p>
                              <Badge tone={TYPE_BADGE_TONE[transaction.type]}>{transaction.type}</Badge>
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </Card>
            </section>
          </div>

          <section className='mt-4'>
            <Card className='p-4'>
              <div className='mb-3 flex items-center justify-between'>
                <h2 className='text-base font-semibold text-[var(--text-primary)]'>Split Tracker</h2>
                <Button
                  type='button'
                  variant='secondary'
                  className='min-h-8 w-auto rounded-lg px-2 py-1 text-xs'
                  onClick={() => navigate('/splits')}
                >
                  View all
                </Button>
              </div>

              {isLoadingSplits ? (
                <p className='py-8 text-center text-sm text-[var(--text-muted)]'>Loading splits…</p>
              ) : pendingSplits.length === 0 ? (
                <div className='py-8 text-center'>
                  <p className='mb-2 text-3xl'>🤝</p>
                  <p className='text-sm text-[var(--text-muted)]'>No pending splits</p>
                </div>
              ) : (
                <div className='space-y-2'>
                  {pendingSplits.map((contact) => (
                    <div key={contact.id} className='flex items-center gap-3 rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] px-3 py-2'>
                      <div
                        className='flex h-10 w-10 items-center justify-center rounded-full text-sm font-bold'
                        style={{
                          backgroundColor: `${contact.avatar_color}33`,
                          color: contact.avatar_color,
                        }}
                      >
                        {contact.name[0]?.toUpperCase()}
                      </div>
                      <div className='min-w-0 flex-1'>
                        <p className='truncate text-sm font-medium text-[var(--text-primary)]'>{contact.name}</p>
                        <p className='text-xs text-[var(--text-muted)]'>{contact.split_count} splits</p>
                      </div>
                      <span className='text-sm font-semibold text-[var(--positive)]'>{formatPaiseAsInr(contact.total_pending_paise)}</span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </section>
        </>
      )}

      <input
        ref={imageFileInputRef}
        type='file'
        accept='image/*'
        className='hidden'
        onChange={(event) => {
          const imageFile = event.target.files?.[0] ?? null;
          event.currentTarget.value = '';
          void handleImageFileSelected(imageFile);
        }}
      />

      {showSaveDraftPrompt ? (
        <div className='fixed inset-0 z-[70] flex items-center justify-center bg-black/60 px-4 py-6'>
          <div className='w-full max-w-md rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-5 shadow-[0_20px_50px_rgba(0,0,0,0.45)]'>
            <div className='flex items-start justify-between gap-2'>
              <h3 className='text-lg font-semibold text-[var(--text-primary)]'>{DASHBOARD_CHAT_UI_TEXT.closeChatTitle}</h3>
              <button
                type='button'
                aria-label='Close'
                className='inline-flex h-8 w-8 items-center justify-center rounded-full border border-[var(--bg-border)] bg-[var(--bg-elevated)] text-base leading-none text-[var(--text-secondary)] hover:bg-[var(--bg-card)]'
                onClick={() => setShowSaveDraftPrompt(false)}
              >
                ×
              </button>
            </div>
            <p className='mt-2 text-sm text-[var(--text-secondary)]'>
              {isSendingChatMessage
                ? 'Your request is still processing. Closing will not cancel it. Keep this chat in Chats now; you can discard it or move it to Drafts after the reply arrives.'
                : DASHBOARD_CHAT_UI_TEXT.closeChatPrompt}
            </p>

            <div className='mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3'>
              <Button type='button' variant='secondary' disabled={isSendingChatMessage} onClick={handleDiscardDraftAndClose}>
                {DASHBOARD_CHAT_UI_TEXT.discardAndCloseLabel}
              </Button>
              <Button type='button' variant='secondary' onClick={handleAddChatAndClose}>
                {DASHBOARD_CHAT_UI_TEXT.addToChatsLabel}
              </Button>
              <Button type='button' disabled={isSendingChatMessage} onClick={handleSaveDraftAndClose}>
                {DASHBOARD_CHAT_UI_TEXT.addToDraftsLabel}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

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

      {isImageProcessing ? (
        <div
          className='fixed inset-0 z-[70] flex items-center justify-center bg-black/35 px-6 backdrop-blur-[2px]'
          role='status'
          aria-live='polite'
          aria-label='Processing uploaded image'
        >
          <div className='flex w-full max-w-xs flex-col items-center gap-3 rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] px-6 py-7 text-center shadow-2xl'>
            <LoaderCircle className='h-8 w-8 animate-spin text-[var(--brand-primary)]' aria-hidden='true' />
            <p className='text-sm font-semibold text-[var(--text-primary)]'>Processing image…</p>
            <p className='text-xs text-[var(--text-muted)]'>Reading the receipt before opening chat.</p>
          </div>
        </div>
      ) : null}

      <BottomSheet
        isOpen={showChatSheet}
        onClose={handleCloseChat}
        title={DASHBOARD_CHAT_UI_TEXT.assistantTitle}
      >
        {renderChatAssistantContent()}
      </BottomSheet>

      {transactionSuccess ? (
        <TransactionSuccessOverlay
          message={transactionSuccess.message}
          expiresAt={transactionSuccess.expiresAt}
          onClose={closeTransactionSuccess}
          onContinue={continueChatting}
          onEditTransaction={transactionSuccess.transactionId ? editCompletedTransaction : undefined}
        />
      ) : null}
      {(isNotificationCenterOpen || (showMemorySuggestions && memorySuggestions.length > 0)) && !transactionSuccess ? (
        <div className='fixed inset-0 z-[60] flex items-center justify-center overflow-y-auto bg-black/60 p-4' role='dialog' aria-modal='true' aria-label='Notifications'>
          <div className='w-full max-w-lg space-y-3'>
            {memorySuggestions.length > 0 ? (
              <MemorySuggestionsPanel suggestions={memorySuggestions} />
            ) : (
              <Card className='border-[color:rgba(168,85,247,0.35)] p-5'>
                <h3 className='font-semibold text-[var(--text-primary)]'>You’re all caught up</h3>
                <p className='mt-1 text-sm text-[var(--text-muted)]'>No notifications right now.</p>
              </Card>
            )}
            <div className='flex justify-center'>
              <Button type='button' variant='secondary' className='!bg-[var(--bg-elevated)] hover:!bg-[var(--bg-card)]' onClick={() => {
                setIsNotificationCenterOpen(false);
                setShowMemorySuggestions(false);
              }}>Close</Button>
            </div>
          </div>
        </div>
      ) : null}

      <BottomSheet
        isOpen={showAddSheet}
        onClose={() => {
          setShowAddSheet(false);
          setManualFallbackMessage(null);
          setProposalForSheet(null);
          setProposalQueue([]);
          setProposalBatchTotal(0);
          setProposalBatchCompleted(0);
          setProposalSheetMode('standard');
          setEditingTransactionId(null);
          setEditingTransactionValues(undefined);
        }}
        title={
          proposalBatchTotal > 1
            ? `${SHEET_TITLES.addTransaction} (${proposalBatchCompleted + 1} of ${proposalBatchTotal})`
            : SHEET_TITLES.addTransaction
        }
      >
        {manualFallbackMessage ? (
          <div className='mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-[var(--text-primary)]' role='status'>
            {manualFallbackMessage}
          </div>
        ) : null}
        <CreateTransactionForm
          mode='sheet'
          showHeading={false}
          initialValues={editingTransactionValues ?? proposalInitialValues}
          transactionId={editingTransactionId ?? undefined}
          trackReviewEvent={Boolean(editingTransactionId)}
          prefillMode={proposalSheetMode}
          enableSplit={proposalBatchTotal <= 1}
          submitLabel={proposalForSheet ? 'Confirm & Add' : 'Add transaction'}
          onSuccess={(_transaction, splitRequested) => {
            if (proposalQueue.length > 1) {
              const remainingQueue = proposalQueue.slice(1);
              setProposalQueue(remainingQueue);
              setProposalBatchCompleted((completed) => completed + 1);
              setProposalForSheet(remainingQueue[0]);
              return;
            }
            if (proposalBatchTotal > 0) {
              setShowAddSheet(false);
              setProposalForSheet(null);
              setProposalQueue([]);
              setProposalBatchTotal(0);
              setProposalBatchCompleted(0);
              setProposalSheetMode('standard');
              return;
            }
            setShowAddSheet(false);
            setManualFallbackMessage(null);
            setEditingTransactionId(null);
            setEditingTransactionValues(undefined);
            setProposalForSheet(null);
            setProposalQueue([]);
            setProposalBatchTotal(0);
            setProposalBatchCompleted(0);
            setProposalSheetMode('standard');
            setShowChatSheet(false);
            if (!splitRequested) navigate('/transactions');
          }}
        />
      </BottomSheet>
    </div>
  );
}
