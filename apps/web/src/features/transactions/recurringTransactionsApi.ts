import { apiClient } from '../../lib/apiClient';
import type { Transaction, TransactionType } from './transactionsApi';

export type RecurrenceUnit = 'daily' | 'weekly' | 'monthly' | 'yearly';
export type RecurringStatus = 'active' | 'paused' | 'needs_attention' | 'completed' | 'cancelled';

export interface RecurringTransaction {
  id: string;
  account_id: string | null;
  category_id: string | null;
  type: 'expense' | 'income';
  amount_paise: number;
  merchant: string | null;
  note: string | null;
  recurrence_unit: RecurrenceUnit;
  interval_count: number;
  anchor_at: string;
  timezone: string;
  end_at: string | null;
  max_occurrences: number | null;
  next_occurrence_at: string | null;
  generated_count: number;
  status: RecurringStatus;
  source: 'manual' | 'chat' | 'memory';
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateRecurringTransactionRequest {
  account_id: string;
  category_id: string;
  type: Extract<TransactionType, 'expense' | 'income'>;
  amount_paise: number;
  merchant?: string;
  note?: string;
  recurrence_unit: RecurrenceUnit;
  interval_count: number;
  anchor_at: string;
  timezone: string;
  end_at?: string;
  max_occurrences?: number;
  create_initial_transaction: boolean;
  source_memory_id?: string;
}

interface CreateRecurringTransactionResponse {
  rule: RecurringTransaction;
  initial_transaction: Transaction | null;
}

const recurringTransactionsApi = apiClient.injectEndpoints({
  endpoints: (builder) => ({
    listRecurringTransactions: builder.query<RecurringTransaction[], void>({
      query: () => '/recurring-transactions',
      providesTags: ['RecurringTransaction'],
    }),
    createRecurringTransaction: builder.mutation<CreateRecurringTransactionResponse, CreateRecurringTransactionRequest>({
      query: (body) => ({ url: '/recurring-transactions', method: 'POST', body }),
      invalidatesTags: ['RecurringTransaction', 'Transaction', 'Account', 'Memory'],
    }),
    pauseRecurringTransaction: builder.mutation<RecurringTransaction, string>({
      query: (id) => ({ url: `/recurring-transactions/${id}/pause`, method: 'POST' }),
      invalidatesTags: ['RecurringTransaction'],
    }),
    updateRecurringTransaction: builder.mutation<
      RecurringTransaction,
      { id: string; body: Partial<CreateRecurringTransactionRequest> }
    >({
      query: ({ id, body }) => ({ url: `/recurring-transactions/${id}`, method: 'PATCH', body }),
      invalidatesTags: ['RecurringTransaction'],
    }),
    resumeRecurringTransaction: builder.mutation<RecurringTransaction, string>({
      query: (id) => ({ url: `/recurring-transactions/${id}/resume`, method: 'POST' }),
      invalidatesTags: ['RecurringTransaction'],
    }),
    cancelRecurringTransaction: builder.mutation<RecurringTransaction, string>({
      query: (id) => ({ url: `/recurring-transactions/${id}`, method: 'DELETE' }),
      invalidatesTags: ['RecurringTransaction'],
    }),
  }),
});

export const {
  useListRecurringTransactionsQuery,
  useCreateRecurringTransactionMutation,
  usePauseRecurringTransactionMutation,
  useUpdateRecurringTransactionMutation,
  useResumeRecurringTransactionMutation,
  useCancelRecurringTransactionMutation,
} = recurringTransactionsApi;
