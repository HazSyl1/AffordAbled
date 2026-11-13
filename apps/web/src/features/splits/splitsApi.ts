import { apiClient } from '../../lib/apiClient';

export interface SplitParticipant {
  id: string;
  name: string;
  share_paise: number;
  settled_paise: number;
  repayment_transaction_id: string | null;
  contact_id: string | null;
  payments: { id: string; amount_paise: number; transaction_id: string | null; created_at: string }[];
}

export interface Split {
  id: string;
  transaction_id: string | null;
  kind: 'expense_split' | 'money_owed';
  direction: 'to_you' | 'by_you';
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
    transfers: {
      debtor: string; creditor: string; amount_paise: number; settled_paise?: number;
      repayment_transaction_id?: string | null;
    }[];
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

export interface PersonSplitBalance {
  person: string;
  owed_to_you_paise: number;
  you_owe_paise: number;
  net_paise: number;
  entries: {
    split_id: string;
    participant_id: string;
    title: string;
    direction: 'to_you' | 'by_you';
    remaining_paise: number;
    created_at: string;
  }[];
}

export interface CreateSplitRequest {
  transaction_id: string;
  title: string;
  amount_paise: number;
  mode: 'equal' | 'custom';
  owner_share_paise?: number;
  participants: { name: string; share_paise: number; contact_id?: string }[];
}

export interface CreateOwedRequest {
  title?: string;
  name: string;
  amount_paise: number;
  direction: 'to_you' | 'by_you';
  contact_id?: string;
}

export interface UpdateSplitRequest {
  title: string;
  owner_share_paise: number;
  participants: { id?: string; name: string; share_paise: number; contact_id?: string }[];
  transaction_amount_paise?: number;
}

export interface SplitContactDetails {
  id: string;
  name: string;
  phone_e164: string | null;
  email: string | null;
  dietary_preference: 'vegetarian' | 'vegan' | 'omnivore' | null;
}

export interface SplitNotificationHistory {
  id: string;
  status: 'queued' | 'processing' | 'sent' | 'failed' | 'rate_limited' | 'cancelled' | 'uncertain';
  channel: string;
  blocked_reason: string | null;
  provider_error_message: string | null;
  created_at: string;
  completed_at: string | null;
  recipient_name?: string | null;
}

export interface SplitNotificationRecipient {
  participant_id: string;
  contact_id: string | null;
  name: string;
  amount_paise: number;
  recipient: string | null;
}

export interface SplitNotificationStatus {
  server_now: string;
  can_notify: boolean;
  blocked_reason: string | null;
  notification_count: number;
  max_notifications: number;
  limits_bypassed: boolean;
  last_sent_at: string | null;
  next_available_at: string | null;
  cooldown_remaining_seconds: number;
  request_in_progress: boolean;
  channel: 'sms' | 'email';
  recipients: SplitNotificationRecipient[];
  missing_recipients: SplitNotificationRecipient[];
  history: SplitNotificationHistory[];
}

const splitsApi = apiClient.injectEndpoints({
  endpoints: (builder) => ({
    listSplits: builder.query<Split[], void>({ query: () => '/splits', providesTags: ['Split'] }),
    listPersonSplitBalances: builder.query<PersonSplitBalance[], void>({
      query: () => '/splits/balances', providesTags: ['Split'],
    }),
    settlePersonSplitBalance: builder.mutation<{
      person: string; offset_paise: number; cash_direction: 'to_you' | 'by_you' | null;
      cash_paise: number; net_before_paise: number; net_after_paise: number;
      split_ids: string[]; transactions: { id: string; split_id: string; amount_paise: number }[];
    }, {
      person_name: string; account_id?: string; amount_paise?: number;
      expected_owed_to_you_paise: number; expected_you_owe_paise: number;
    }>({
      query: (body) => ({ url: '/splits/balances/settle', method: 'POST', body }),
      invalidatesTags: ['Split', 'Transaction', 'Account', 'Category'],
    }),
    getBalanceEmailStatus: builder.query<{
      can_notify: boolean; blocked_reason: string | null; next_available_at: string | null;
      notification_count: number; max_notifications: number; request_in_progress: boolean; server_now: string;
      limits_bypassed: boolean;
    }, string>({
      query: (contactId) => `/splits/balances/${contactId}/email-status`,
      providesTags: (_result, _error, contactId) => [{ type: 'SplitNotification', id: contactId }],
    }),
    queueBalanceStatement: builder.mutation<{ notification_id: string; status: string; created_at: string }, {
      contactId: string; idempotencyKey: string;
    }>({
      query: ({ contactId, idempotencyKey }) => ({
        url: `/splits/balances/${contactId}/email`, method: 'POST', headers: { 'Idempotency-Key': idempotencyKey },
      }),
      invalidatesTags: (_result, _error, { contactId }) => [{ type: 'SplitNotification', id: contactId }],
    }),
    listSplitContacts: builder.query<string[], void>({ query: () => '/splits/contacts', providesTags: ['Split'] }),
    listSplitContactDetails: builder.query<SplitContactDetails[], void>({
      query: () => '/splits/contacts/details', providesTags: ['Split'],
    }),
    setSplitContactDetails: builder.mutation<SplitContactDetails, {
      contact_id?: string; name: string; phone_e164: string | null; email: string | null;
    }>({
      query: (body) => ({ url: '/splits/contacts/details', method: 'PUT', body }),
      invalidatesTags: ['Split', 'SplitNotification'],
    }),
    deleteSplitContactDetails: builder.mutation<void, { contactId?: string; name: string }>({
      query: ({ contactId, name }) => ({
        url: contactId
          ? `/splits/contacts/details/${contactId}`
          : `/splits/contacts/details?name=${encodeURIComponent(name)}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['Split', 'SplitNotification'],
    }),
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
    payMoneyOwed: builder.mutation<Split, { splitId: string; participantId: string; accountId: string }>({
      query: ({ splitId, participantId, accountId }) => ({
        url: `/splits/${splitId}/participants/${participantId}/pay`, method: 'POST',
        body: { account_id: accountId },
      }),
      invalidatesTags: ['Split', 'Transaction', 'Account', 'Category'],
    }),
    updateSplit: builder.mutation<Split, { splitId: string; body: UpdateSplitRequest }>({
      query: ({ splitId, body }) => ({ url: `/splits/${splitId}`, method: 'PATCH', body }),
      invalidatesTags: ['Split'],
    }),
    renameSplit: builder.mutation<Split, { splitId: string; title: string }>({
      query: ({ splitId, title }) => ({ url: `/splits/${splitId}/title`, method: 'PATCH', body: { title } }),
      invalidatesTags: ['Split', 'SplitNotification'],
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
    recordSplitPayment: builder.mutation<Split, {
      splitId: string; participantId: string; accountId: string; amountPaise?: number;
    }>({
      query: ({ splitId, participantId, accountId, amountPaise }) => ({
        url: `/splits/${splitId}/participants/${participantId}/payments`, method: 'POST',
        body: { account_id: accountId, ...(amountPaise === undefined ? {} : { amount_paise: amountPaise }) },
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
    listSplitNotificationStatuses: builder.query<Record<string, SplitNotificationStatus>, void>({
      query: () => '/splits/notification-statuses', providesTags: ['SplitNotification'],
    }),
    getSplitNotificationStatus: builder.query<SplitNotificationStatus, { splitId: string }>({
      query: ({ splitId }) => `/splits/${splitId}/notifications`,
      providesTags: ['SplitNotification'],
    }),
    queueSplitNotification: builder.mutation<{
      campaign_id: string; notification_ids: string[]; status: string; created_at: string;
      skipped_recipients: { participant_id: string; contact_id: string | null; name: string; amount_paise: number; reason: string }[];
    }, { splitId: string; idempotencyKey: string; participantIds?: string[] }>({
      query: ({ splitId, idempotencyKey, participantIds }) => ({
        url: `/splits/${splitId}/notifications`, method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
        ...(participantIds ? { body: { participant_ids: participantIds } } : {}),
      }),
      invalidatesTags: ['SplitNotification'],
    }),
  }),
});

export const {
  useListSplitsQuery, useListPersonSplitBalancesQuery, useSettlePersonSplitBalanceMutation,
  useQueueBalanceStatementMutation,
  useGetBalanceEmailStatusQuery,
  useListSplitContactsQuery, useCreateSplitMutation, useCreateOwedMutation,
  useSettleSplitParticipantMutation,
  useDeleteSplitMutation, useUpdateSplitMutation, useRepaySplitParticipantMutation,
  useRepaySettlementTransferMutation,
  useRecordSplitPaymentMutation,
  usePayMoneyOwedMutation,
  useListSplitContactPreferencesQuery, useSetSplitContactPreferenceMutation,
  useListSplitPreferenceSuggestionsQuery,
  useDeleteSplitContactPreferenceMutation,
  useListSplitContactDetailsQuery, useSetSplitContactDetailsMutation, useDeleteSplitContactDetailsMutation,
  useListSplitNotificationStatusesQuery, useLazyGetSplitNotificationStatusQuery,
  useQueueSplitNotificationMutation,
  useRenameSplitMutation,
  useLazyListSplitsQuery,
} = splitsApi;
