import { createBrowserRouter } from 'react-router-dom';

import { AccountsPage } from '../pages/AccountsPage';
import { DashboardPage } from '../pages/DashboardPage';
import { LoginPage } from '../pages/LoginPage';
import { ProfilePage } from '../pages/ProfilePage';
import { RegisterPage } from '../pages/RegisterPage';
import { SplitsPage } from '../pages/SplitsPage';
import { TransactionsPage } from '../pages/TransactionsPage';
import { ProtectedRoute } from './ProtectedRoute';

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/register', element: <RegisterPage /> },
  {
    element: <ProtectedRoute />,
    children: [
      { path: '/', element: <DashboardPage /> },
      { path: '/accounts', element: <AccountsPage /> },
      { path: '/transactions', element: <TransactionsPage /> },
      { path: '/splits', element: <SplitsPage /> },
      { path: '/splits/new', element: <SplitsPage /> },
      { path: '/profile', element: <ProfilePage /> },
    ],
  },
]);
