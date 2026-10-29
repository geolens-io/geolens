import { ApiError, apiFetch } from '../client';
import { __resetAggregatePacingForTests, AGGREGATE_STARTS_PER_WINDOW, fetchAggregate } from '../aggregate';

vi.mock('../client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

function deferred() {
  let resolve!: (value: unknown) => void;
  const promise = new Promise((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const rateLimited = (retryAfterMs?: number) => {
  const error = new ApiError('slow down', 429, '10 per 1 second');
  if (retryAfterMs) error.retryAfterMs = retryAfterMs;
  return error;
};

beforeEach(() => {
  apiFetchMock.mockReset();
  __resetAggregatePacingForTests();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('fetchAggregate', () => {
  it('sends the embed token and keeps at most two requests in flight', async () => {
    const pending = [deferred(), deferred(), deferred()];
    let next = 0;
    apiFetchMock.mockImplementation(() => pending[next++].promise as never);

    const results = [1, 2, 3].map(() => fetchAggregate('ds-1', { op: 'count' }, { embedToken: 'embed-abc' }));
    await vi.waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(2));
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/datasets/ds-1/aggregate/',
      expect.objectContaining({
        method: 'POST',
        headers: { 'X-Embed-Token': 'embed-abc' },
        body: JSON.stringify({ op: 'count' }),
      }),
    );

    pending[0].resolve('first');
    await expect(results[0]).resolves.toBe('first');
    await vi.waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(3));
    pending[1].resolve('second');
    pending[2].resolve('third');
    await expect(Promise.all(results)).resolves.toEqual(['first', 'second', 'third']);
  });

  it('drops a queued request whose caller gave up', async () => {
    const pending = [deferred(), deferred()];
    let next = 0;
    apiFetchMock.mockImplementation(() => pending[next++].promise as never);

    const running = [fetchAggregate('ds-1', { op: 'count' }), fetchAggregate('ds-1', { op: 'count' })];
    const controller = new AbortController();
    const queued = fetchAggregate('ds-1', { op: 'count' }, { signal: controller.signal });
    controller.abort();
    await expect(queued).rejects.toBeDefined();

    pending[0].resolve('a');
    pending[1].resolve('b');
    await Promise.all(running);
    expect(apiFetchMock).toHaveBeenCalledTimes(2);
  });

  it('keeps a 50-widget burst to eight starts in every one-second window', async () => {
    vi.useFakeTimers({ now: 10_000 });
    const starts: number[] = [];
    apiFetchMock.mockImplementation(async () => {
      starts.push(Date.now());
      return 'ok' as never;
    });

    const all = Promise.all(Array.from({ length: 50 }, () => fetchAggregate('ds-1', { op: 'count' })));
    await vi.advanceTimersByTimeAsync(10_000);
    await all;

    expect(starts).toHaveLength(50);
    // The first eight go out at once; after that no second holds more than eight.
    expect(starts.slice(0, AGGREGATE_STARTS_PER_WINDOW).every((start) => start === 10_000)).toBe(true);
    for (const start of starts) {
      const inWindow = starts.filter((other) => other >= start && other < start + 1000);
      expect(inWindow.length).toBeLessThanOrEqual(AGGREGATE_STARTS_PER_WINDOW);
    }
  });

  it('pauses every request after a rate-limit refusal for its Retry-After', async () => {
    vi.useFakeTimers({ now: 10_000 });
    const starts: number[] = [];
    let refused = false;
    apiFetchMock.mockImplementation(async () => {
      starts.push(Date.now());
      if (!refused) {
        refused = true;
        throw rateLimited(2000);
      }
      return 'ok' as never;
    });

    const all = Promise.all([1, 2, 3].map(() => fetchAggregate('ds-1', { op: 'count' })));
    await vi.advanceTimersByTimeAsync(5000);
    await expect(all).resolves.toEqual(['ok', 'ok', 'ok']);

    // The second request had already started when the first was refused; nothing starts in the pause after.
    const refusedAt = starts[0];
    const later = starts.slice(2);
    expect(later.every((start) => start >= refusedAt + 2000)).toBe(true);
    expect(starts).toHaveLength(4);
  });

  it('retries a busy refusal soon, without pausing the page', async () => {
    vi.useFakeTimers({ now: 10_000 });
    const starts: number[] = [];
    let refused = false;
    apiFetchMock.mockImplementation(async () => {
      starts.push(Date.now());
      if (!refused) {
        refused = true;
        throw new ApiError('busy', 429, { code: 'query_busy', message: 'busy' });
      }
      return 'ok' as never;
    });

    const all = Promise.all([1, 2].map(() => fetchAggregate('ds-1', { op: 'count' })));
    await vi.advanceTimersByTimeAsync(1000);
    await expect(all).resolves.toEqual(['ok', 'ok']);
    expect(starts[1] - starts[0]).toBeLessThan(1000);
    expect(starts[2] - starts[0]).toBeLessThan(1000);
  });

  it('gives up after a few refusals', async () => {
    vi.useFakeTimers({ now: 10_000 });
    apiFetchMock.mockImplementation(async () => {
      throw rateLimited();
    });
    const result = fetchAggregate('ds-1', { op: 'count' });
    const settled = expect(result).rejects.toMatchObject({ status: 429 });
    await vi.advanceTimersByTimeAsync(10_000);
    await settled;
    expect(apiFetchMock).toHaveBeenCalledTimes(4);
  });
});
