import { Navigate, Outlet } from 'react-router-dom';

import { Layout } from '../components/templates/Layout';
import { useAppSelector } from './hooks';

export function ProtectedRoute() {
  const accessToken = useAppSelector((state) => state.auth.accessToken);

  if (!accessToken) {
    return <Navigate to="/login" replace />;
  }

  return (
    <Layout>
      <Outlet />
    </Layout>
  );
}
