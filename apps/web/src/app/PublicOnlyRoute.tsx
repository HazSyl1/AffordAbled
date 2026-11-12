import { Navigate, Outlet } from 'react-router-dom';

import { useAppSelector } from './hooks';

/** Keep authenticated users out of the login and registration screens. */
export function PublicOnlyRoute() {
  const accessToken = useAppSelector((state) => state.auth.accessToken);

  if (accessToken) {
    return <Navigate to='/dashboard' replace />;
  }

  return <Outlet />;
}
