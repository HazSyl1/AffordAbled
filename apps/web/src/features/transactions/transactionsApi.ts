import { apiClient } from '../../lib/apiClient';

export type TransactionType = 'expense' | 'income' | 'transfer' | 'refund';

export interface Transaction {
  id: string;
  account_id: string;
  to_account_id: string | null;
  category_id: string | null;
  type: TransactionType;
  amount_paise: number;
  merchant: string | null;
  note: string | null;
  occurred_at: string;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateTransactionRequest {
  account_id: string;
  to_account_id?: string;
  category_id?: string;
  type: TransactionType;
  amount_paise: number;
  merchant?: string;
  note?: string;
  occurred_at: string;
}

export interface UpdateTransactionRequest {
  account_id?: string;
  to_account_id?: string;
  category_id?: string;
  type?: TransactionType;
  amount_paise?: number;
  merchant?: string;
  note?: string;
  occurred_at?: string;
}

const transactionsApi = apiClient.injectEndpoints({
  endpoints: (builder) => ({
    listTransactions: builder.query<Transaction[], void>({
      query: () => '/transactions',
      providesTags: ['Transaction'],
    }),
    createTransaction: builder.mutation<Transaction, CreateTransactionRequest>({
      query: (body) => ({ url: '/transactions', method: 'POST', body }),
      invalidatesTags: ['Transaction', 'Account'],
    }),
    updateTransaction: builder.mutation<
      Transaction,
      { transactionId: string; body: UpdateTransactionRequest }
    >({
      query: ({ transactionId, body }) => ({
        url: `/transactions/${transactionId}`,
        method: 'PATCH',
        body,
      }),
      invalidatesTags: ['Transaction', 'Account'],
    }),
    deleteTransaction: builder.mutation<void, string>({
      query: (transactionId) => ({ url: `/transactions/${transactionId}`, method: 'DELETE' }),
      invalidatesTags: ['Transaction', 'Account'],
    }),
    restoreTransaction: builder.mutation<void, string>({
      query: (transactionId) => ({ url: `/transactions/${transactionId}/restore`, method: 'POST' }),
      invalidatesTags: ['Transaction', 'Account'],
    }),
  }),
});

export const {
  useListTransactionsQuery,
  useCreateTransactionMutation,
  useUpdateTransactionMutation,
  useDeleteTransactionMutation,
  useRestoreTransactionMutation,
} = transactionsApi;
