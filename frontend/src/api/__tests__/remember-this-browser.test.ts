import { rememberThisBrowser } from '@/api/auth';

describe('rememberThisBrowser', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('posts the token from this origin with the app header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await rememberThisBrowser('a b');

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/auth\/login\/device-trust\?token=a%20b$/);
    expect(init).toMatchObject({
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-GeoLens-Auth-Mode': 'cookie' },
    });
  });

  it('turns a coded refusal into its translated message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: { code: 'device_trust_browser_full', message: 'x' } }),
          { status: 409 },
        ),
      ),
    );
    await expect(rememberThisBrowser('t')).rejects.toThrow(
      'This browser already remembers as many accounts as it can.',
    );
  });
});
