/** Extract a user-safe FastAPI/RTK Query error message instead of hiding it behind a generic failure. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  if (typeof error !== 'object' || error === null) return fallback;

  if ('data' in error) {
    const data = (error as { data?: unknown }).data;
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      const detail = (data as { detail?: unknown }).detail;
      if (typeof detail === 'string' && detail.trim()) return detail.trim();
      if (typeof detail === 'object' && detail !== null && 'message' in detail) {
        const message = (detail as { message?: unknown }).message;
        if (typeof message === 'string' && message.trim()) return message.trim();
      }
    }
  }

  if ('error' in error) {
    const message = (error as { error?: unknown }).error;
    if (typeof message === 'string' && message.trim()) return message.trim();
  }

  return fallback;
}
