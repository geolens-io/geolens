import { uploadChunks } from './_presignedUpload';

/**
 * fix(review #1800 P2 round 3): the per-part PUT moved from `fetch` to XHR
 * (see _presignedUpload.ts for why — `fetch` exposes no upload-progress
 * signal, so a wall-clock AbortSignal.timeout() could not tell a genuine
 * stall from a slow-but-live transfer). This mock stands in for
 * XMLHttpRequest the same way the old suite stubbed `fetch`.
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

  // Test helper: complete this request with a status and headers.
  respond(status: number, headers: Record<string, string> = {}) {
    this.status = status;
    this.headers = headers;
    this.onload?.();
  }

  // Test helper: fire a network-layer failure (no response at all).
  networkError() {
    this.onerror?.();
  }
}

function stubXHR() {
  MockXHR.instances = [];
  vi.stubGlobal('XMLHttpRequest', MockXHR);
}

function okResponse(instance: MockXHR, etag: string) {
  instance.respond(200, { ETag: etag });
}

function errorResponse(instance: MockXHR, status: number) {
  instance.respond(status);
}

describe('uploadChunks', () => {
  beforeEach(() => {
    stubXHR();
  });

  it('returns ETags in order for a 3-chunk upload', async () => {
    const file = new Blob(['aaaabbbbccc']); // 11 bytes
    const urls = ['https://s3/u1', 'https://s3/u2', 'https://s3/u3'];
    const promise = uploadChunks(urls, file, 4);

    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(1));
    okResponse(MockXHR.instances[0], '"etag-1"');
    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(2));
    okResponse(MockXHR.instances[1], '"etag-2"');
    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(3));
    okResponse(MockXHR.instances[2], '"etag-3"');

    await expect(promise).resolves.toEqual(['"etag-1"', '"etag-2"', '"etag-3"']);
    expect(MockXHR.instances.map((x) => x.method)).toEqual(['PUT', 'PUT', 'PUT']);
    expect(MockXHR.instances.map((x) => x.url)).toEqual(urls);
  });

  it('PUTs the correct slice of the input file as each chunk body', async () => {
    // 11 bytes; partSize=4 yields slices "aaaa", "bbbb", "ccc".
    const file = new Blob(['aaaabbbbccc']);
    const urls = ['u1', 'u2', 'u3'];
    const promise = uploadChunks(urls, file, 4);

    for (let i = 0; i < 3; i++) {
      await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(i + 1));
      okResponse(MockXHR.instances[i], `"e${i + 1}"`);
    }
    await promise;

    const bodies = await Promise.all(
      MockXHR.instances.map((x) => (x.body as Blob).text()),
    );
    expect(bodies).toEqual(['aaaa', 'bbbb', 'ccc']);
  });

  it('throws when any chunk PUT returns a non-2xx status', async () => {
    // First two parts succeed, third part fails with 403.
    const file = new Blob(['aaaabbbbccc']);
    const urls = ['u1', 'u2', 'u3'];
    const promise = uploadChunks(urls, file, 4);
    // Suppress the unhandled-rejection window between the throw below and
    // the awaited assertion — same rejection, just observed twice.
    promise.catch(() => {});

    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(1));
    okResponse(MockXHR.instances[0], '"e1"');
    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(2));
    okResponse(MockXHR.instances[1], '"e2"');
    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(3));
    errorResponse(MockXHR.instances[2], 403);

    await expect(promise).rejects.toThrow(/Upload part 3 failed \(HTTP 403\)/);
  });

  it('reports cumulative progress (0–1) after each chunk completes', async () => {
    const file = new Blob(['aaaabbbbccc']); // 11 bytes, partSize 4 → 4/11, 8/11, 11/11
    const progress: number[] = [];
    const promise = uploadChunks(['u1', 'u2', 'u3'], file, 4, (p) => progress.push(p));

    for (let i = 0; i < 3; i++) {
      await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(i + 1));
      okResponse(MockXHR.instances[i], `"e${i + 1}"`);
    }
    await promise;

    expect(progress).toEqual([4 / 11, 8 / 11, 1]);
  });

  // fix(#1778): an empty-string ETag used to reach the backend's
  // complete_multipart_upload, which mapped it to a "session may have
  // expired" 502 — advice that can never fix a bucket CORS misconfiguration
  // (ExposeHeaders must list ETag for a cross-origin PUT to expose it at
  // all). Fail fast instead, naming the real cause.
  it('throws naming the missing bucket CORS config when ETag header is absent', async () => {
    const file = new Blob(['xyz']);
    const promise = uploadChunks(['u1'], file, 4);
    promise.catch(() => {});

    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(1));
    // 2xx with no ETag header at all.
    MockXHR.instances[0].respond(200);

    await expect(promise).rejects.toThrow(/ETag/);
  });

  // fix(review #1800 P2 round 3): S3 already accepted this part (a 2xx PUT
  // response) before the missing ETag was noticed — throwing straight away
  // left the multipart upload open server-side, consuming storage on every
  // retry, because the completion endpoint's own abort path was never
  // reached (uploadChunks never got far enough to call it). onMissingEtag
  // lets the caller trigger that same abort path (its "complete with no
  // parts" call) before the configuration error propagates.
  it('calls onMissingEtag exactly once, before throwing, when ETag is absent', async () => {
    const file = new Blob(['xyz']);
    const onMissingEtag = vi.fn().mockResolvedValue(undefined);
    const promise = uploadChunks(['u1'], file, 4, undefined, { onMissingEtag });
    promise.catch(() => {});

    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(1));
    MockXHR.instances[0].respond(200);

    await expect(promise).rejects.toThrow(/ETag/);
    expect(onMissingEtag).toHaveBeenCalledTimes(1);
    expect(onMissingEtag).toHaveBeenCalledWith();
  });

  // The cleanup call is best-effort: its own failure must not mask the
  // real (missing-ETag) error, and must not be retried as if it were the
  // part PUT itself.
  it('still throws the missing-ETag error when onMissingEtag itself rejects', async () => {
    const file = new Blob(['xyz']);
    const onMissingEtag = vi.fn().mockRejectedValue(new Error('abort endpoint down'));
    const promise = uploadChunks(['u1'], file, 4, undefined, { onMissingEtag });
    promise.catch(() => {});

    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(1));
    MockXHR.instances[0].respond(200);

    await expect(promise).rejects.toThrow(/ETag/);
    expect(onMissingEtag).toHaveBeenCalledTimes(1);
  });

  it('stops on the first failing chunk and surfaces its 1-indexed part number', async () => {
    const file = new Blob(['aaaabbbb']);
    const promise = uploadChunks(['u1', 'u2'], file, 4);
    promise.catch(() => {});

    await vi.waitFor(() => expect(MockXHR.instances).toHaveLength(1));
    errorResponse(MockXHR.instances[0], 400);

    await expect(promise).rejects.toThrow(/Upload part 1 failed \(HTTP 400\)/);
    // Did not attempt the second part.
    expect(MockXHR.instances).toHaveLength(1);
  });
});
