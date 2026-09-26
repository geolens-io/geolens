import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AJAXError } from 'maplibre-gl';
import { tileRetryProtocol } from '../tile-retry-protocol';
import { buildTileTransformRequest } from '../tile-utils';

vi.unmock('maplibre-gl');

const url = 'https://tiles.example/tiles/data.roads/0/0/0.pbf?sig=signature';
const request = { url: `geolens-tile://${url}`, headers: { 'X-Embed-Token': 'test-token' } };

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
  vi.spyOn(Math, 'random').mockReturnValue(0);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it.each(['2', 'Thu, 01 Jan 2026 00:00:02 GMT'])('honors Retry-After %s and preserves credentials and cache metadata', async (retryAfter) => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(new Response('', { status: 429, headers: { 'Retry-After': retryAfter } }))
    .mockResolvedValueOnce(new Response('tile', { headers: { 'Cache-Control': 'public, max-age=60' } }));
  vi.stubGlobal('fetch', fetcher);
  const controller = new AbortController();
  const result = tileRetryProtocol(request, controller);
  await vi.advanceTimersByTimeAsync(1999);
  expect(fetcher).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect((await result).cacheControl).toBe('public, max-age=60');
  expect(fetcher).toHaveBeenLastCalledWith(url, expect.objectContaining({ headers: request.headers, signal: expect.any(AbortSignal) }));
});

it('preserves the strong ETag for MapLibre tile revalidation', async () => {
  const etag = '"tile-content-digest"';
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('tile', {
    headers: { ETag: etag },
  })));

  const response = await tileRetryProtocol(request, new AbortController());

  expect(response.etag).toBe(etag);
});

