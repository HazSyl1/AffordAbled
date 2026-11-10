import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { PageLoader } from '../components/molecules/PageLoader';
import { useRefreshSessionMutation } from '../features/auth/authApi';
import { getStoredAccessToken, persistAccessToken } from '../features/auth/authStorage';
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

    const restoreSession = async () => {
      const storedAccessToken = await getStoredAccessToken();

      try {
        const result = await refreshSession().unwrap();
        await persistAccessToken(result.access_token);
        if (isMounted) {
          dispatch(setCredentials({ accessToken: result.access_token }));
        }
      } catch {
        // Capacitor WebViews can lose the refresh cookie between launches.
        // Fall back to the Keychain/Keystore-backed access token in that case.
        if (isMounted && storedAccessToken) {
          dispatch(setCredentials({ accessToken: storedAccessToken }));
        }
      } finally {
        if (isMounted) {
          setIsChecking(false);
        }
      }
    };

    void restoreSession();

    return () => {
      isMounted = false;
    };
  }, [dispatch, refreshSession]);

  if (isChecking) {
    return <PageLoader />;
  }

  return <>{children}</>;
}
