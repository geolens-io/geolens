import { useAuthStore } from '@/stores/auth-store';
import { onSessionExpired } from '@/api/client';

// fix(#1446): the XHR upload path cleared the store directly on a terminal
// 401. Since the refresh credential became an httpOnly cookie, that leaves it
// and its server-side row alive while the client considers the user signed
// out. It also skipped the signed-out prompt every other surface shows
// (fix(#628)). It now routes through notifySessionExpired.

const mockLogoutSession = vi.fn<() => Promise<void>>();
vi.mock('@/api/auth', () => ({
  refreshAccessToken: vi.fn(() => Promise.reject(new Error('rate limited'))),
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
    handler = vi.fn<() => void>();
    unregister = onSessionExpired(handler);
    (globalThis as unknown as { XMLHttpRequest: unknown }).XMLHttpRequest = FakeXHR;
  });

  afterEach(() => {
    unregister();
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
  });

  it('revokes server-side and prompts once when an upload 401s terminally', async () => {
    const { uploadFile } = await import('@/api/ingest');
    // Both the original attempt and the post-refresh retry return 401.
    FakeXHR.queue = [401, 401];
    useAuthStore.setState({
      token: 'stale-access',
      refreshToken: null,
      expiresAt: Date.now() + 120_000,
    });

    await expect(
      uploadFile(new File(['x'], 'a.geojson')),
    ).rejects.toMatchObject({ status: 401 });

    expect(mockLogoutSession).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().token).toBeNull();
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
