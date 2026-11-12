import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';

import { LazyLandingPage } from './LazyPages';
import { useAppSelector } from './hooks';

const HAS_OPENED_APP_KEY = 'affordabled.has_opened_app';

function readFirstOpenState(): boolean {
  try {
    return window.localStorage.getItem(HAS_OPENED_APP_KEY) !== 'true';
  } catch {
    return true;
  }
}

export function HomeRoute() {
  const accessToken = useAppSelector((state) => state.auth.accessToken);
  const [isFirstOpen] = useState(readFirstOpenState);

  useEffect(() => {
    try {
      window.localStorage.setItem(HAS_OPENED_APP_KEY, 'true');
    } catch {
      // If storage is unavailable, keep the first-open landing experience.
    }
  }, []);

  if (accessToken) {
    return <Navigate to='/dashboard' replace />;
  }

  if (isFirstOpen) {
    return <LazyLandingPage />;
  }

  return <Navigate to='/login' replace />;
}
