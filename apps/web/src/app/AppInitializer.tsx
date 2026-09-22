import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { useRefreshSessionMutation } from '../features/auth/authApi';
import { setCredentials } from '../features/auth/authSlice';
import { useAppDispatch } from './hooks';

/**
 * On first load the access token only ever lives in memory, so a page
 * refresh loses it. This silently exchanges the httpOnly refresh cookie
 * (if any) for a new access token before the router renders anything.
 */
export function AppInitializer({ children }: { children: ReactNode }) {
  const dispatch = useAppDispatch();
  const [refreshSession] = useRefreshSessionMutation();
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    let isMounted = true;

    refreshSession()
      .unwrap()
      .then((result) => {
        if (isMounted) {
          dispatch(setCredentials({ accessToken: result.access_token }));
        }
      })
      .catch(() => {
        // No valid session cookie — the user will see the login page.
      })
      .finally(() => {
        if (isMounted) {
          setIsChecking(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [dispatch, refreshSession]);

  if (isChecking) {
    return <p>Loading…</p>;
  }

  return <>{children}</>;
}
