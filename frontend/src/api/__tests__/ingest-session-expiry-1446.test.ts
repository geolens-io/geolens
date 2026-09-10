import { useAuthStore } from '@/stores/auth-store';
import { abortInflightRefresh, ApiError, onSessionExpired } from '@/api/client';

// fix(#1446): the XHR upload path cleared the store directly on a terminal 401,
// skipping the single signed-out prompt every other surface shows (fix(#628)).
// It now routes through notifySessionExpired.

const mockLogoutSession = vi.fn<() => Promise<void>>();
const mockRefresh = vi.fn<() => Promise<never>>();
vi.mock('@/api/auth', () => ({
  refreshAccessToken: () => mockRefresh(),
  logoutSession: () => mockLogoutSession(),
}));

class FakeXHR {
  static queue: number[] = [];
  status = 0;
  responseText = '{}';
  upload = { onprogress: null as unknown };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  open() {}
  setRequestHeader() {}
  send() {
    this.status = FakeXHR.queue.shift() ?? 500;
    this.responseText = '{"detail":"nope"}';
    queueMicrotask(() => this.onload?.());
  }
}

describe('upload auth failure (fix #1446)', () => {
  let handler: ReturnType<typeof vi.fn<() => void>>;
  let unregister: () => void;

  beforeEach(() => {
    vi.clearAllMocks();
    mockLogoutSession.mockResolvedValue(undefined);
    mockRefresh.mockRejectedValue(new ApiError('unauthorized', 401));
    handler = vi.fn<() => void>();
    unregister = onSessionExpired(handler);
    (globalThis as unknown as { XMLHttpRequest: unknown }).XMLHttpRequest = FakeXHR;
  });

  afterEach(() => {
    unregister();
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
    // fix(#2038): the transient refresh back-off is module state; end signed out.
    abortInflightRefresh();
  });

  it('clears local state and prompts once when an upload 401s terminally', async () => {
    const { uploadFile } = await import('@/api/ingest');
    FakeXHR.queue = [401];
    useAuthStore.setState({
      token: 'stale-access',
      refreshToken: null,
      expiresAt: Date.now() + 120_000,
    });

    await expect(
      uploadFile(new File(['x'], 'a.geojson')),
    ).rejects.toMatchObject({ status: 401 });

    // fix(#2038): local teardown only — /auth/logout/ revokes every device.
    expect(mockLogoutSession).not.toHaveBeenCalled();
    expect(handler).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().token).toBeNull();
  });

  // fix(#2038): the upload door shares the rule — only a rejected refresh
  // credential ends the session.
  it('keeps the session when the upload 401s but the refresh failed transiently', async () => {
    const { uploadFile } = await import('@/api/ingest');
    mockRefresh.mockRejectedValue(new ApiError('service unavailable', 503));
    FakeXHR.queue = [401];
    useAuthStore.setState({
      token: 'live-access',
      refreshToken: null,
      expiresAt: Date.now() + 120_000,
    });

    await expect(
      uploadFile(new File(['x'], 'a.geojson')),
    ).rejects.toMatchObject({ status: 401 });

    expect(mockLogoutSession).not.toHaveBeenCalled();
    expect(handler).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe('live-access');
  });

  it('does not revoke on an anonymous upload 401 (no session to end)', async () => {
    const { uploadFile } = await import('@/api/ingest');
    FakeXHR.queue = [401];
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null });

    await expect(
      uploadFile(new File(['x'], 'a.geojson')),
    ).rejects.toMatchObject({ status: 401 });

    expect(mockLogoutSession).not.toHaveBeenCalled();
    expect(handler).not.toHaveBeenCalled();
  });
});
