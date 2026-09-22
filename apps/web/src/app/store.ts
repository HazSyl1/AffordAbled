import { combineReducers, configureStore } from '@reduxjs/toolkit';

import { apiClient } from '../lib/apiClient';
import authReducer from '../features/auth/authSlice';

const rootReducer = combineReducers({
  auth: authReducer,
  [apiClient.reducerPath]: apiClient.reducer,
});

export function makeStore() {
  return configureStore({
    reducer: rootReducer,
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(apiClient.middleware),
  });
}

export const store = makeStore();

export type RootState = ReturnType<typeof rootReducer>;
export type AppDispatch = typeof store.dispatch;
