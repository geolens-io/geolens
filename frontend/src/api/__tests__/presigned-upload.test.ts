import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { uploadChunks } from '../_presignedUpload';

/**
 * fix(#438): DATA-02 — per-part retry and abort for presigned multipart uploads.
 * A single transient blip used to throw and discard every part already sent.
 *
 * fix(review #1800 P2 round 3): the per-part PUT moved from `fetch` to XHR —
 * `fetch` exposes no upload-progress signal, so a wall-clock
 * AbortSignal.timeout() could not distinguish a genuine stall from a
 * slow-but-live transfer (a 10 MiB part at the backend's credited minimum
 * rate legitimately takes ~320s). This mock stands in for XMLHttpRequest
 * the same way the suite used to stub `fetch`, and drives
 * `upload.onprogress` explicitly so the inactivity-timeout tests below can
 * exercise both the "still resetting the timer" and "nothing resets it"
 * paths under fake timers.
 */
class MockXHR {
  static instances: MockXHR[] = [];

  method = '';
  url = '';
  status = 0;
  body: unknown = null;
  upload: { onprogress: ((e: unknown) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  aborted = false;
  private headers: Record<string, string> = {};

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
    MockXHR.instances.push(this);
  }

  send(body: unknown) {
    this.body = body;
  }

  abort() {
    this.aborted = true;
  }

  getResponseHeader(name: string): string | null {
    return this.headers[name] ?? null;
  }

  respond(status: number, headers: Record<string, string> = {}) {
    this.status = status;
    this.headers = headers;
    this.onload?.();
  }

  progress() {
    this.upload.onprogress?.({});
  }
}

function stubXHR() {
  MockXHR.instances = [];
  vi.stubGlobal('XMLHttpRequest', MockXHR);
}

function okResponse(instance: MockXHR, etag = 'etag') {
  instance.respond(200, { ETag: etag });
}

describe('uploadChunks', () => {
  const file = new Blob([new Uint8Array(300)]); // 3 parts at partSize 100
  const urls = ['u1', 'u2', 'u3'];

  beforeEach(() => {
    vi.useFakeTimers();
    stubXHR();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('uploads every part and returns ETags in order', async () => {
    const promise = uploadChunks(urls, file, 100);

    for (let i = 0; i < 3; i++) {
      await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(i + 1));
      okResponse(MockXHR.instances[i], 'e');
    }

    await expect(promise).resolves.toEqual(['e', 'e', 'e']);
    expect(MockXHR.instances).toHaveLength(3);
  });

  it('retries a part that returns a transient 503, keeping earlier parts', async () => {
    const promise = uploadChunks(urls, file, 100);

    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(1));
    okResponse(MockXHR.instances[0]); // part 1 ok
    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(2));
    MockXHR.instances[1].respond(503); // part 2 fails
    await vi.advanceTimersByTimeAsync(1000); // retry backoff
    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(3));
    okResponse(MockXHR.instances[2]); // part 2 retry ok
    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(4));
    okResponse(MockXHR.instances[3]); // part 3 ok

    await expect(promise).resolves.toHaveLength(3);
    // 3 parts + 1 retry = 4 PUTs; part 1 was never re-sent.
    expect(MockXHR.instances).toHaveLength(4);
  });

  it('gives up on a part after exhausting retries', async () => {
    const promise = uploadChunks(urls, file, 100, undefined, { maxRetries: 2 });
    promise.catch(() => {});

    // 1 initial + 2 retries on part 1, each failing 500.
    for (let i = 0; i < 3; i++) {
      await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(i + 1));
      MockXHR.instances[i].respond(500);
      if (i < 2) await vi.advanceTimersByTimeAsync(4000); // covers both backoffs
    }

    await expect(promise).rejects.toThrow(/Upload part 1 failed/);
    expect(MockXHR.instances).toHaveLength(3);
  });

  it('does not retry a permanent 4xx', async () => {
    const promise = uploadChunks(urls, file, 100);
    promise.catch(() => {});

    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(1));
    MockXHR.instances[0].respond(403);

    await expect(promise).rejects.toThrow(/403/);
    expect(MockXHR.instances).toHaveLength(1);
  });

  it('aborts before starting the next part when the signal fires', async () => {
    const controller = new AbortController();
    const promise = uploadChunks(urls, file, 100, undefined, { signal: controller.signal });
    promise.catch(() => {});

    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(1));
    controller.abort();
    okResponse(MockXHR.instances[0]);

    await expect(promise).rejects.toMatchObject({ name: 'AbortError' });
    // Part 1 ran; the abort check stops part 2 from starting.
    expect(MockXHR.instances).toHaveLength(1);
  });

  // fix(review #1800 P2 round 3): AbortSignal.timeout() was a WALL-CLOCK
  // deadline (300s flat), not a stall detector — a part actively
  // progressing past that deadline was aborted anyway, forever, on every
  // attempt. The inactivity timer must NOT fire as long as
  // upload.onprogress keeps arriving, however slowly, even well past the
  // old 300s figure.
  it('completes a slow-but-progressing part past the old 300s wall-clock figure', async () => {
    const promise = uploadChunks(['u1'], file, 100);
    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(1));
    const xhr = MockXHR.instances[0];

    // 8 progress events 45s apart (each under the 60s inactivity window,
    // resetting it every time) — 360s total, past the old flat deadline.
    for (let i = 0; i < 8; i++) {
      await vi.advanceTimersByTimeAsync(45_000);
      xhr.progress();
    }
    okResponse(xhr, 'slow-etag');

    await expect(promise).resolves.toEqual(['slow-etag']);
    expect(xhr.aborted).toBe(false);
  });

  // Pin: a part with no progress events for the inactivity window aborts
  // and is retried (a timeout is retriable — see _presignedUpload.ts).
  it('aborts a part that reports no progress for the inactivity window', async () => {
    const promise = uploadChunks(['u1'], file, 100);
    promise.catch(() => {});
    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(1));
    const stalled = MockXHR.instances[0];

    // No progress event at all — advance straight past the 60s window.
    await vi.advanceTimersByTimeAsync(60_000);

    expect(stalled.aborted).toBe(true);
    // Retriable: the loop starts a fresh XHR for the same part after the
    // backoff delay rather than giving up immediately.
    await vi.advanceTimersByTimeAsync(1000);
    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(2));
    okResponse(MockXHR.instances[1], 'retry-etag');

    await expect(promise).resolves.toEqual(['retry-etag']);
  });

  // fix(#1778): the retry loop only fires on a REJECTED fetch/XHR — a part
  // PUT that stalls on a half-open TCP connection never rejects on its
  // own, so it used to hang forever with no timeout and no way out.
  it('attaches an inactivity timer to every part even when the caller passes no signal', async () => {
    const promise = uploadChunks(['u1'], file, 100);
    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(1));
    const xhr = MockXHR.instances[0];

    // No progress, no caller signal — the inactivity timer alone must
    // still abort this part once the window elapses.
    await vi.advanceTimersByTimeAsync(60_000);
    expect(xhr.aborted).toBe(true);

    promise.catch(() => {});
  });
});
