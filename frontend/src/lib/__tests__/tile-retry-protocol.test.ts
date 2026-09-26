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
  expect(fetcher).toHaveBeenLastCalledWith(url, expect.objectContaining({ headers: request.headers, signal: controller.signal }));
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
