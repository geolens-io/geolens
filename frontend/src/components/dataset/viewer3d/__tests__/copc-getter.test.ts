import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { makeRangeGetter } from '../copc-getter';
import { MAX_LOAD_READS, MAX_RANGE_BYTES } from '../copc-limits';

const URL_PATH = '/api/datasets/d1/copc/a1/data.copc.laz';

function partial(length: number, headers: Record<string, string> = {}) {
  return new Response(new Uint8Array(length), { status: 206, headers });
}

describe('makeRangeGetter', () => {
  const datasetFetch = vi.fn();
  beforeEach(() => {
    datasetFetch.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it('asks for the inclusive byte range through the guarded fetch and returns the bytes', async () => {
    datasetFetch.mockResolvedValue(partial(10));
    const bytes = await makeRangeGetter(datasetFetch, URL_PATH, 1000)(100, 110);
    expect(bytes.byteLength).toBe(10);
    expect(datasetFetch).toHaveBeenCalledWith(URL_PATH, expect.objectContaining({ headers: { Range: 'bytes=100-109' } }));
  });

  it.each([
    ['a negative start', -1, 10],
    ['an empty range', 5, 5],
    ['a fractional offset', 0.5, 10],
    ['a non-finite end', 0, Number.POSITIVE_INFINITY],
    ['a range past the cap', 0, MAX_RANGE_BYTES + 1],
    ['a range past the recorded file size', 990, 1100],
  ])('refuses %s without a request', async (_label, begin, end) => {
    await expect(makeRangeGetter(datasetFetch, URL_PATH, 1000)(begin, end)).rejects.toThrow(/refused/);
    expect(datasetFetch).not.toHaveBeenCalled();
  });

  it('stops a load that exceeds its read budget, as a header with endless VLRs would drive', async () => {
    datasetFetch.mockImplementation(async () => partial(1));
    const getter = makeRangeGetter(datasetFetch, URL_PATH, null);
    for (let i = 0; i < MAX_LOAD_READS; i++) await getter(i, i + 1);
    await expect(getter(0, 1)).rejects.toThrow(/budget/);
  });

  it('requires a 206 of exactly the requested length', async () => {
    datasetFetch.mockResolvedValueOnce(new Response(new Uint8Array(10), { status: 200 }));
    await expect(makeRangeGetter(datasetFetch, URL_PATH, null)(0, 10)).rejects.toThrow(/answered 200/);
    datasetFetch.mockResolvedValueOnce(partial(9));
    await expect(makeRangeGetter(datasetFetch, URL_PATH, null)(0, 10)).rejects.toThrow(/wrong length/);
    datasetFetch.mockResolvedValueOnce(partial(10, { 'Content-Length': '99999999' }));
    await expect(makeRangeGetter(datasetFetch, URL_PATH, null)(0, 10)).rejects.toThrow(/larger than requested/);
  });

  it('backs off on 429, honouring Retry-After, then succeeds', async () => {
    datasetFetch
      .mockResolvedValueOnce(new Response('', { status: 429, headers: { 'Retry-After': '2' } }))
      .mockResolvedValueOnce(partial(4));
    const pending = makeRangeGetter(datasetFetch, URL_PATH, null)(0, 4);
    await vi.advanceTimersByTimeAsync(1900);
    expect(datasetFetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(200);
    await expect(pending).resolves.toHaveLength(4);
    expect(datasetFetch).toHaveBeenCalledTimes(2);
  });

  it('gives up after repeated 429s', async () => {
    datasetFetch.mockImplementation(async () => new Response('', { status: 429 }));
    const pending = makeRangeGetter(datasetFetch, URL_PATH, null)(0, 4);
    const assertion = expect(pending).rejects.toThrow(/answered 429/);
    await vi.advanceTimersByTimeAsync(60_000);
    await assertion;
  });

  it('runs at most four reads at once', async () => {
    let active = 0;
    let peak = 0;
    datasetFetch.mockImplementation(async () => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 10));
      active -= 1;
      return partial(1);
    });
    const getter = makeRangeGetter(datasetFetch, URL_PATH, null);
    const all = Promise.all(Array.from({ length: 12 }, (_, i) => getter(i, i + 1)));
    await vi.advanceTimersByTimeAsync(200);
    await all;
    expect(peak).toBe(4);
  });
});
