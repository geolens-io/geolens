import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { uploadChunks } from '../_presignedUpload';

/**
 * fix(#438): DATA-02 — per-part retry and abort for presigned multipart uploads.
 * A single transient blip used to throw and discard every part already sent.
 */
describe('uploadChunks', () => {
  const file = new Blob([new Uint8Array(300)]); // 3 parts at partSize 100
  const urls = ['u1', 'u2', 'u3'];

  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  function okResponse(etag = 'etag') {
    return { ok: true, status: 200, headers: new Headers({ ETag: etag }) } as Response;
  }

  it('uploads every part and returns ETags in order', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse('e'));
    vi.stubGlobal('fetch', fetchMock);

    const result = await uploadChunks(urls, file, 100);
    expect(result).toEqual(['e', 'e', 'e']);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('retries a part that returns a transient 503, keeping earlier parts', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(okResponse()) // part 1 ok
      .mockResolvedValueOnce({ ok: false, status: 503, headers: new Headers() } as Response) // part 2 fails
      .mockResolvedValueOnce(okResponse()) // part 2 retry ok
      .mockResolvedValueOnce(okResponse()); // part 3 ok
    vi.stubGlobal('fetch', fetchMock);

    const promise = uploadChunks(urls, file, 100);
    await vi.runAllTimersAsync();
    await expect(promise).resolves.toHaveLength(3);
    // 3 parts + 1 retry = 4 fetches; part 1 was never re-sent.
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('gives up on a part after exhausting retries', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: false, status: 500, headers: new Headers() } as Response);
    vi.stubGlobal('fetch', fetchMock);

    const promise = uploadChunks(urls, file, 100, undefined, { maxRetries: 2 });
    const assertion = expect(promise).rejects.toThrow(/part 1 upload failed/);
    await vi.runAllTimersAsync();
    await assertion;
    // 1 initial + 2 retries on part 1.
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('does not retry a permanent 4xx', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: false, status: 403, headers: new Headers() } as Response);
    vi.stubGlobal('fetch', fetchMock);

    await expect(uploadChunks(urls, file, 100)).rejects.toThrow(/403/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('aborts before starting the next part when the signal fires', async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockImplementation(() => {
      controller.abort();
      return Promise.resolve(okResponse());
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      uploadChunks(urls, file, 100, undefined, { signal: controller.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' });
    // Part 1 ran; the abort check stops part 2 from starting.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
