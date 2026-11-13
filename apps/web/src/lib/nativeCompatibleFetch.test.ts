import { afterEach, describe, expect, it, vi } from 'vitest';

import { nativeCompatibleFetch } from './nativeCompatibleFetch';

type TestWindow = Window & { CapacitorWebFetch?: typeof fetch };

afterEach(() => {
  delete (window as TestWindow).CapacitorWebFetch;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('nativeCompatibleFetch', () => {
  it('bypasses CapacitorHttp for an RTK multipart Request', async () => {
    const nativeFetch = vi.fn<typeof fetch>().mockResolvedValue(new Response('{}'));
    const webKitFetch = vi.fn<typeof fetch>().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', nativeFetch);
    (window as TestWindow).CapacitorWebFetch = webKitFetch;

    const body = new FormData();
    body.append('image', new File([Uint8Array.from([0, 255, 216, 128])], 'receipt.jpg', { type: 'image/jpeg' }));
    const request = new Request('https://api.example.test/chat/image', { method: 'POST', body });

    await nativeCompatibleFetch(request);

    expect(request.headers.get('content-type')).toMatch(/^multipart\/form-data; boundary=/);
    expect(webKitFetch).toHaveBeenCalledWith(request, undefined);
    expect(nativeFetch).not.toHaveBeenCalled();
  });

  it('keeps normal JSON traffic on CapacitorHttp', async () => {
    const nativeFetch = vi.fn<typeof fetch>().mockResolvedValue(new Response('{}'));
    const webKitFetch = vi.fn<typeof fetch>().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', nativeFetch);
    (window as TestWindow).CapacitorWebFetch = webKitFetch;
    const request = new Request('https://api.example.test/chat', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{}',
    });

    await nativeCompatibleFetch(request);

    expect(nativeFetch).toHaveBeenCalledWith(request, undefined);
    expect(webKitFetch).not.toHaveBeenCalled();
  });
});
