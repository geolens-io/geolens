import { abortInflightRefresh, apiFetch, onSessionExpired } from '@/api/client';
import { useAuthStore } from '@/stores/auth-store';
import { refreshAccessToken } from '@/api/auth';
import type { TokenResponse, UserResponse } from '@/types/api';

// A request acts only on the session it started under: once another sign-in
// replaces it, the request is not sent, refreshed, resent or allowed to sign out.

vi.mock('@/api/auth', () => ({
  refreshAccessToken: vi.fn(),
  revokeCurrentSession: vi.fn(() => Promise.resolve()),
  logoutSession: vi.fn(() => Promise.resolve()),
}));

const mockFetch = vi.fn();

function response(status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: () => Promise.resolve({ detail: 'x' }),
    headers: new Headers(),
  } as Response;
}

const userA = { id: 'a', username: 'a', roles: ['viewer'] } as unknown as UserResponse;
const userB = { id: 'b', username: 'b', roles: ['viewer'] } as unknown as UserResponse;

/** What another tab's write to the persisted session looks like here. */
function peerTabWrites(state: Record<string, unknown>) {
  void useAuthStore.persist.getOptions().storage?.setItem('geolens-auth', { state: state as never, version: 1 });
  window.dispatchEvent(new StorageEvent('storage', { key: 'geolens-auth' }));
}

function authorizationOf(call: unknown[]): string | null {
  return new Headers((call[1] as RequestInit).headers).get('Authorization');
}

describe('request across a session change', () => {
  let expired: ReturnType<typeof vi.fn<() => void>>;
  let unregister: () => void;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', mockFetch);
    expired = vi.fn<() => void>();
    unregister = onSessionExpired(expired);
    useAuthStore.getState().setAuth('access-a', 'refresh-a', 900, userA);
  });

  afterEach(() => {
    unregister();
    vi.unstubAllGlobals();
    useAuthStore.getState().logout();
    abortInflightRefresh();
  });

  it('leaves a sign-in made by another tab alone when the older request 401s', async () => {
    let answer!: (r: Response) => void;
    mockFetch.mockImplementationOnce(() => new Promise((resolve) => { answer = resolve; }));
    const pending = apiFetch('/datasets/');
    await vi.waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));

    const epoch = useAuthStore.getState().sessionEpoch;
    peerTabWrites({ token: 'access-b', expiresAt: Date.now() + 900_000, user: userB, sessionId: 'peer' });
    await vi.waitFor(() => expect(useAuthStore.getState().sessionEpoch).not.toBe(epoch));
    answer(response(401));

    await expect(pending).rejects.toMatchObject({ status: 401 });
    expect(refreshAccessToken).not.toHaveBeenCalled();
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(expired).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe('access-b');
  });

  it('does not send under a sign-in that replaced the session during its refresh', async () => {
    useAuthStore.setState({ expiresAt: Date.now() + 5_000 });
    let finishRefresh!: (tokens: TokenResponse) => void;
    vi.mocked(refreshAccessToken).mockImplementationOnce(
      () => new Promise((resolve) => { finishRefresh = resolve; }),
    );

    const pending = apiFetch('/maps/', { method: 'POST', body: '{}' });
    await vi.waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
    useAuthStore.getState().setAuth('access-b', 'refresh-b', 900, userB);
    finishRefresh({ access_token: 'access-a2', refresh_token: 'refresh-a2', token_type: 'bearer', expires_in: 900 });

    await expect(pending).rejects.toMatchObject({ status: 401, unconfirmed: true });
    expect(mockFetch).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe('access-b');
  });

  it('keeps a peer tab refresh of the same session', async () => {
    mockFetch.mockResolvedValueOnce(response(401)).mockResolvedValueOnce(response(200));
    vi.mocked(refreshAccessToken).mockResolvedValueOnce({
      access_token: 'access-a2',
      refresh_token: 'refresh-a2',
      token_type: 'bearer',
      expires_in: 900,
    });
    const { sessionId } = useAuthStore.getState();
    const epoch = useAuthStore.getState().sessionEpoch;
    peerTabWrites({ token: 'access-a1', refreshToken: 'refresh-a1', expiresAt: Date.now() + 900_000, user: userA, sessionId });
    await vi.waitFor(() => expect(useAuthStore.getState().token).toBe('access-a1'));
    expect(useAuthStore.getState().sessionEpoch).toBe(epoch);

    await expect(apiFetch('/datasets/')).resolves.toEqual({ detail: 'x' });
    expect(authorizationOf(mockFetch.mock.calls[1])).toBe('Bearer access-a2');
  });
});
