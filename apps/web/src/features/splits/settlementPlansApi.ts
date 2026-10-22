import { apiClient } from '../../lib/apiClient';

export interface SettlementCharge {
  id: string;
  label: string;
  amount_paise: number;
  shared_by: string[];
  paid_by?: string | null;
  source_quote?: string | null;
}

export interface SettlementBill {
  id: string;
  merchant: string;
  charges: SettlementCharge[];
  discounts: { label: string; charge_ids: string[]; amount_paise?: number; rate_bps?: number;
    include_extras?: boolean; source_quote?: string | null }[];
  extras: { id?: string; label: string; kind: 'fee' | 'tip'; shared_by: string[]; paid_by?: string | null;
    amount_paise?: number;
    rate_bps?: number; base_charge_ids?: string[]; base_paise?: number; source_quote?: string | null }[];
  payments: { person: string; amount_paise?: number | null; transaction_id?: string; account_id?: string;
    category_id?: string; occurred_at?: string; covered_charge_ids?: string[]; covered_extra_ids?: string[] }[];
  stated_total_paise?: number;
}

export interface SettlementInput {
  title: string;
  participants: string[];
  bills: SettlementBill[];
  debts: { debtor: string; creditor: string; amount_paise: number }[];
}

export interface SettlementPreview {
  bills: { id: string; merchant: string; total_paise: number; shares_paise: Record<string, number>;
    paid_paise: Record<string, number>; payment_amounts_paise?: number[]; rows: { label: string; kind: string;
      amount_paise: number; allocations: Record<string, number> }[] }[];
  shares_paise: Record<string, number>;
  paid_paise: Record<string, number>;
  balances_paise: Record<string, number>;
  transfers: { debtor: string; creditor: string; amount_paise: number }[];
  settled_transfers?: { id: string; debtor: string; creditor: string; amount_paise: number }[];
  total_paise: number;
}

export interface SettlementDraft {
  id: string;
  version: number;
  status: 'draft' | 'confirmed';
  data: SettlementInput;
  preview: SettlementPreview;
  plan_id: string | null;
  revision_plan_id: string | null;
}

export interface SettlementPlan {
  id: string;
  title: string;
  total_paise: number;
  data: SettlementInput;
  preview: SettlementPreview;
  transaction_ids: string[];
  transfers: { id: string; debtor: string; creditor: string; amount_paise: number;
    settled_at: string | null; repayment_transaction_id: string | null }[];
}

const settlementPlansApi = apiClient.injectEndpoints({
  endpoints: (builder) => ({
    listSettlementPlans: builder.query<SettlementPlan[], void>({
      query: () => '/settlement-plans', providesTags: ['Split'],
    }),
    getSettlementDraft: builder.query<SettlementDraft, string>({
      query: (id) => `/settlement-plans/drafts/${id}`, providesTags: ['Split'],
    }),
    createSettlementDraft: builder.mutation<SettlementDraft,
      { request_key: string; data: SettlementInput; revision_plan_id?: string }>({
      query: (body) => ({ url: '/settlement-plans/drafts', method: 'POST', body }),
      invalidatesTags: ['Split'],
    }),
    updateSettlementDraft: builder.mutation<SettlementDraft,
      { id: string; version: number; data: SettlementInput }>({
      query: ({ id, version, data }) => ({
        url: `/settlement-plans/drafts/${id}`, method: 'PUT', body: { version, data },
      }),
      invalidatesTags: ['Split'],
    }),
    confirmSettlementDraft: builder.mutation<SettlementPlan, { id: string; version: number }>({
      query: ({ id, version }) => ({
        url: `/settlement-plans/drafts/${id}/confirm`, method: 'POST', body: { version },
      }),
      invalidatesTags: ['Split', 'Transaction', 'Account', 'Category'],
    }),
    settleSettlementPlanTransfer: builder.mutation<SettlementPlan,
      { planId: string; transferId: string; accountId?: string }>({
      query: ({ planId, transferId, accountId }) => ({
        url: `/settlement-plans/${planId}/transfers/${transferId}/settle`,
        method: 'POST', body: { account_id: accountId ?? null },
      }),
      invalidatesTags: ['Split', 'Transaction', 'Account', 'Category'],
    }),
  }),
});

export const {
  useListSettlementPlansQuery, useGetSettlementDraftQuery, useCreateSettlementDraftMutation,
  useUpdateSettlementDraftMutation, useConfirmSettlementDraftMutation,
  useSettleSettlementPlanTransferMutation,
} = settlementPlansApi;
