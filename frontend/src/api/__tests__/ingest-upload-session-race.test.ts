import { useAuthStore } from '@/stores/auth-store';
import { abortInflightRefresh, ApiError, onSessionExpired } from '@/api/client';
import { uploadFile } from '@/api/ingest';
import type { TokenResponse, UserResponse } from '@/types/api';

// An upload acts only on the session it started under: once a logout or another
// sign-in replaces it, the upload never refreshes, resends under or ends the new one.

const mockRefresh = vi.fn<(refreshToken: string | null, signal?: AbortSignal) => Promise<TokenResponse>>();
const mockRevokeCurrentSession = vi.fn<(token: string) => Promise<void>>();
const mockLogoutSession = vi.fn<() => Promise<void>>();
vi.mock('@/api/auth', () => ({
  refreshAccessToken: (refreshToken: string | null, signal?: AbortSignal) => mockRefresh(refreshToken, signal),
  revokeCurrentSession: (token: string) => mockRevokeCurrentSession(token),
  logoutSession: () => mockLogoutSession(),
}));

class FakeXHR {
  static sent: FakeXHR[] = [];
  status = 0;
  responseText = '';
  headers: Record<string, string> = {};
  upload = { onprogress: null as unknown };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  open() {}
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send() {
    FakeXHR.sent.push(this);
  }
  respond(status: number, body: string) {
    this.status = status;
    this.responseText = body;
    this.onload?.();
  }
}

const userA = { id: 'a', username: 'a', roles: ['editor'] } as unknown as UserResponse;
const userB = { id: 'b', username: 'b', roles: ['editor'] } as unknown as UserResponse;

async function nextSend(count: number) {
  await vi.waitFor(() => expect(FakeXHR.sent).toHaveLength(count));
  return FakeXHR.sent[count - 1];
}

describe('upload across a session change', () => {
  let expired: ReturnType<typeof vi.fn<() => void>>;
  let unregister: () => void;

  beforeEach(() => {
    vi.clearAllMocks();
    FakeXHR.sent = [];
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    mockRevokeCurrentSession.mockResolvedValue(undefined);
    mockLogoutSession.mockResolvedValue(undefined);
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

  it('neither refreshes, resends nor ends a newer sign-in when the old upload 401s', async () => {
    const pending = uploadFile(new File(['x'], 'a.csv'));
    const first = await nextSend(1);
    expect(first.headers.Authorization).toBe('Bearer access-a');

    useAuthStore.getState().logout();
    useAuthStore.getState().setAuth('access-b', 'refresh-b', 900, userB);
    mockRefresh.mockRejectedValue(new ApiError('unauthorized', 401));
    first.respond(401, '{"detail":"Not authenticated"}');

    await expect(pending).rejects.toMatchObject({ status: 401, unconfirmed: true });
    expect(mockRefresh).not.toHaveBeenCalled();
    expect(FakeXHR.sent).toHaveLength(1);
    expect(expired).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe('access-b');
    expect(useAuthStore.getState().user).toEqual(userB);
  });

  it('does not send under a sign-in that replaced the session during its refresh', async () => {
    useAuthStore.setState({ expiresAt: Date.now() + 5_000 });
    let finishRefresh!: (tokens: TokenResponse) => void;
    mockRefresh.mockImplementationOnce(() => new Promise((resolve) => { finishRefresh = resolve; }));

    const pending = uploadFile(new File(['x'], 'a.csv'));
    await vi.waitFor(() => expect(mockRefresh).toHaveBeenCalledTimes(1));
    useAuthStore.getState().logout();
    useAuthStore.getState().setAuth('access-b', 'refresh-b', 900, userB);
    finishRefresh({ access_token: 'access-a2', refresh_token: 'refresh-a2', token_type: 'bearer', expires_in: 900 });

    await expect(pending).rejects.toMatchObject({ status: 401, unconfirmed: true });
    expect(FakeXHR.sent).toHaveLength(0);
    expect(useAuthStore.getState().token).toBe('access-b');
  });

  it('refreshes and resends once within the same session', async () => {
    mockRefresh.mockResolvedValueOnce({
      access_token: 'access-a2',
      refresh_token: 'refresh-a2',
      token_type: 'bearer',
      expires_in: 900,
    });

    const pending = uploadFile(new File(['x'], 'a.csv'));
    (await nextSend(1)).respond(401, '{"detail":"expired"}');
    const retry = await nextSend(2);
    expect(retry.headers.Authorization).toBe('Bearer access-a2');
    retry.respond(201, '{"job_id":"job-1"}');

    await expect(pending).resolves.toEqual({ job_id: 'job-1' });
    expect(mockRefresh).toHaveBeenCalledExactlyOnceWith('refresh-a', expect.any(AbortSignal));
    expect(useAuthStore.getState().token).toBe('access-a2');
  });
});
