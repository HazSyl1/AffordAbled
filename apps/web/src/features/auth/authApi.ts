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
}

export interface ProfileTransactionSummary {
  message: string;
  transaction_count: number;
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
} = authApi;
