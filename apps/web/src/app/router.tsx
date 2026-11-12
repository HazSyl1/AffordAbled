import { createBrowserRouter } from 'react-router-dom';

import { HomeRoute } from './HomeRoute';
import { PublicOnlyRoute } from './PublicOnlyRoute';
import { ProtectedRoute } from './ProtectedRoute';
import {
  LazyAccountsPage, LazyChatPage, LazyDashboardPage, LazyLoginPage,
  LazyProfilePage, LazyRegisterPage, LazySplitsPage, LazyTransactionsPage,
} from './LazyPages';

export const router = createBrowserRouter([
  { path: '/', element: <HomeRoute /> },
  {
    element: <PublicOnlyRoute />,
    children: [
      { path: '/login', element: <LazyLoginPage /> },
      { path: '/register', element: <LazyRegisterPage /> },
    ],
  },
  {
    element: <ProtectedRoute />,
    children: [
      { path: '/dashboard', element: <LazyDashboardPage /> },
      { path: '/chat', element: <LazyChatPage /> },
      { path: '/accounts', element: <LazyAccountsPage /> },
      { path: '/transactions', element: <LazyTransactionsPage /> },
      { path: '/splits', element: <LazySplitsPage /> },
      { path: '/splits/new', element: <LazySplitsPage /> },
      { path: '/profile', element: <LazyProfilePage /> },
    ],
  },
]);
