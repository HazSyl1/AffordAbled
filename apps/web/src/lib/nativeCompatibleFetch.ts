type CapacitorFetchWindow = Window & {
  /** Original WebKit fetch saved by Capacitor before it patches window.fetch. */
  CapacitorWebFetch?: typeof fetch;
};

/**
 * RTK Query calls fetch with a Request instance. CapacitorHttp 8 converts the
 * resulting multipart ReadableStream to text on iOS, corrupting binary files.
 * Keep native HTTP for normal API traffic, but let WebKit send multipart
 * requests byte-for-byte. The API explicitly allows the Capacitor origin.
 */
export function nativeCompatibleFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const request = input instanceof Request && init === undefined ? input : new Request(input, init);
  const contentType = request.headers.get('content-type')?.toLowerCase() ?? '';
  const originalWebFetch = typeof window === 'undefined'
    ? undefined
    : (window as CapacitorFetchWindow).CapacitorWebFetch;

  if (originalWebFetch && contentType.startsWith('multipart/form-data')) {
    return originalWebFetch.call(window, input, init);
  }

  return fetch(input, init);
}
