import { apiClient } from '../../lib/apiClient';

export type AccountType = 'cash' | 'bank' | 'card' | 'wallet';

export interface Account {
  id: string;
  name: string;
  type: AccountType;
  balance_paise: number;
  currency: string;
  is_active: boolean;
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
  }),
});

export const { useListAccountsQuery, useCreateAccountMutation } = accountsApi;
