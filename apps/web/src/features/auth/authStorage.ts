import { Capacitor } from '@capacitor/core';
import { SecureStorage } from '@aparajita/capacitor-secure-storage';

const ACCESS_TOKEN_KEY = 'affordabled.access_token';

function isNativeApp(): boolean {
  return Capacitor.isNativePlatform();
}

/** Persist native sessions in Keychain/Keystore; browser sessions remain cookie-based. */
export async function persistAccessToken(accessToken: string): Promise<void> {
  if (!isNativeApp()) return;

  try {
    await SecureStorage.set(ACCESS_TOKEN_KEY, accessToken);
  } catch {
    // Native secure storage is a resilience layer; the in-memory session still works.
  }
}

export async function getStoredAccessToken(): Promise<string | null> {
  if (!isNativeApp()) return null;

  try {
    const value = await SecureStorage.get(ACCESS_TOKEN_KEY);
    return typeof value === 'string' && value.length > 0 ? value : null;
  } catch {
    return null;
  }
}

export async function clearStoredAccessToken(): Promise<void> {
  if (!isNativeApp()) return;

  try {
    await SecureStorage.remove(ACCESS_TOKEN_KEY);
  } catch {
    // Ignore cleanup failures; the API session is still cleared in memory.
  }
}
