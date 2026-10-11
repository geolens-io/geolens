import { abortInflightRefresh, ApiError, tryRefresh } from '@/api/client';
import { refreshAccessToken } from '@/api/auth';
import {
  restoreSession,
  restoreSessionBeforeRender,
  retrySessionRestore,
  useSessionRestore,
  wireSessionSync,
} from '@/lib/session-sync';
import { completeSignIn } from '@/lib/sign-in';
import { useAuthStore } from '@/stores/auth-store';
import { otherTab } from '@/test/broadcast-channel';
import type { TokenResponse, UserResponse } from '@/types/api';

vi.mock('@/api/auth', () => ({
  refreshAccessToken: vi.fn(),
  getMe: vi.fn(() => new Promise(() => {})),
  revokeCurrentSession: vi.fn(() => Promise.resolve()),
  logoutSession: vi.fn(() => Promise.resolve()),
}));

const STORAGE_KEY = 'geolens-auth';
const user = { id: 'u1', username: 'someone', roles: ['editor'] } as unknown as UserResponse;

function issued(access: string): TokenResponse {
  return { access_token: access, refresh_token: null, token_type: 'bearer', expires_in: 900 };
}

/** What a reload finds: the store as rehydrated from storage, with no token in memory. */
async function reloadWith(state: Record<string, unknown>): Promise<void> {
  // Every store write persists, so storage is seeded after the reset.
  useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null });
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ state, version: 2 }));
  await useAuthStore.persist.rehydrate();
}