it('stops after two retries', async () => {
  const fetcher = vi.fn().mockImplementation(() => Promise.resolve(new Response('', { status: 429, headers: { 'Retry-After': '0' } })));
  vi.stubGlobal('fetch', fetcher);
  const assertion = expect(tileRetryProtocol(request, new AbortController())).rejects.toMatchObject({ status: 429, url });
  await vi.runAllTimersAsync();
  await assertion;
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it.each([401, 403, 404, 503])('does not retry %s', async (status) => {
  const fetcher = vi.fn().mockResolvedValue(new Response('', { status }));
  vi.stubGlobal('fetch', fetcher);
  const error = await tileRetryProtocol(request, new AbortController()).catch((error: unknown) => error);
  expect(error).toBeInstanceOf(AJAXError);
  expect(error).toMatchObject({ status, url });
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it('does not retry earlier than a long server cooldown', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('', { status: 429, headers: { 'Retry-After': '120' } }));
  vi.stubGlobal('fetch', fetcher);
  await expect(tileRetryProtocol(request, new AbortController())).rejects.toMatchObject({ status: 429 });
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it('cancels a pending retry when MapLibre aborts the tile', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('', { status: 429 }));
  vi.stubGlobal('fetch', fetcher);
  const controller = new AbortController();
  const assertion = expect(tileRetryProtocol(request, controller)).rejects.toMatchObject({ name: 'AbortError' });
  await vi.advanceTimersByTimeAsync(0);
  controller.abort();
  await vi.runAllTimersAsync();
  await assertion;
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it.each(['', 'clusters/'])('transforms first-party %s tiles with embed credentials', (prefix) => {
  const path = `/api/tiles/${prefix}data.roads/0/0/0.pbf?sig=signature`;
  expect(buildTileTransformRequest({ embedToken: 'token' })(path)).toEqual({
    url: `geolens-tile://${window.location.origin}${path}`,
    headers: { 'X-Embed-Token': 'token' },
  });
});

it('leaves third-party tiles and unrelated resources alone', () => {
  const transform = buildTileTransformRequest();
  expect(transform(url)).toEqual({ url });
  expect(transform('/api/tiles/token/id/').url).toBe(`${window.location.origin}/api/tiles/token/id/`);
  expect(transform('pmtiles://https://example.test/map.pmtiles').url).toBe('pmtiles://https://example.test/map.pmtiles');
});

it('returns expired signed-token failures to the existing auth recovery handler', async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(new Response('', { status: 429, headers: { 'Retry-After': '2' } }))
    .mockResolvedValueOnce(new Response('', { status: 403 }));
  vi.stubGlobal('fetch', fetcher);
  const assertion = expect(tileRetryProtocol(request, new AbortController())).rejects.toMatchObject({ status: 403, url });
  await vi.runAllTimersAsync();
  await assertion;
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it('routes the configured cross-origin tile CDN through retry with embed credentials', () => {
  expect(buildTileTransformRequest({
    embedToken: 'token',
    getTileConfig: () => ({ cdn_base_url: 'https://tiles.example' }),
  })(url)).toEqual({ url: `geolens-tile://${url}`, headers: { 'X-Embed-Token': 'token' } });
});

it.each([0, 10])('drains sixty visible tiles with %s server slots initially occupied', async (initialLoad) => {
  let serverActive = initialLoad;
  let rejected = 0;
  if (initialLoad > 0) setTimeout(() => { serverActive = 0; }, 1000);
  vi.stubGlobal('fetch', vi.fn(async () => {
    if (serverActive >= 10) {
      rejected++;
      return new Response('', { status: 429, headers: { 'Retry-After': '2' } });
    }
    serverActive++;
    await new Promise((resolve) => setTimeout(resolve, 1000));
    serverActive--;
    return new Response('tile');
  }));

  const results = Promise.allSettled(Array.from({ length: 60 }, (_, index) =>
    tileRetryProtocol({ ...request, url: `${request.url}&tile=${index}` }, new AbortController()),
  ));
  await vi.runAllTimersAsync();

  if (initialLoad > 0) expect(rejected).toBeGreaterThan(0);
  expect((await results).filter((result) => result.status === 'fulfilled')).toHaveLength(60);
  expect(serverActive).toBe(0);
});

function holdTileFetches() {
  const fetcher = vi.fn((_url: string, options: RequestInit) => new Promise<Response>((_resolve, reject) => {
    const signal = options.signal!;
    signal.addEventListener('abort', () => reject(signal.reason), { once: true });
  }));
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}

it('removes a canceled queued tile and admits the next live tile when capacity frees', async () => {
  const fetcher = holdTileFetches();
  const controllers = Array.from({ length: 8 }, () => new AbortController());
  const results = controllers.map((controller, index) =>
    tileRetryProtocol({ ...request, url: `${request.url}&tile=${index}` }, controller).catch((error: unknown) => error),
  );
  await vi.advanceTimersByTimeAsync(0);
  expect(fetcher).toHaveBeenCalledTimes(6);
  controllers[6].abort();
  await expect(results[6]).resolves.toMatchObject({ name: 'AbortError' });
  controllers[0].abort();
  await vi.advanceTimersByTimeAsync(0);
  expect(fetcher).toHaveBeenCalledTimes(7);
  expect(fetcher).toHaveBeenLastCalledWith(`${url}&tile=7`, expect.anything());
  controllers.forEach((controller) => controller.abort());
  await Promise.all(results);

  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('next tile')));
  await expect(tileRetryProtocol(request, new AbortController())).resolves.toHaveProperty('data');
});

it('bounds queue size and returns canceled queue capacity immediately', async () => {
  const fetcher = holdTileFetches();
  const controllers = Array.from({ length: 518 }, () => new AbortController());
  const results = controllers.map((controller) => tileRetryProtocol(request, controller).catch((error: unknown) => error));
  await vi.advanceTimersByTimeAsync(0);
  expect(fetcher).toHaveBeenCalledTimes(6);
  await expect(tileRetryProtocol(request, new AbortController())).rejects.toMatchObject({ status: 429, url });
  controllers[6].abort();
  await results[6];
  const replacement = new AbortController();
  const replacementResult = tileRetryProtocol(request, replacement).catch((error: unknown) => error);
  replacement.abort();
  await expect(replacementResult).resolves.toMatchObject({ name: 'AbortError' });
  controllers.forEach((controller) => controller.abort());
  await Promise.all(results);
});

it('bounds queue and active waits with distinct timeout errors', async () => {
  const fetcher = holdTileFetches();
  const results = Array.from({ length: 7 }, () =>
    tileRetryProtocol(request, new AbortController()).catch((error: unknown) => error),
  );
  await vi.advanceTimersByTimeAsync(120_000);
  await expect(results[6]).resolves.toMatchObject({ status: 504, statusText: 'Tile request queue timed out', url });
  expect(fetcher).toHaveBeenCalledTimes(6);
  await vi.advanceTimersByTimeAsync(480_000);
  for (const result of results.slice(0, 6)) {
    await expect(result).resolves.toMatchObject({ status: 504, statusText: 'Tile request timed out', url });
  }
});
