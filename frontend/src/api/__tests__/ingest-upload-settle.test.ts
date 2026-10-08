import { useAuthStore } from '@/stores/auth-store';
import { abortInflightRefresh, ApiError } from '@/api/client';
import { uploadFile } from '@/api/ingest';
import { clearUploadBatch, removeUploadSessionEntry, startUploadEntry } from '@/api/upload-session';

const mockRefresh = vi.fn();
vi.mock('@/api/auth', () => ({
  refreshAccessToken: (...args: unknown[]) => mockRefresh(...args),
  revokeCurrentSession: vi.fn(async () => {}),
  logoutSession: vi.fn(async () => {}),
}));

class FakeXHR {
  static sent: FakeXHR[] = [];
  status = 0;
  responseText = '';
  aborted = false;
  upload: { onprogress: ((e: unknown) => void) | null; onload: (() => void) | null } = {
    onprogress: null,
    onload: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  open() {}
  setRequestHeader() {}
  send() {
    FakeXHR.sent.push(this);
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
  respond(status: number, body: string) {
    this.status = status;
    this.responseText = body;
    this.onload?.();
  }
}

const file = () => new File(['x'], 'a.geojson');

async function settleOf(p: Promise<unknown>): Promise<{ ok: boolean; value: unknown }> {
  return p.then(
    (value) => ({ ok: true, value }),
    (value) => ({ ok: false, value }),
  );
}

describe('direct-POST upload settles exactly once', () => {
  beforeEach(() => {
    FakeXHR.sent = [];
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    useAuthStore.setState({ token: null, expiresAt: null });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    abortInflightRefresh();
    mockRefresh.mockReset();
  });

  it('an already-aborted signal rejects without sending', async () => {
    const abort = new AbortController();
    abort.abort();
    const result = await settleOf(uploadFile(file(), undefined, null, abort.signal));
    expect(result.ok).toBe(false);
    expect((result.value as DOMException).name).toBe('AbortError');
    expect(FakeXHR.sent).toHaveLength(0);
  });

  it('a caller abort cancels the request and rejects once, ignoring later events', async () => {
    const abort = new AbortController();
    const p = settleOf(uploadFile(file(), undefined, null, abort.signal));
    await vi.waitFor(() => expect(FakeXHR.sent).toHaveLength(1));
    const xhr = FakeXHR.sent[0];
    abort.abort();
    xhr.respond(200, '{"job_id":"j"}');
    xhr.onerror?.();
    const result = await p;
    expect(xhr.aborted).toBe(true);
    expect(result.ok).toBe(false);
    expect((result.value as DOMException).name).toBe('AbortError');
  });

  it('a stalled upload times out with a timeout error, and progress postpones it', async () => {
    vi.useFakeTimers();
    const p = settleOf(uploadFile(file()));
    await vi.advanceTimersByTimeAsync(0);
    const xhr = FakeXHR.sent[0];
    await vi.advanceTimersByTimeAsync(100_000);
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 2 });
    await vi.advanceTimersByTimeAsync(100_000);
    expect(xhr.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(30_000);
    const result = await p;
    expect(xhr.aborted).toBe(true);
    expect(result.ok).toBe(false);
    const err = result.value as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.message).toBe('The request took too long. Try again.');
    xhr.respond(200, '{}');
  });

  it('waits for server processing after the body is sent, up to the response deadline', async () => {
    vi.useFakeTimers();
    const p = settleOf(uploadFile(file()));
    await vi.advanceTimersByTimeAsync(0);
    const xhr = FakeXHR.sent[0];
    xhr.upload.onload?.();
    await vi.advanceTimersByTimeAsync(600_000);
    expect(xhr.aborted).toBe(false);
    xhr.respond(200, '{"job_id":"j"}');
    expect(await p).toEqual({ ok: true, value: { job_id: 'j' } });
  });

  it('a cancel while a shared token refresh is pending rejects without waiting for it', async () => {
    useAuthStore.setState({ token: 'old', expiresAt: Date.now() + 1_000 });
    mockRefresh.mockImplementation(
      (_token: unknown, refreshSignal?: AbortSignal) =>
        new Promise((_, reject) => {
          refreshSignal?.addEventListener('abort', () => reject(new Error('refresh aborted')));
        }),
    );
    const abort = new AbortController();
    const p = settleOf(uploadFile(file(), undefined, null, abort.signal));
    await vi.waitFor(() => expect(mockRefresh).toHaveBeenCalled());
    abort.abort();
    const result = await p;
    expect(result.ok).toBe(false);
    expect((result.value as DOMException).name).toBe('AbortError');
    expect(FakeXHR.sent).toHaveLength(0);
  });

  it('a browser timeout event rejects once as a timeout', async () => {
    const p = settleOf(uploadFile(file()));
    await vi.waitFor(() => expect(FakeXHR.sent).toHaveLength(1));
    const xhr = FakeXHR.sent[0];
    xhr.ontimeout?.();
    xhr.onerror?.();
    const result = await p;
    expect((result.value as ApiError).message).toBe('The request took too long. Try again.');
  });

  it('a network error rejects once as a network failure', async () => {
    const p = settleOf(uploadFile(file()));
    await vi.waitFor(() => expect(FakeXHR.sent).toHaveLength(1));
    const xhr = FakeXHR.sent[0];
    xhr.onerror?.();
    xhr.respond(200, '{}');
    const result = await p;
    expect(result.ok).toBe(false);
    expect((result.value as ApiError).message).toBe('Network unavailable. Check your connection.');
  });

  it('a 401 retry settles once, and an abort during the retry rejects as an abort', async () => {
    useAuthStore.setState({ token: 'old', expiresAt: Date.now() + 3_600_000 });
    mockRefresh.mockResolvedValue({
      access_token: 'new',
      refresh_token: 'r',
      expires_in: 3600,
      token_type: 'bearer',
    });
    const abort = new AbortController();
    const p = settleOf(uploadFile(file(), undefined, null, abort.signal));
    await vi.waitFor(() => expect(FakeXHR.sent).toHaveLength(1));
    FakeXHR.sent[0].respond(401, '{}');
    await vi.waitFor(() => expect(FakeXHR.sent).toHaveLength(2));
    const retry = FakeXHR.sent[1];
    abort.abort();
    FakeXHR.sent[0].respond(200, '{}');
    retry.respond(200, '{}');
    const result = await p;
    expect(FakeXHR.sent).toHaveLength(2);
    expect(result.ok).toBe(false);
    expect((result.value as DOMException).name).toBe('AbortError');
  });

  it('a 401 retry that succeeds resolves once', async () => {
    useAuthStore.setState({ token: 'old', expiresAt: Date.now() + 3_600_000 });
    mockRefresh.mockResolvedValue({
      access_token: 'new',
      refresh_token: 'r',
      expires_in: 3600,
      token_type: 'bearer',
    });
    const p = settleOf(uploadFile(file()));
    await vi.waitFor(() => expect(FakeXHR.sent).toHaveLength(1));
    FakeXHR.sent[0].respond(401, '{}');
    await vi.waitFor(() => expect(FakeXHR.sent).toHaveLength(2));
    FakeXHR.sent[1].respond(200, '{"job_id":"j"}');
    FakeXHR.sent[0].onerror?.();
    const result = await p;
    expect(result).toEqual({ ok: true, value: { job_id: 'j' } });
  });

  it('dismissing an uploading entry aborts its request, and clearing the batch aborts the rest', async () => {
    startUploadEntry('e1', file(), false);
    startUploadEntry('e2', file(), false);
    await vi.waitFor(() => expect(FakeXHR.sent).toHaveLength(2));
    removeUploadSessionEntry('e1');
    expect(FakeXHR.sent.map((x) => x.aborted)).toEqual([true, false]);
    clearUploadBatch();
    expect(FakeXHR.sent.map((x) => x.aborted)).toEqual([true, true]);
  });
});
