import { apiClient } from '../../lib/apiClient';

export type AccountType = 'cash' | 'bank' | 'card' | 'wallet';

export interface Account {
  id: string;
  name: string;
  type: AccountType;
  balance_paise: number;
  currency: string;
  is_active: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateAccountRequest {
  name: string;
  type: AccountType;
  balance_paise: number;
  currency?: string;
}

const accountsApi = apiClient.injectEndpoints({
  endpoints: (builder) => ({
    listAccounts: builder.query<Account[], void>({
      query: () => '/accounts',
      providesTags: ['Account'],
    }),
    createAccount: builder.mutation<Account, CreateAccountRequest>({
      query: (body) => ({ url: '/accounts', method: 'POST', body }),
      invalidatesTags: ['Account'],
    }),
    setDefaultAccount: builder.mutation<Account, string>({
      query: (accountId) => ({ url: `/accounts/${accountId}/default`, method: 'PATCH' }),
      invalidatesTags: ['Account'],
    }),
  }),
});

export const { useListAccountsQuery, useCreateAccountMutation, useSetDefaultAccountMutation } = accountsApi;
