import { apiFetch, ApiError } from '@/api/client';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('@/api/auth', () => ({
  refreshAccessToken: vi.fn(),
}));

vi.mock('@/lib/error-map', () => ({
  translateError: (msg: string) => msg,
}));

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'OK',
    json: () => Promise.resolve(data),
    headers: new Headers(),
  } as Response;
}

function errorResponse(status: number, detail?: string): Response {
  return {
    ok: false,
    status,
    statusText: 'Bad Request',
    json: detail
      ? () => Promise.resolve({ detail })
      : () => Promise.reject(new Error('not json')),
    headers: new Headers(),
  } as Response;
}

describe('apiFetch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
  });

  it('makes a GET request to the correct URL', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ id: 1 }));

    const result = await apiFetch('/datasets/');
    expect(result).toEqual({ id: 1 });
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/datasets/',
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
  });

  it('sets Content-Type to application/json by default', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    await apiFetch('/test/');
    const headers: Headers = mockFetch.mock.calls[0][1].headers;
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  it('does not set Content-Type for FormData body', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));
    const formData = new FormData();

    await apiFetch('/upload/', { method: 'POST', body: formData });
    const headers: Headers = mockFetch.mock.calls[0][1].headers;
    expect(headers.get('Content-Type')).toBeNull();
  });

  it('includes Authorization header when token is present', async () => {
    useAuthStore.setState({ token: 'my-token' });
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    await apiFetch('/test/');
    const headers: Headers = mockFetch.mock.calls[0][1].headers;
    expect(headers.get('Authorization')).toBe('Bearer my-token');
  });

  it('does not include Authorization header when no token', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    await apiFetch('/test/');
    const headers: Headers = mockFetch.mock.calls[0][1].headers;
    expect(headers.get('Authorization')).toBeNull();
  });

  it('makes a POST request with body', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ created: true }));
    const body = JSON.stringify({ name: 'test' });

    const result = await apiFetch('/items/', { method: 'POST', body });
    expect(result).toEqual({ created: true });
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/items/',
      expect.objectContaining({ method: 'POST', body }),
    );
  });

  it('returns undefined for 204 No Content', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
      statusText: 'No Content',
      headers: new Headers(),
      json: () => Promise.reject(new Error('no body')),
    } as Response);

    const result = await apiFetch('/items/1', { method: 'DELETE' });
    expect(result).toBeUndefined();
  });

  it('throws ApiError with detail from JSON error body', async () => {
    mockFetch.mockResolvedValueOnce(errorResponse(400, 'Name is required'));

    try {
      await apiFetch('/test/');
      expect.fail('should have thrown');
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).message).toBe('Name is required');
      expect((e as ApiError).status).toBe(400);
    }
  });

  it('throws ApiError with statusText when body is not JSON', async () => {
    mockFetch.mockResolvedValueOnce(errorResponse(500));

    try {
      await apiFetch('/test/');
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).status).toBe(500);
    }
  });

  it('attempts token refresh on 401 and retries', async () => {
    const { refreshAccessToken } = await import('@/api/auth');
    const mockRefresh = vi.mocked(refreshAccessToken);
    mockRefresh.mockResolvedValueOnce({
      access_token: 'new-token',
      refresh_token: 'new-refresh',
      token_type: 'bearer',
      expires_in: 900,
    });

    useAuthStore.setState({ token: 'expired-token', refreshToken: 'my-refresh' });

    // First call returns 401, retry returns success
    mockFetch
      .mockResolvedValueOnce(errorResponse(401))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));

    const result = await apiFetch('/protected/');
    expect(result).toEqual({ ok: true });
    expect(mockRefresh).toHaveBeenCalledWith('my-refresh');
    expect(mockFetch).toHaveBeenCalledTimes(2);

    // Verify retry used the new token
    const retryHeaders: Headers = mockFetch.mock.calls[1][1].headers;
    expect(retryHeaders.get('Authorization')).toBe('Bearer new-token');
  });

  it('logs out and throws on 401 when no refresh token', async () => {
    useAuthStore.setState({ token: 'expired-token', refreshToken: null });
    mockFetch.mockResolvedValueOnce(errorResponse(401));

    await expect(apiFetch('/protected/')).rejects.toThrow(ApiError);
    expect(useAuthStore.getState().token).toBeNull();
  });

  it('logs out and throws on 401 when refresh fails', async () => {
    const { refreshAccessToken } = await import('@/api/auth');
    vi.mocked(refreshAccessToken).mockRejectedValueOnce(new Error('refresh failed'));

    useAuthStore.setState({ token: 'expired-token', refreshToken: 'bad-refresh' });
    // First call returns 401; refresh fails but token remains, so retry also gets 401
    mockFetch
      .mockResolvedValueOnce(errorResponse(401))
      .mockResolvedValueOnce(errorResponse(401));

    await expect(apiFetch('/protected/')).rejects.toThrow(ApiError);
    expect(useAuthStore.getState().token).toBeNull();
  });

  // RES-N1: `TypeError: Failed to fetch` is what browsers throw when the
  // network is unreachable (offline, DNS, CORS preflight block). Without
  // the safeFetch wrapper, this propagated as an unhandled rejection through
  // every TanStack Query. We now convert it to a friendly ApiError(status=0).
  describe('network error handling (RES-N1)', () => {
    it('converts TypeError from fetch into ApiError with status 0', async () => {
      mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));

      try {
        await apiFetch('/test/');
        expect.fail('should have thrown');
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError);
        expect((e as ApiError).status).toBe(0);
        expect((e as ApiError).message).toMatch(/network/i);
      }
    });

    it('converts TypeError from refresh-retry fetch into ApiError with status 0', async () => {
      const { refreshAccessToken } = await import('@/api/auth');
      vi.mocked(refreshAccessToken).mockResolvedValueOnce({
        access_token: 'new-token',
        refresh_token: 'new-refresh',
        token_type: 'bearer',
        expires_in: 900,
      });
      useAuthStore.setState({ token: 'expired-token', refreshToken: 'my-refresh' });

      // First call: 401 triggers refresh. Retry: network error.
      mockFetch
        .mockResolvedValueOnce(errorResponse(401))
        .mockRejectedValueOnce(new TypeError('Failed to fetch'));

      try {
        await apiFetch('/protected/');
        expect.fail('should have thrown');
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError);
        expect((e as ApiError).status).toBe(0);
      }
    });

    it('lets non-TypeError fetch rejections propagate unchanged (e.g. AbortError)', async () => {
      const abort = new DOMException('The operation was aborted', 'AbortError');
      mockFetch.mockRejectedValueOnce(abort);

      await expect(apiFetch('/test/')).rejects.toBe(abort);
    });
  });

  // SP-09: 3 concurrent 401 responses should collapse to a single refresh POST.
  // Smoke check on 2026-05-15 saw 3 concurrent /auth/refresh/ POSTs because the
  // proactive timer in use-auth.ts bypassed the client.ts mutex. Both call sites
  // must share the same in-flight singleton.
  describe('concurrent refresh de-duplication (SP-09)', () => {
    it('collapses 3 concurrent 401s into a single refresh POST', async () => {
      const { refreshAccessToken } = await import('@/api/auth');
      const mockRefresh = vi.mocked(refreshAccessToken);

      let resolveRefresh: (v: unknown) => void = () => {};
      mockRefresh.mockImplementation(
        () =>
          new Promise((resolve) => {
            resolveRefresh = resolve;
          }),
      );

      useAuthStore.setState({ token: 'expired', refreshToken: 'r' });

      // Each apiFetch call: 401, then retry success
      mockFetch
        .mockResolvedValueOnce(errorResponse(401))
        .mockResolvedValueOnce(errorResponse(401))
        .mockResolvedValueOnce(errorResponse(401))
        .mockResolvedValueOnce(jsonResponse({ ok: 1 }))
        .mockResolvedValueOnce(jsonResponse({ ok: 2 }))
        .mockResolvedValueOnce(jsonResponse({ ok: 3 }));

      // Kick off 3 concurrent requests; do not await yet
      const p1 = apiFetch('/a/');
      const p2 = apiFetch('/b/');
      const p3 = apiFetch('/c/');

      // Yield twice so all three reach the 401-branch and queue on the shared promise
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();

      // Now release the refresh
      resolveRefresh({
        access_token: 'new',
        refresh_token: 'r2',
        token_type: 'bearer',
        expires_in: 900,
      });

      await Promise.all([p1, p2, p3]);

      expect(mockRefresh).toHaveBeenCalledTimes(1);
    });

    it('clears the in-flight singleton on refresh failure so the next call retries', async () => {
      const { refreshAccessToken } = await import('@/api/auth');
      const mockRefresh = vi.mocked(refreshAccessToken);

      // First refresh attempt fails
      mockRefresh.mockRejectedValueOnce(new Error('boom'));
      useAuthStore.setState({ token: 'expired', refreshToken: 'r' });
      mockFetch
        .mockResolvedValueOnce(errorResponse(401))
        .mockResolvedValueOnce(errorResponse(401));

      await expect(apiFetch('/a/')).rejects.toThrow(ApiError);
      expect(mockRefresh).toHaveBeenCalledTimes(1);

      // Second wave: the singleton must have cleared, so a new refresh attempt fires
      mockRefresh.mockResolvedValueOnce({
        access_token: 'new',
        refresh_token: 'r2',
        token_type: 'bearer',
        expires_in: 900,
      });
      useAuthStore.setState({ token: 'expired-2', refreshToken: 'r' });
      mockFetch
        .mockResolvedValueOnce(errorResponse(401))
        .mockResolvedValueOnce(jsonResponse({ ok: 1 }));

      await apiFetch('/b/');
      expect(mockRefresh).toHaveBeenCalledTimes(2);
    });
  });
});
