import { useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Badge } from '../../components/atoms/Badge';
import { Button } from '../../components/atoms/Button';
import { Card } from '../../components/atoms/Card';
import { Input } from '../../components/atoms/Input';
import { BottomSheet } from '../../components/molecules/BottomSheet';
import { CreateTransactionForm } from '../../components/organisms/CreateTransactionForm';
import { useListAccountsQuery } from '../accounts/accountsApi';
import { useListCategoriesQuery } from '../categories/categoriesApi';
import { useSendChatMessageMutation, useTranscribeVoiceMutation } from '../chat/chatApi';
import { useListTransactionsQuery } from '../transactions/transactionsApi';
import type { TransactionType } from '../transactions/transactionsApi';
import {
  DASHBOARD_CHAT_UI_TEXT,
  DASHBOARD_QUICK_ACTIONS,
  type DashboardQuickActionKey,
  SHEET_TITLES,
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
  const navigate = useNavigate();
  const { data: accounts, isLoading: isLoadingAccounts } = useListAccountsQuery();
  const { data: transactions, isLoading: isLoadingTransactions } = useListTransactionsQuery();
  const { data: categories } = useListCategoriesQuery();
  const [sendChatMessage, { isLoading: isSendingChatMessage }] = useSendChatMessageMutation();
  const [transcribeVoice, { isLoading: isTranscribingVoice }] = useTranscribeVoiceMutation();
  const [showAddSheet, setShowAddSheet] = useState(false);
  const [showChatSheet, setShowChatSheet] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [chatThreadId, setChatThreadId] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatError, setChatError] = useState<string | null>(null);
  const voiceFileInputRef = useRef<HTMLInputElement | null>(null);

  const pendingSplits: PendingSplit[] = [];

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

  const sendMessageToAssistant = async (messageText: string) => {
    const normalizedMessage = messageText.trim();
    if (!normalizedMessage) {
      return;
    }

    setChatError(null);
    setChatMessages((previousMessages) => [
      ...previousMessages,
      { id: createLocalId(), role: 'user', content: normalizedMessage },
    ]);

    try {
      const response = await sendChatMessage({
        message: normalizedMessage,
        thread_id: chatThreadId ?? undefined,
      }).unwrap();

      setChatThreadId(response.thread_id);
      setChatMessages((previousMessages) => [
        ...previousMessages,
        { id: createLocalId(), role: 'assistant', content: response.message },
      ]);
    } catch {
      setChatError(DASHBOARD_CHAT_UI_TEXT.assistantError);
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

  const handleVoiceFileSelected = async (audioFile: File | null) => {
    if (!audioFile) {
      return;
    }

    setChatError(null);

    try {
      const transcription = await transcribeVoice({
        audio: audioFile,
        locale: 'en-IN',
      }).unwrap();

      setShowChatSheet(true);
      await sendMessageToAssistant(transcription.transcript);
    } catch {
      setChatError(DASHBOARD_CHAT_UI_TEXT.voiceError);
    }
  };

  const handleQuickActionClick = (actionKey: DashboardQuickActionKey) => {
    if (actionKey === 'add') {
      setShowAddSheet(true);
      return;
    }

    if (actionKey === 'chat') {
      setShowChatSheet(true);
      return;
    }

    if (actionKey === 'voice') {
      voiceFileInputRef.current?.click();
    }
  };

  return (
    <div className='mx-auto w-full max-w-[1200px] px-4 py-4 md:px-6 md:py-6'>
      <header className='sticky top-[env(safe-area-inset-top)] z-20 -mx-4 mb-4 border-b border-[var(--bg-border)] bg-[color:rgba(9,9,11,0.8)] px-4 py-4 pt-[calc(1rem+env(safe-area-inset-top))] backdrop-blur-xl md:static md:mx-0 md:mb-5 md:border-none md:bg-transparent md:px-0 md:pt-0'>
        <div className='flex items-center justify-between'>
          <div>
            <h1 className='text-lg font-semibold text-[var(--text-secondary)]'>Good morning, Sarthak 👋</h1>
            <p className='mt-0.5 text-xs text-[var(--text-muted)]'>Here is your wallet snapshot for today.</p>
          </div>
          <button
            type='button'
            className='flex h-11 w-11 items-center justify-center rounded-full border border-[var(--bg-border)] bg-[var(--bg-card)] text-lg text-[var(--text-secondary)] active:scale-[0.98]'
            aria-label='Notifications'
          >
            🔔
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
                const isDisabled = action.key === 'image' || (action.key === 'voice' && isTranscribingVoice);

                return (
                  <Button
                    key={action.key}
                    type='button'
                    variant='ghost'
                    className='min-h-12 flex-col gap-1 rounded-2xl px-2 py-2 text-sm'
                    disabled={isDisabled}
                    onClick={() => handleQuickActionClick(action.key)}
                  >
                    <span className='text-base' aria-hidden='true'>
                      {action.icon}
                    </span>
                    {action.label}
                    {action.key === 'image' ? <span className='text-[10px] text-[var(--text-muted)]'>{DASHBOARD_CHAT_UI_TEXT.imageComingSoon}</span> : null}
                  </Button>
                );
              })}
            </div>

            {chatError ? <p className='text-xs text-[var(--negative)]'>{chatError}</p> : null}
          </section>

          <div className='space-y-4 lg:grid lg:grid-cols-2 lg:gap-4 lg:space-y-0'>
            <section>
              <Card className='p-4'>
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

            <section>
              <Card className='p-4'>
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

              {pendingSplits.length === 0 ? (
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
        ref={voiceFileInputRef}
        type='file'
        accept='audio/*,.wav,.ogg'
        className='hidden'
        onChange={(event) => {
          const audioFile = event.target.files?.[0] ?? null;
          event.currentTarget.value = '';
          void handleVoiceFileSelected(audioFile);
        }}
      />

      <BottomSheet
        isOpen={showChatSheet}
        onClose={() => setShowChatSheet(false)}
        title={DASHBOARD_CHAT_UI_TEXT.assistantTitle}
      >
        <div className='space-y-3'>
          <div className='max-h-[42vh] space-y-2 overflow-y-auto rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-3'>
            {chatMessages.length === 0 ? (
              <p className='text-sm text-[var(--text-muted)]'>{DASHBOARD_CHAT_UI_TEXT.emptyState}</p>
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
                  {message.content}
                </div>
              ))
            )}
          </div>

          <div className='flex items-center gap-2'>
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
            <Button
              type='button'
              variant='primary'
              className='min-h-12 w-auto px-4'
              disabled={chatInput.trim().length === 0 || isSendingChatMessage}
              onClick={() => {
                void handleChatSubmit();
              }}
            >
              {DASHBOARD_CHAT_UI_TEXT.sendButton}
            </Button>
          </div>

          <p className='text-xs text-[var(--text-muted)]'>{DASHBOARD_CHAT_UI_TEXT.voiceHint}</p>
        </div>
      </BottomSheet>

      <BottomSheet isOpen={showAddSheet} onClose={() => setShowAddSheet(false)} title={SHEET_TITLES.addTransaction}>
        <CreateTransactionForm mode='sheet' showHeading={false} onSuccess={() => setShowAddSheet(false)} />
      </BottomSheet>
    </div>
  );
}