/** Let the fake channel deliver and the handlers it triggers settle. */
async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe('session recovery and cross-tab sync', () => {
  let unwire: () => void;
  let peer: ReturnType<typeof otherTab>;

  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, '', '/login');
    window.localStorage.removeItem(STORAGE_KEY);
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null, sessionId: null });
    unwire = wireSessionSync();
    peer = otherTab();
  });

  afterEach(() => {
    peer.close();
    unwire();
    abortInflightRefresh();
    useSessionRestore.setState({ failures: 0 });
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null, sessionId: null });
    window.localStorage.removeItem(STORAGE_KEY);
    window.history.replaceState({}, '', '/');
  });

  it('recovers a reloaded cookie session from the refresh cookie', async () => {
    vi.mocked(refreshAccessToken).mockResolvedValueOnce(issued('recovered'));
    await reloadWith({ sessionId: 'session-1', user });

    await restoreSession();

    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
    expect(vi.mocked(refreshAccessToken).mock.calls[0][0]).toBeNull();
    expect(useAuthStore.getState()).toMatchObject({ token: 'recovered', sessionId: 'session-1', user });
    expect(window.localStorage.getItem(STORAGE_KEY)).not.toContain('recovered');
  });

  it('leaves the OAuth callback page to install the session its redirect issued', async () => {
    window.history.replaceState({}, '', '/oauth/callback');
    await reloadWith({ sessionId: 'session-1', user });

    await restoreSessionBeforeRender();

    expect(refreshAccessToken).not.toHaveBeenCalled();
  });

  it('abandons a refresh of the replaced session when a sign-in completes', async () => {
    let signal: AbortSignal | undefined;
    vi.mocked(refreshAccessToken).mockImplementationOnce((_token, abortSignal) => {
      signal = abortSignal;
      return new Promise(() => {});
    });
    await reloadWith({ sessionId: 'session-1', user });
    void restoreSession();
    await vi.waitFor(() => expect(signal).toBeDefined());

    void completeSignIn(issued('new-login'));

    expect(signal?.aborted).toBe(true);
    expect(useAuthStore.getState().token).toBe('new-login');
  });

  it('does nothing on a reload with no session to recover', async () => {
    await reloadWith({ sessionId: null, user: null });

    await restoreSession();

    expect(refreshAccessToken).not.toHaveBeenCalled();
  });

  it('ends a session whose refresh cookie is rejected, in every tab', async () => {
    vi.mocked(refreshAccessToken).mockRejectedValueOnce(new ApiError('expired', 401));
    await reloadWith({ sessionId: 'session-1', user });

    await restoreSession();
    await settle();

    expect(useAuthStore.getState()).toMatchObject({ token: null, sessionId: null, user: null });
    expect(peer.received).toEqual([{ type: 'logout', sessionId: 'session-1' }]);
  });

  it('keeps the session for a later retry when the refresh fails transiently', async () => {
    vi.mocked(refreshAccessToken).mockRejectedValueOnce(new ApiError('unavailable', 503));
    await reloadWith({ sessionId: 'session-1', user });

    vi.useFakeTimers();
    try {
      vi.mocked(refreshAccessToken).mockResolvedValueOnce(issued('recovered'));
      await restoreSession();

      expect(useAuthStore.getState()).toMatchObject({ token: null, sessionId: 'session-1', user });

      // Nothing on a signed-out page asks again, so the recovery retries itself
      // once the refresh back-off has passed.
      await vi.advanceTimersByTimeAsync(30_000);
      expect(refreshAccessToken).toHaveBeenCalledTimes(2);
      expect(useAuthStore.getState()).toMatchObject({ token: 'recovered', sessionId: 'session-1' });
    } finally {
      vi.useRealTimers();
    }
  });

  it('retries a rate-limited recovery once the server says it may', async () => {
    const limited = Object.assign(new ApiError('rate limited', 429), { retryAfterMs: 5_000 });
    vi.mocked(refreshAccessToken).mockRejectedValueOnce(limited);
    await reloadWith({ sessionId: 'session-1', user });

    vi.useFakeTimers();
    try {
      vi.mocked(refreshAccessToken).mockResolvedValueOnce(issued('recovered'));
      const pending = restoreSession();
      await vi.advanceTimersByTimeAsync(2_000);
      await pending;
      expect(useSessionRestore.getState().failures).toBe(1);

      await vi.advanceTimersByTimeAsync(4_000);
      expect(refreshAccessToken).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(1_000);
      expect(refreshAccessToken).toHaveBeenCalledTimes(2);
      expect(useAuthStore.getState()).toMatchObject({ token: 'recovered', sessionId: 'session-1' });
    } finally {
      vi.useRealTimers();
    }
  });

  it('retries a stalled recovery at once when asked to', async () => {
    vi.mocked(refreshAccessToken).mockRejectedValueOnce(new ApiError('unavailable', 503));
    await reloadWith({ sessionId: 'session-1', user });
    await restoreSession();
    expect(useSessionRestore.getState().failures).toBe(1);

    vi.mocked(refreshAccessToken).mockResolvedValueOnce(issued('recovered'));
    retrySessionRestore();

    await vi.waitFor(() => expect(useAuthStore.getState().token).toBe('recovered'));
    expect(refreshAccessToken).toHaveBeenCalledTimes(2);
  });

  it('recovers a migrating legacy session with its in-memory refresh token', async () => {
    vi.mocked(refreshAccessToken).mockResolvedValueOnce({ ...issued('migrated'), order: 7 });
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ state: { token: 'legacy-access', refreshToken: 'legacy-refresh', user } }),
    );
    await useAuthStore.persist.rehydrate();

    await restoreSession();
    await settle();

    expect(vi.mocked(refreshAccessToken).mock.calls[0][0]).toBe('legacy-refresh');
    expect(useAuthStore.getState()).toMatchObject({ token: 'migrated', refreshToken: null });
    expect(window.localStorage.getItem(STORAGE_KEY)).not.toContain('legacy');
    // Other tabs can recover the migrated session from the cookie now.
    expect(peer.received).toEqual([{ type: 'login', sessionId: useAuthStore.getState().sessionId, order: 7 }]);
  });

  it('slow refresh does not delay render', async () => {
    let finish!: (tokens: TokenResponse) => void;
    vi.mocked(refreshAccessToken).mockImplementationOnce(
      () => new Promise((resolve) => { finish = resolve; }),
    );
    await reloadWith({ sessionId: 'session-1', user });

    await restoreSessionBeforeRender(20);
    expect(useAuthStore.getState().token).toBeNull();

    finish(issued('late'));
    await vi.waitFor(() => expect(useAuthStore.getState().token).toBe('late'));
  });

  it('signs this tab out when another tab logs out of the same session', async () => {
    useAuthStore.getState().setAuth('access-1', null, 900, user);
    const { sessionId, sessionEpoch } = useAuthStore.getState();

    peer.post({ type: 'logout', sessionId });
    await settle();

    expect(useAuthStore.getState()).toMatchObject({ token: null, sessionId: null, user: null });
    expect(useAuthStore.getState().sessionEpoch).toBe(sessionEpoch + 1);
  });

  it('abandons an in-flight refresh when another tab logs out', async () => {
    let signal: AbortSignal | undefined;
    vi.mocked(refreshAccessToken).mockImplementationOnce((_token, abortSignal) => {
      signal = abortSignal;
      return new Promise(() => {});
    });
    useAuthStore.getState().setAuth('access-1', null, 900, user);
    void tryRefresh();
    await vi.waitFor(() => expect(signal).toBeDefined());

    peer.post({ type: 'logout', sessionId: useAuthStore.getState().sessionId });
    await settle();

    expect(signal?.aborted).toBe(true);
  });

  it('ignores a logout for a session this tab has already replaced', async () => {
    useAuthStore.getState().setAuth('access-2', null, 900, user);

    peer.post({ type: 'logout', sessionId: 'an-older-session' });
    await settle();

    expect(useAuthStore.getState().token).toBe('access-2');
  });

  it('takes over a session another tab signed in, through the shared cookie', async () => {
    useAuthStore.getState().setAuth('old-access', null, 900, user);
    vi.mocked(refreshAccessToken).mockResolvedValueOnce(issued('adopted'));

    peer.post({ type: 'login', sessionId: 'peer-session' });
    await settle();

    expect(vi.mocked(refreshAccessToken).mock.calls[0][0]).toBeNull();
    expect(useAuthStore.getState()).toMatchObject({ token: 'adopted', sessionId: 'peer-session' });
  });

  it('announces sign-in and logout with the session id alone', async () => {
    useAuthStore.getState().setAuth('access-secret', null, 900, user);
    const { sessionId } = useAuthStore.getState();
    useAuthStore.getState().logout();
    await settle();

    expect(peer.received).toEqual([
      { type: 'login', sessionId },
      { type: 'logout', sessionId },
    ]);
  });

  it('announces nothing for a body-token session, which only lives in its tab', async () => {
    useAuthStore.getState().setAuth('access-1', 'refresh-1', 900, user);
    useAuthStore.getState().logout();
    await settle();

    expect(peer.received).toEqual([]);
  });

  it('keeps the embedded viewer out of other tabs\' sessions', async () => {
    window.history.replaceState({}, '', '/m/share-token?embed=true');

    peer.post({ type: 'login', sessionId: 'peer-session' });
    await settle();

    expect(refreshAccessToken).not.toHaveBeenCalled();
    expect(useAuthStore.getState().sessionId).toBeNull();
  });
});
