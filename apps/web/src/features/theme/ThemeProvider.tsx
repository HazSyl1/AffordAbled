import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Capacitor } from '@capacitor/core';
import { StatusBar, Style } from '@capacitor/status-bar';
import { ThemeContext, type ThemeMode } from './themeContext';

const STORAGE_KEY = 'affordabled-theme';
function readInitialMode(): ThemeMode {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return window.matchMedia?.('(prefers-color-scheme: dark)')?.matches ? 'dark' : 'light';
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(readInitialMode);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, mode);
    document.documentElement.dataset.theme = mode;
    const backgroundColor = mode === 'dark' ? '#000000' : '#F0F4F8';
    document.querySelector<HTMLMetaElement>('#app-theme-color')?.setAttribute('content', backgroundColor);

    if (Capacitor.isNativePlatform()) {
      void Promise.allSettled([
        StatusBar.setOverlaysWebView({ overlay: false }),
        StatusBar.setBackgroundColor({ color: backgroundColor }),
        StatusBar.setStyle({ style: mode === 'dark' ? Style.Light : Style.Dark }),
      ]);
    }
  }, [mode]);

  const value = useMemo(() => ({ mode, setMode }), [mode]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

