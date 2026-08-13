/**
 * fix(#1472 review): dataset attribution through the builder sync path.
 *
 * The builder has no explicit <AttributionControl> to hand `customAttribution`
 * to, so it credits through MapLibre's native source-level `attribution` — the
 * field MVT-05 declared on SyncLayerInput and left unfed until #1472. These
 * pin both halves: that `toSyncInput` copies `dataset_attribution` off the API
 * response at all, and that the value survives to the MapLibre source spec for
 * every layer kind the builder renders (vector, raster, raster-dem).
 */
import { describe, expect, it, vi } from 'vitest';
import { syncLayersToMap, toSyncInput } from '../map-sync';
import type { TileToken } from '@/api/tiles';
import type { MapLayerResponse } from '@/types/api';

vi.mock('@/lib/tile-utils', () => ({
  getMvtSourceLayerName: (table: string) => `data.${table}`,
  buildSignedTileUrl: vi.fn(() => '/tiles/mock/{z}/{x}/{y}.pbf'),
  buildClusterTileUrl: vi.fn(() => '/tiles/clusters/mock/{z}/{x}/{y}.pbf'),
}));

const SWISSTOPO = '© swisstopo — swissALTI3D';

const VECTOR_TOKEN: TileToken = {
  kind: 'vector',
  sig: 'mock',
  exp: 9999999999,
  scope: 'test',
  expires_in: 3600,
};

const RASTER_TOKEN: TileToken = {
  kind: 'raster',
  tile_url: '/raster-tiles/ds-1/tiles/{z}/{x}/{y}.png',
  sig: 'mock',
  exp: 9999999999,
  scope: 'test',
  expires_in: 3600,
  bounds: [-10, -10, 10, 10],
  minzoom: 0,
  maxzoom: 18,
  tile_size: 256,
  format: 'png',
} as unknown as TileToken;

function makeMockMap() {
  const sources = new Map<string, { type: string }>();
  const layerIds = new Set<string>();

  return {
    getSource: vi.fn((id: string) => sources.get(id) ?? null),
    addSource: vi.fn((id: string, spec: { type: string }) => {
      sources.set(id, { ...spec });
    }),
    removeSource: vi.fn((id: string) => { sources.delete(id); }),
    addLayer: vi.fn((layer: { id: string }) => { layerIds.add(layer.id); }),
    getLayer: vi.fn((id: string) => layerIds.has(id) ? { id } : null),
    removeLayer: vi.fn((id: string) => { layerIds.delete(id); }),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getPaintProperty: vi.fn(),
    getFilter: vi.fn().mockReturnValue(null),
    setFilter: vi.fn(),
    setLayerZoomRange: vi.fn(),
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({ layers: Array.from(layerIds).map((id) => ({ id })) })),
    moveLayer: vi.fn(),
  } as unknown as import('maplibre-gl').Map;
}

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_table_name: 'alti3d',
    dataset_geometry_type: 'MultiPolygon',
    dataset_extent_bbox: null,
    opacity: 1,
    visible: true,
    paint: { 'fill-color': '#2255aa' },
    layout: {},
    filter: null,
    dataset_attribution: SWISSTOPO,
    ...overrides,
  } as unknown as MapLayerResponse;
}

/** Sync one layer and return the source spec it created. */
function syncAndReadSourceSpec(
  layer: MapLayerResponse,
  token: TileToken,
): Record<string, unknown> {
  const map = makeMockMap();
  syncLayersToMap(
    map,
    [toSyncInput(layer)],
    new Map<string, TileToken>([['ds-1', token]]),
    undefined,
    { current: new Set() },
    { current: '' },
  );
  return (map.addSource as ReturnType<typeof vi.fn>).mock.calls[0][1] as Record<
    string,
    unknown
  >;
}

describe('dataset attribution through the builder sync path (#1472)', () => {
  it('copies dataset_attribution onto the sync input', () => {
    expect(toSyncInput(makeLayer()).attribution).toBe(SWISSTOPO);
  });

  it('nulls the sync input when the dataset requires no credit', () => {
    expect(toSyncInput(makeLayer({ dataset_attribution: null })).attribution).toBeNull();
  });

  it('reaches the vector source spec', () => {
    const spec = syncAndReadSourceSpec(makeLayer(), VECTOR_TOKEN);
    expect(spec.type).toBe('vector');
    expect(spec.attribution).toBe(SWISSTOPO);
  });

  it('reaches the raster source spec', () => {
    const spec = syncAndReadSourceSpec(
      makeLayer({ layer_type: 'raster_geolens', dataset_record_type: 'raster_dataset' }),
      RASTER_TOKEN,
    );
    expect(spec.type).toBe('raster');
    expect(spec.attribution).toBe(SWISSTOPO);
  });

  it('reaches the raster-dem source spec', () => {
    const spec = syncAndReadSourceSpec(
      makeLayer({
        is_dem: true,
        layer_type: 'raster_geolens',
        dataset_record_type: 'raster_dataset',
        style_config: { render_mode: 'hillshade' },
      }),
      RASTER_TOKEN,
    );
    expect(spec.type).toBe('raster-dem');
    expect(spec.attribution).toBe(SWISSTOPO);
  });

  it('omits attribution entirely when the dataset requires no credit', () => {
    const spec = syncAndReadSourceSpec(
      makeLayer({ dataset_attribution: null }),
      VECTOR_TOKEN,
    );
    expect(spec).not.toHaveProperty('attribution');
  });
});
