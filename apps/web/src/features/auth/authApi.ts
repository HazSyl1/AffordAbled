import { apiClient } from '../../lib/apiClient';
import type { AuthUser } from './authSlice';

export interface AccessTokenResponse {
  access_token: string;
  token_type: string;
}

export interface RegisterRequest {
  name: string;
  date_of_birth: string;
  email: string;
  password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface UpdateProfileRequest {
  name: string;
  date_of_birth: string | null;
  upi_id: string | null;
}

export interface ProfileTransactionSummary {
  message: string;
  transaction_count: number;
}

export interface UsageMetric {
  used: number;
  limit: number | null;
  remaining: number | null;
  unlimited: boolean;
}

export interface UserUsage {
  account_tier: 'free' | 'subscribed' | 'test';
  reset_at: string;
  chat_turns: UsageMetric;
  ai_transactions: UsageMetric;
  notification_limits_bypassed: boolean;
}

const authApi = apiClient.injectEndpoints({
  endpoints: (builder) => ({
    register: builder.mutation<AccessTokenResponse, RegisterRequest>({
      query: (body) => ({ url: '/auth/register', method: 'POST', body }),
    }),
    login: builder.mutation<AccessTokenResponse, LoginRequest>({
      query: (body) => ({ url: '/auth/login', method: 'POST', body }),
    }),
    logout: builder.mutation<void, void>({
      query: () => ({ url: '/auth/logout', method: 'POST' }),
    }),
    refreshSession: builder.mutation<AccessTokenResponse, void>({
      query: () => ({ url: '/auth/refresh', method: 'POST' }),
    }),
    getMe: builder.query<AuthUser, void>({
      query: () => '/auth/me',
    }),
    updateProfile: builder.mutation<AuthUser, UpdateProfileRequest>({
      query: (body) => ({ url: '/auth/me', method: 'PATCH', body }),
    }),
    getProfileTransactionSummary: builder.query<ProfileTransactionSummary, void>({
      query: () => '/auth/me/transaction-summary',
      providesTags: ['Transaction'],
    }),
    getProfileUsage: builder.query<UserUsage, void>({
      query: () => '/auth/me/usage',
    }),
  }),
});

export const {
  useRegisterMutation,
  useLoginMutation,
  useLogoutMutation,
  useRefreshSessionMutation,
  useLazyGetMeQuery,
  useUpdateProfileMutation,
  useLazyGetProfileTransactionSummaryQuery,
  useGetProfileUsageQuery,
} = authApi;
