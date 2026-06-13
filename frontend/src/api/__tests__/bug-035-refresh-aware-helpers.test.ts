// BUG-035: AI stream + download/export helpers must use the refresh-aware
// fetch pipeline (proactive expiry refresh + 401→tryRefresh→retry) instead of a
// bare fetch with a possibly-stale JWT. Pre-fix these helpers issued a raw
// fetch() and hard-failed with a 401 when the token had expired during a long
// idle; post-fix they transparently refresh and retry like every other request.
import { streamGenerateMap } from '@/api/maps';
import { exportAuditLogs } from '@/api/admin';
import { downloadExport } from '@/api/datasets';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('@/api/auth', () => ({
  refreshAccessToken: vi.fn(),
}));

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function streamingResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Unauthorized',
    body,
    headers: new Headers(),
    json: () => Promise.resolve({ detail: 'unauthorized' }),
  } as unknown as Response;
}

function blobResponse(status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Unauthorized',
    headers: new Headers(),
    blob: () => Promise.resolve(new Blob(['data'])),
    json: () => Promise.resolve({ detail: 'unauthorized' }),
  } as unknown as Response;
}

async function drain<T>(gen: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const ev of gen) out.push(ev);
  return out;
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ token: 'tok', refreshToken: 'r', expiresAt: null, user: null });
  // jsdom lacks the DOM download plumbing; stub what authenticatedDownload uses.
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:url');
  globalThis.URL.revokeObjectURL = vi.fn();
});

describe('BUG-035: streamGenerateMap is refresh-aware', () => {
  it('proactively refreshes when the token is within 30s of expiry before opening the stream', async () => {
    const { refreshAccessToken } = await import('@/api/auth');
    const mockRefresh = vi.mocked(refreshAccessToken);
    mockRefresh.mockResolvedValueOnce({
      access_token: 'fresh-token',
      refresh_token: 'r2',
      token_type: 'bearer',
      expires_in: 900,
    });
    // expiresAt is in the past → proactive-refresh branch fires.
    useAuthStore.setState({ token: 'stale', refreshToken: 'r', expiresAt: Date.now() - 1000 });

    mockFetch.mockResolvedValueOnce(
      streamingResponse(['event: done\r\n', 'data: {"type":"done"}\r\n', '\r\n']),
    );

    await drain(streamGenerateMap({ prompt: 'p' }));

    expect(mockRefresh).toHaveBeenCalledWith('r');
    // The stream request carried the refreshed token, not the stale one.
    const headers: Headers = mockFetch.mock.calls[0][1].headers;
    expect(headers.get('Authorization')).toBe('Bearer fresh-token');
  });

  it('retries the stream after a 401 by refreshing the token', async () => {
    const { refreshAccessToken } = await import('@/api/auth');
    const mockRefresh = vi.mocked(refreshAccessToken);
    mockRefresh.mockResolvedValueOnce({
      access_token: 'retry-token',
      refresh_token: 'r2',
      token_type: 'bearer',
      expires_in: 900,
    });

    mockFetch
      .mockResolvedValueOnce(streamingResponse([], 401))
      .mockResolvedValueOnce(
        streamingResponse(['event: done\r\n', 'data: {"type":"done"}\r\n', '\r\n']),
      );

    const events = await drain(streamGenerateMap({ prompt: 'p' }));

    expect(mockRefresh).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(events).toHaveLength(1);
    const retryHeaders: Headers = mockFetch.mock.calls[1][1].headers;
    expect(retryHeaders.get('Authorization')).toBe('Bearer retry-token');
  });
});

describe('BUG-035: exportAuditLogs is refresh-aware', () => {
  it('retries the export after a 401 by refreshing the token', async () => {
    const { refreshAccessToken } = await import('@/api/auth');
    vi.mocked(refreshAccessToken).mockResolvedValueOnce({
      access_token: 'export-token',
      refresh_token: 'r2',
      token_type: 'bearer',
      expires_in: 900,
    });

    mockFetch
      .mockResolvedValueOnce(blobResponse(401))
      .mockResolvedValueOnce(blobResponse(200));

    await exportAuditLogs('csv');

    expect(mockFetch).toHaveBeenCalledTimes(2);
    const retryHeaders: Headers = mockFetch.mock.calls[1][1].headers;
    expect(retryHeaders.get('Authorization')).toBe('Bearer export-token');
  });
});

describe('BUG-035: downloadExport is refresh-aware', () => {
  it('retries the download after a 401 by refreshing the token', async () => {
    const { refreshAccessToken } = await import('@/api/auth');
    vi.mocked(refreshAccessToken).mockResolvedValueOnce({
      access_token: 'dl-token',
      refresh_token: 'r2',
      token_type: 'bearer',
      expires_in: 900,
    });
    const appendChild = vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n);
    const removeChild = vi.spyOn(document.body, 'removeChild').mockImplementation((n) => n);

    mockFetch
      .mockResolvedValueOnce(blobResponse(401))
      .mockResolvedValueOnce(blobResponse(200));

    await downloadExport('ds-1', 'geojson', 'out.geojson');

    expect(mockFetch).toHaveBeenCalledTimes(2);
    const retryHeaders: Headers = mockFetch.mock.calls[1][1].headers;
    expect(retryHeaders.get('Authorization')).toBe('Bearer dl-token');

    appendChild.mockRestore();
    removeChild.mockRestore();
  });
});
