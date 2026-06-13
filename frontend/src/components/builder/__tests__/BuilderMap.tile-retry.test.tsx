import { describe, it, expect, vi, beforeEach } from 'vitest';
import { resignVectorSourceForRetry } from '@/components/builder/BuilderMap';
import { getSourceIdForLayer } from '@/components/builder/map-sync';
import type { MapLayerResponse } from '@/types/api';
import type { TileToken } from '@/api/tiles';

// GUARD-03 / BLDR-TILE-RACE coverage: the extracted re-sign helper must re-issue
// setTiles exactly once for a recoverable vector 401/403 (vector source + present
// token) and return false (no setTiles) for the non-recoverable cases (raster
// source / missing token / non-vector source) so the caller falls through to the
// existing auth-error toast. Mock the signing functions so the URL is deterministic
// and the call can be counted — same approach as map-sync.tile-refresh.test.ts.
vi.mock('@/lib/tile-utils', () => ({
  buildSignedTileUrl: vi.fn(
    (table: string, t: { sig: string } | null) => `/api/tiles/data.${table}/{z}/{x}/{y}.pbf?sig=${t?.sig ?? ''}`,
  ),
  buildClusterTileUrl: vi.fn(
    (table: string, t: { sig: string } | null) => `/api/tiles/clusters/data.${table}/{z}/{x}/{y}.pbf?sig=${t?.sig ?? ''}`,
  ),
}));

vi.mock('@/lib/env', () => ({
  getEnvConfig: () => ({ TILE_BASE_URL: undefined }),
}));

Object.defineProperty(window, 'location', {
  value: { origin: 'http://localhost:8080' },
  writable: true,
});

type MockSource = { type: string; setTiles?: ReturnType<typeof vi.fn> };

function createMockMap(sources: Record<string, MockSource>) {
  return {
    getSource: vi.fn((id: string) => sources[id] ?? null),
  } as unknown as import('maplibre-gl').Map;
}

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-x',
    dataset_id: 'ds-x',
    dataset_table_name: 'parcels',
    visible: true,
    style_config: null,
    ...(overrides as object),
  } as unknown as MapLayerResponse;
}

function makeVectorToken(): TileToken {
  return { kind: 'vector', sig: 'fresh-sig', exp: 9999999999, scope: 'test', expires_in: 3600 } as unknown as TileToken;
}

function makeRasterToken(): TileToken {
  return { kind: 'raster', tile_url: '/api/raster-tiles/x/{z}/{x}/{y}.png', tile_size: 256 } as unknown as TileToken;
}

describe('resignVectorSourceForRetry (GUARD-03 / BLDR-TILE-RACE)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('re-signs a vector source ONCE and returns true when a token is present (recoverable race)', () => {
    const layer = makeLayer();
    const sourceId = getSourceIdForLayer(layer);
    const setTiles = vi.fn();
    const map = createMockMap({ [sourceId]: { type: 'vector', setTiles } });
    const tokenMap = new Map<string, TileToken>([[layer.dataset_id, makeVectorToken()]]);

    const result = resignVectorSourceForRetry(map, sourceId, [layer], tokenMap, null);

    expect(result).toBe(true);
    expect(setTiles).toHaveBeenCalledTimes(1);
    expect(setTiles).toHaveBeenCalledWith([expect.stringContaining('sig=fresh-sig')]);
  });

  it('returns false WITHOUT calling setTiles when the source is raster (falls through to toast)', () => {
    const layer = makeLayer();
    const sourceId = getSourceIdForLayer(layer);
    const setTiles = vi.fn();
    // Raster token + raster source: not re-signed by this path.
    const map = createMockMap({ [sourceId]: { type: 'raster', setTiles } });
    const tokenMap = new Map<string, TileToken>([[layer.dataset_id, makeRasterToken()]]);

    const result = resignVectorSourceForRetry(map, sourceId, [layer], tokenMap, null);

    expect(result).toBe(false);
    expect(setTiles).not.toHaveBeenCalled();
  });

  it('returns false WITHOUT calling setTiles when no token is present for the failing source', () => {
    const layer = makeLayer();
    const sourceId = getSourceIdForLayer(layer);
    const setTiles = vi.fn();
    const map = createMockMap({ [sourceId]: { type: 'vector', setTiles } });
    const tokenMap = new Map<string, TileToken>(); // empty — no token yet

    const result = resignVectorSourceForRetry(map, sourceId, [layer], tokenMap, null);

    expect(result).toBe(false);
    expect(setTiles).not.toHaveBeenCalled();
  });

  it('returns false when no layer matches the failing sourceId', () => {
    const layer = makeLayer();
    const sourceId = getSourceIdForLayer(layer);
    const setTiles = vi.fn();
    const map = createMockMap({ [sourceId]: { type: 'vector', setTiles } });
    const tokenMap = new Map<string, TileToken>([[layer.dataset_id, makeVectorToken()]]);

    const result = resignVectorSourceForRetry(map, 'source-unknown', [layer], tokenMap, null);

    expect(result).toBe(false);
    expect(setTiles).not.toHaveBeenCalled();
  });
});
