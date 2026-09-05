import { apiFetch, ApiError, tryRefresh } from '@/api/client';
import { useAuthStore } from '@/stores/auth-store';
import type { TokenResponse } from '@/types/api';

vi.mock('@/api/auth', () => ({
  refreshAccessToken: vi.fn(),
  // fix(#1446): the 401 path now dispatches a best-effort server revocation,
  // because a transiently-failed refresh leaves a live httpOnly cookie that
  // clearing the store cannot reach.
  logoutSession: vi.fn(() => Promise.resolve()),
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

  it('classifies an unmapped JSON detail instead of displaying backend prose', async () => {
    mockFetch.mockResolvedValueOnce(errorResponse(400, 'Name is required'));

    try {
      await apiFetch('/test/');
      expect.fail('should have thrown');
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).message).toBe(
        'The request could not be completed. Check your input.',
      );
      expect((e as ApiError).status).toBe(400);
    }
  });

  it('localizes a FastAPI 422 detail array without exposing raw JSON', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      statusText: 'Unprocessable Entity',
      headers: new Headers(),
      json: () =>
        Promise.resolve({
          detail: [
            { type: 'missing', loc: ['body', 'name'], msg: 'Field required', input: {} },
          ],
        }),
    } as Response);

    try {
      await apiFetch('/test/');
      expect.fail('should have thrown');
    } catch (e) {
      expect((e as ApiError).message).toBe('name is required.');
      expect((e as ApiError).message).not.toContain('{');
      // the raw payload is still available to callers that want it
      expect((e as ApiError).body).toEqual([
        { type: 'missing', loc: ['body', 'name'], msg: 'Field required', input: {} },
      ]);
    }
  });

  it('uses a localized status category when the body is not JSON', async () => {
    mockFetch.mockResolvedValueOnce(errorResponse(500));

    try {
      await apiFetch('/test/');
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).status).toBe(500);
      expect((e as ApiError).message).toBe(
        'The service is temporarily unavailable. Try again later.',
      );
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
    expect(mockRefresh).toHaveBeenCalledWith('my-refresh', expect.any(AbortSignal));
    expect(mockFetch).toHaveBeenCalledTimes(2);

    // Verify retry used the new token
    const retryHeaders: Headers = mockFetch.mock.calls[1][1].headers;
    expect(retryHeaders.get('Authorization')).toBe('Bearer new-token');
  });

  // BUG-016: after a successful refresh, a retry that returns a non-401 error
  // (e.g. 403 Forbidden) must be RETURNED to the caller — NOT treated as an
  // auth failure. Pre-fix this fell through to logout(); post-fix it returns
  // the retry response.
  describe('BUG-016: non-401 retry after refresh is returned, not a logout', () => {
    it('returns 403 retry response without logging out', async () => {
      const { refreshAccessToken } = await import('@/api/auth');
      vi.mocked(refreshAccessToken).mockResolvedValueOnce({
        access_token: 'new-token',
        refresh_token: 'new-refresh',
        token_type: 'bearer',
        expires_in: 900,
      });

      useAuthStore.setState({ token: 'expired-token', refreshToken: 'my-refresh' });

      // First call: 401. Refresh succeeds. Retry: 403 (authorization, not auth).
      mockFetch
        .mockResolvedValueOnce(errorResponse(401))
        .mockResolvedValueOnce(errorResponse(403));

      // apiFetch wraps non-ok responses in ApiError AFTER authenticatedFetch returns —
      // but authenticatedFetch must RETURN the 403 response instead of logging out.
      // The resulting ApiError should have status 403, not 401, and the user must
      // still be logged in.
      await expect(apiFetch('/protected/')).rejects.toMatchObject({ status: 403 });
      expect(useAuthStore.getState().token).toBe('new-token'); // NOT logged out
    });

    it('returns 500 retry response without logging out', async () => {
      const { refreshAccessToken } = await import('@/api/auth');
      vi.mocked(refreshAccessToken).mockResolvedValueOnce({
        access_token: 'new-token',
        refresh_token: 'new-refresh',
        token_type: 'bearer',
        expires_in: 900,
      });

      useAuthStore.setState({ token: 'expired-token', refreshToken: 'my-refresh' });

      mockFetch
        .mockResolvedValueOnce(errorResponse(401))
        .mockResolvedValueOnce(errorResponse(500, 'Internal Server Error'));

      await expect(apiFetch('/protected/')).rejects.toMatchObject({ status: 500 });
      expect(useAuthStore.getState().token).toBe('new-token'); // NOT logged out
    });

    it('still logs out when retry is ALSO 401', async () => {
      const { refreshAccessToken } = await import('@/api/auth');
      vi.mocked(refreshAccessToken).mockResolvedValueOnce({
        access_token: 'new-token',
        refresh_token: 'new-refresh',
        token_type: 'bearer',
        expires_in: 900,
      });

      useAuthStore.setState({ token: 'expired-token', refreshToken: 'my-refresh' });

      // Refresh "succeeds" but retry is still 401 → logout
      mockFetch
        .mockResolvedValueOnce(errorResponse(401))
        .mockResolvedValueOnce(errorResponse(401));

      await expect(apiFetch('/protected/')).rejects.toMatchObject({ status: 401 });
      expect(useAuthStore.getState().token).toBeNull(); // logged out
    });
  });

  // fix(#1302): with no stored refresh token the session may still be alive —
  // the credential is an httpOnly cookie JS cannot see — so a 401 must still
  // attempt a refresh. Only when that refresh also fails is the session dead.
  it('still attempts a cookie refresh on 401 with no stored refresh token', async () => {
    const { refreshAccessToken } = await import('@/api/auth');
    vi.mocked(refreshAccessToken).mockRejectedValueOnce(new Error('refresh failed'));

    useAuthStore.setState({ token: 'cookie-session-token', refreshToken: null });
    // fix(#1849): a failed refresh no longer retries with the dead token, so
    // only the initial 401 fetch happens — one queued response, not two.
    mockFetch.mockResolvedValueOnce(errorResponse(401));

    await expect(apiFetch('/protected/')).rejects.toThrow(ApiError);
    expect(refreshAccessToken).toHaveBeenCalledWith(null, expect.any(AbortSignal));
    expect(useAuthStore.getState().token).toBeNull();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('does not attempt a refresh on an anonymous 401', async () => {
    const { refreshAccessToken } = await import('@/api/auth');

    useAuthStore.setState({ token: null, refreshToken: null });
    mockFetch.mockResolvedValueOnce(errorResponse(401));

    await expect(apiFetch('/protected/')).rejects.toThrow(ApiError);
    expect(refreshAccessToken).not.toHaveBeenCalled();
  });

  it('logs out and throws on 401 when refresh fails', async () => {
    const { refreshAccessToken } = await import('@/api/auth');
    vi.mocked(refreshAccessToken).mockRejectedValueOnce(new Error('refresh failed'));

    // A distinct access token per test: the session-death latch dedupes on it,
    // and real sessions never reuse one (every JWT carries a fresh jti).
    useAuthStore.setState({ token: 'expired-token', refreshToken: 'bad-refresh' });
    mockFetch.mockResolvedValueOnce(errorResponse(401));

    await expect(apiFetch('/protected/')).rejects.toThrow(ApiError);
    expect(useAuthStore.getState().token).toBeNull();
    // fix(#1849): a failed refresh must not retry the original request with
    // the now-dead token — only the initial 401 fetch happens.
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  describe('tryRefresh return value (#1849)', () => {
    it('returns false and skips the retry when refresh fails, going straight to logout', async () => {
      const { refreshAccessToken } = await import('@/api/auth');
      vi.mocked(refreshAccessToken).mockRejectedValueOnce(new ApiError('unauthorized', 401));

      // A distinct access token per test: the session-death latch dedupes on
      // it (see the note on 'logs out and throws on 401 when refresh fails').
      useAuthStore.setState({ token: 'expired-token-1849a', refreshToken: 'bad-refresh' });
      mockFetch.mockResolvedValueOnce(errorResponse(401));

      await expect(apiFetch('/protected/')).rejects.toThrow(ApiError);
      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(useAuthStore.getState().token).toBeNull();
    });

    it('returns true and retries exactly once when refresh succeeds', async () => {
      const { refreshAccessToken } = await import('@/api/auth');
      vi.mocked(refreshAccessToken).mockResolvedValueOnce({
        access_token: 'fresh-token',
        refresh_token: 'fresh-refresh',
        expires_in: 900,
        token_type: 'bearer',
      });

      useAuthStore.setState({ token: 'expired-token-1849b', refreshToken: 'old-refresh' });
      mockFetch
        .mockResolvedValueOnce(errorResponse(401))
        .mockResolvedValueOnce(jsonResponse({ ok: true }));

      await expect(apiFetch('/protected/')).resolves.toEqual({ ok: true });
      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(useAuthStore.getState().token).toBe('fresh-token');
    });

    it('backs off once on a 429 before giving up', async () => {
      vi.useFakeTimers();
      try {
        const { refreshAccessToken } = await import('@/api/auth');
        vi.mocked(refreshAccessToken).mockRejectedValueOnce(new ApiError('rate limited', 429));

        useAuthStore.setState({ token: 'expired-token-1849c', refreshToken: 'bad-refresh' });
        mockFetch.mockResolvedValueOnce(errorResponse(401));

        const pending = apiFetch('/protected/').catch((e: unknown) => e);
        await vi.advanceTimersByTimeAsync(2000);
        const result = await pending;

        expect(result).toBeInstanceOf(ApiError);
        expect(mockFetch).toHaveBeenCalledTimes(1);
        expect(useAuthStore.getState().token).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    });

    // fix(#1862 review P2): a regression of the fix above. Before it, the
    // stale-token truthiness masked this case by accident — `!!token` was
    // true regardless of whose refresh put it there. Reporting failure here
    // for an outcome the store shows as success would make the caller treat
    // a peer tab's valid session as dead.
    it('returns true when a peer tab rotates the token while this refresh fails', async () => {
      const { refreshAccessToken } = await import('@/api/auth');
      let rejectRefresh: (err: unknown) => void = () => {};
      vi.mocked(refreshAccessToken).mockImplementation(
        () =>
          new Promise<TokenResponse>((_resolve, reject) => {
            rejectRefresh = reject;
          }),
      );

      useAuthStore.setState({ token: 'stale-local-token', refreshToken: 'r' });

      const pending = tryRefresh();
      await Promise.resolve();

      // Simulate auth-store.ts's cross-tab `storage` listener rehydrating a
      // peer tab's successful refresh into this tab's store while this
      // attempt is still in flight.
      useAuthStore.setState({ token: 'peer-rotated-token' });
      rejectRefresh(new Error('network error'));

      await expect(pending).resolves.toBe(true);
      expect(useAuthStore.getState().token).toBe('peer-rotated-token');
    });

    it('still returns false when the token is unchanged after a failed refresh', async () => {
      const { refreshAccessToken } = await import('@/api/auth');
      vi.mocked(refreshAccessToken).mockRejectedValueOnce(new Error('boom'));

      useAuthStore.setState({ token: 'unchanged-token', refreshToken: 'r' });

      await expect(tryRefresh()).resolves.toBe(false);
      expect(useAuthStore.getState().token).toBe('unchanged-token');
    });
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

      let resolveRefresh: (v: TokenResponse | PromiseLike<TokenResponse>) => void = () => {};
      mockRefresh.mockImplementation(
        () =>
          new Promise<TokenResponse>((resolve) => {
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
      // fix(#1849): a failed refresh no longer retries with the dead token —
      // one queued response, not two.
      mockFetch.mockResolvedValueOnce(errorResponse(401));

      await expect(apiFetch('/a/')).rejects.toThrow(ApiError);
      expect(mockRefresh).toHaveBeenCalledTimes(1);
      expect(mockFetch).toHaveBeenCalledTimes(1);

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
