import { apiClient } from '../../lib/apiClient';

export interface SplitParticipant {
  id: string;
  name: string;
  share_paise: number;
  settled_paise: number;
  repayment_transaction_id: string | null;
}

export interface Split {
  id: string;
  transaction_id: string | null;
  kind: 'expense_split' | 'money_owed';
  title: string;
  owner_share_paise: number;
  total_paise: number;
  outstanding_paise: number;
  created_at: string;
  participants: SplitParticipant[];
  item_breakdown?: { name: string; amount_paise: number; food_type: string;
    allocations: { person: string; amount_paise: number }[] }[] | null;
  settlement_breakdown?: {
    priced_items_paise: number;
    remainder_paise: number;
    contributions: { person: string; amount_paise: number }[];
    debts: { debtor: string; creditor: string; amount_paise: number }[];
    transfers: { debtor: string; creditor: string; amount_paise: number; repayment_transaction_id?: string | null }[];
    quantity_allocations: {
      item_name: string; people: string[]; quantity_per_person: number;
      unit_price_paise: number; total_paise: number;
    }[];
  } | null;
}

export interface SplitContactPreference {
  id: string;
  name: string;
  dietary_preference: 'vegetarian' | 'vegan' | 'omnivore' | null;
  preference_confirmed_at: string | null;
}

export interface SplitPreferenceSuggestion {
  name: string;
  suggested_preference: 'vegetarian';
  evidence_splits: number;
}

export interface CreateSplitRequest {
  transaction_id: string;
  title: string;
  amount_paise: number;
  mode: 'equal' | 'custom';
  owner_share_paise?: number;
  participants: { name: string; share_paise: number }[];
}

export interface CreateOwedRequest {
  title?: string;
  name: string;
  amount_paise: number;
}

export interface UpdateSplitRequest {
  title: string;
  owner_share_paise: number;
  participants: { id?: string; name: string; share_paise: number }[];
}

const splitsApi = apiClient.injectEndpoints({
  endpoints: (builder) => ({
    listSplits: builder.query<Split[], void>({ query: () => '/splits', providesTags: ['Split'] }),
    listSplitContacts: builder.query<string[], void>({ query: () => '/splits/contacts', providesTags: ['Split'] }),
    listSplitContactPreferences: builder.query<SplitContactPreference[], void>({
      query: () => '/splits/contacts/preferences', providesTags: ['Split'],
    }),
    listSplitPreferenceSuggestions: builder.query<SplitPreferenceSuggestion[], void>({
      query: () => '/splits/contacts/preference-suggestions', providesTags: ['Split'],
    }),
    setSplitContactPreference: builder.mutation<SplitContactPreference,
      { name: string; dietary_preference: SplitContactPreference['dietary_preference'] }>({
      query: (body) => ({ url: '/splits/contacts/preferences', method: 'PUT', body }),
      invalidatesTags: ['Split'],
    }),
    deleteSplitContactPreference: builder.mutation<void, string>({
      query: (contactId) => ({ url: `/splits/contacts/preferences/${contactId}`, method: 'DELETE' }),
      invalidatesTags: ['Split'],
    }),
    createSplit: builder.mutation<Split, CreateSplitRequest>({
      query: (body) => ({ url: '/splits', method: 'POST', body }), invalidatesTags: ['Split'],
    }),
    createOwed: builder.mutation<Split, CreateOwedRequest>({
      query: (body) => ({ url: '/splits/owed', method: 'POST', body }), invalidatesTags: ['Split'],
    }),
    updateSplit: builder.mutation<Split, { splitId: string; body: UpdateSplitRequest }>({
      query: ({ splitId, body }) => ({ url: `/splits/${splitId}`, method: 'PATCH', body }),
      invalidatesTags: ['Split'],
    }),
    settleSplitParticipant: builder.mutation<Split, { splitId: string; participantId: string; repaymentTransactionId: string }>({
      query: ({ splitId, participantId, repaymentTransactionId }) => ({
        url: `/splits/${splitId}/participants/${participantId}/settle`, method: 'POST',
        body: { repayment_transaction_id: repaymentTransactionId },
      }),
      invalidatesTags: ['Split'],
    }),
    repaySplitParticipant: builder.mutation<Split, { splitId: string; participantId: string; accountId: string }>({
      query: ({ splitId, participantId, accountId }) => ({
        url: `/splits/${splitId}/participants/${participantId}/repay`, method: 'POST',
        body: { account_id: accountId },
      }),
      invalidatesTags: ['Split', 'Transaction', 'Account', 'Category'],
    }),
    repaySettlementTransfer: builder.mutation<Split, { splitId: string; debtor: string; accountId: string }>({
      query: ({ splitId, debtor, accountId }) => ({
        url: `/splits/${splitId}/settlement-transfers/repay`, method: 'POST',
        body: { debtor, account_id: accountId },
      }),
      invalidatesTags: ['Split', 'Transaction', 'Account', 'Category'],
    }),
    deleteSplit: builder.mutation<void, string>({
      query: (splitId) => ({ url: `/splits/${splitId}`, method: 'DELETE' }),
      invalidatesTags: ['Split'],
    }),
  }),
});

export const {
  useListSplitsQuery, useListSplitContactsQuery, useCreateSplitMutation, useCreateOwedMutation,
  useSettleSplitParticipantMutation,
  useDeleteSplitMutation, useUpdateSplitMutation, useRepaySplitParticipantMutation,
  useRepaySettlementTransferMutation,
  useListSplitContactPreferencesQuery, useSetSplitContactPreferenceMutation,
  useListSplitPreferenceSuggestionsQuery,
  useDeleteSplitContactPreferenceMutation,
} = splitsApi;
