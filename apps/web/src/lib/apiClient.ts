import type { BaseQueryFn, FetchArgs, FetchBaseQueryError } from '@reduxjs/toolkit/query';
import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

import { API_BASE_URL } from './env';
import type { RootState } from '../app/store';
import { clearCredentials, setAuthNotice, setCredentials } from '../features/auth/authSlice';
import { AUTH_UI_TEXT } from '../constants';

const rawBaseQuery = fetchBaseQuery({
  baseUrl: `${API_BASE_URL}/api/v1`,
  credentials: 'include', // sends the httpOnly refresh cookie automatically
  prepareHeaders: (headers, { getState }) => {
    const accessToken = (getState() as RootState).auth.accessToken;
    if (accessToken) {
      headers.set('Authorization', `Bearer ${accessToken}`);
    }
    return headers;
  },
});

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
    const refreshResult = await rawBaseQuery(
      { url: '/auth/refresh', method: 'POST' },
      api,
      extraOptions,
    );

    if (refreshResult.data) {
      const { access_token: accessToken } = refreshResult.data as { access_token: string };
      api.dispatch(setCredentials({ accessToken }));
      result = await rawBaseQuery(args, api, extraOptions);
      if (result.error?.status === 401) {
        api.dispatch(clearCredentials());
        api.dispatch(setAuthNotice(AUTH_UI_TEXT.sessionExpiredError));
        api.dispatch(apiClient.util.resetApiState());
      }
    } else {
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
  tagTypes: ['Account', 'Category', 'Transaction', 'Split', 'Memory'],
  endpoints: () => ({}),
});
