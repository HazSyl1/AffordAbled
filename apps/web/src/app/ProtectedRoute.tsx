import { Navigate, Outlet } from 'react-router-dom';

import { useAppSelector } from './hooks';

export function ProtectedRoute() {
  const accessToken = useAppSelector((state) => state.auth.accessToken);

  if (!accessToken) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
