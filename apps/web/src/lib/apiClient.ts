import type { BaseQueryFn, FetchArgs, FetchBaseQueryError } from '@reduxjs/toolkit/query';
import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

import { API_BASE_URL } from './env';
import type { RootState } from '../app/store';
import { clearStoredAccessToken, persistAccessToken } from '../features/auth/authStorage';
import { clearCredentials, setAuthNotice, setCredentials } from '../features/auth/authSlice';
import { AUTH_UI_TEXT } from '../constants';
import { nativeCompatibleFetch } from './nativeCompatibleFetch';

const rawBaseQuery = fetchBaseQuery({
  baseUrl: `${API_BASE_URL}/api/v1`,
  credentials: 'include', // sends the httpOnly refresh cookie automatically
  fetchFn: nativeCompatibleFetch,
  prepareHeaders: (headers, { getState }) => {
    const accessToken = (getState() as RootState).auth.accessToken;
    if (accessToken) {
      headers.set('Authorization', `Bearer ${accessToken}`);
    }
    return headers;
  },
});

let refreshInFlight: Promise<string | null> | null = null;

// On a 401, try exactly one silent refresh (using the httpOnly cookie), then
// retry the original request once. If the refresh itself fails, log out.
const baseQueryWithReauth: BaseQueryFn<string | FetchArgs, unknown, FetchBaseQueryError> = async (
  args,
  api,
  extraOptions,
) => {
  const hadAccessToken = Boolean((api.getState() as RootState).auth.accessToken);
  let result = await rawBaseQuery(args, api, extraOptions);

  const requestUrl = typeof args === 'string' ? args : args.url;
  const isAuthEntryRequest = ['/auth/login', '/auth/register', '/auth/google/callback', '/auth/refresh']
    .some((path) => requestUrl.endsWith(path));

  if (result.error?.status === 401 && !isAuthEntryRequest) {
    if (!refreshInFlight) {
      refreshInFlight = (async () => {
        const refreshResult = await rawBaseQuery(
          { url: '/auth/refresh', method: 'POST' },
          api,
          extraOptions,
        );
        if (!refreshResult.data) return null;
        const { access_token: accessToken } = refreshResult.data as { access_token: string };
        await persistAccessToken(accessToken);
        api.dispatch(setCredentials({ accessToken }));
        return accessToken;
      })().finally(() => {
        refreshInFlight = null;
      });
    }

    const refreshedAccessToken = await refreshInFlight;
    if (refreshedAccessToken) {
      result = await rawBaseQuery(args, api, extraOptions);
      if (result.error?.status === 401) {
        await clearStoredAccessToken();
        api.dispatch(clearCredentials());
        api.dispatch(setAuthNotice(AUTH_UI_TEXT.sessionExpiredError));
        api.dispatch(apiClient.util.resetApiState());
      }
    } else {
      await clearStoredAccessToken();
      api.dispatch(clearCredentials());
      if (hadAccessToken) {
        api.dispatch(setAuthNotice(AUTH_UI_TEXT.sessionExpiredError));
      }
      api.dispatch(apiClient.util.resetApiState());
    }
  }

  return result;
};

export const apiClient = createApi({
  reducerPath: 'api',
  baseQuery: baseQueryWithReauth,
  tagTypes: ['Account', 'Category', 'Transaction', 'RecurringTransaction', 'Split', 'SplitNotification', 'Memory'],
  endpoints: () => ({}),
});
