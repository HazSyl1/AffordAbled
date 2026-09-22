import { createBrowserRouter } from 'react-router-dom';

import { DashboardPage } from '../pages/DashboardPage';
import { LoginPage } from '../pages/LoginPage';
import { RegisterPage } from '../pages/RegisterPage';
import { TransactionsPage } from '../pages/TransactionsPage';
import { ProtectedRoute } from './ProtectedRoute';

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/register', element: <RegisterPage /> },
  {
    element: <ProtectedRoute />,
    children: [
      { path: '/', element: <DashboardPage /> },
      { path: '/transactions', element: <TransactionsPage /> },
    ],
  },
]);
