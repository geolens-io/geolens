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
import { ensureRasterDemTerrainSource, syncLayersToMap, toSyncInput } from '../map-sync';
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

/** Sync one layer with bounded GeoJSON data and return the source spec. */
function syncGeoJsonAndReadSourceSpec(
  layer: MapLayerResponse,
  geojson: GeoJSON.FeatureCollection,
): Record<string, unknown> {
  const map = makeMockMap();
  syncLayersToMap(
    map,
    [toSyncInput(layer)],
    new Map<string, TileToken>([['ds-1', VECTOR_TOKEN]]),
    undefined,
    { current: new Set() },
    { current: '' },
    new Map([[layer.id, geojson]]),
  );
  return (map.addSource as ReturnType<typeof vi.fn>).mock.calls[0][1] as Record<
    string,
    unknown
  >;
}

const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

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

// fix(#1472 review): the two GeoJSON source shapes shipped uncredited because
// the attribution lookup lived inside the vector-tile block they never reach.
describe('dataset attribution on the builder GeoJSON source paths (#1472)', () => {
  it('reaches the plain GeoJSON source a small 3D dataset uses', () => {
    const spec = syncGeoJsonAndReadSourceSpec(
      makeLayer({ is_3d: true, dataset_feature_count: 100 }),
      EMPTY_FC,
    );
    expect(spec.type).toBe('geojson');
    expect(spec.cluster).toBeUndefined();
    expect(spec.attribution).toBe(SWISSTOPO);
  });

  it('reaches the clustered GeoJSON source a bounded cluster layer uses', () => {
    const spec = syncGeoJsonAndReadSourceSpec(
      makeLayer({
        dataset_geometry_type: 'Point',
        style_config: { render_mode: 'cluster' },
        dataset_feature_count: 100,
      }),
      EMPTY_FC,
    );
    expect(spec.type).toBe('geojson');
    expect(spec.cluster).toBe(true);
    expect(spec.attribution).toBe(SWISSTOPO);
  });

  it('omits attribution on a GeoJSON source when no credit is required', () => {
    const spec = syncGeoJsonAndReadSourceSpec(
      makeLayer({ is_3d: true, dataset_feature_count: 100, dataset_attribution: null }),
      EMPTY_FC,
    );
    expect(spec.type).toBe('geojson');
    expect(spec).not.toHaveProperty('attribution');
  });
});

// fix(#1472 review): a terrain-mode DEM has no visible layer, so the attributed
// source its adapter built is unreferenced and MapLibre's `used` flag is false.
// The terrain source is counted through `usedForTerrain` instead, which makes it
// the only place a terrain-only DEM's credit can come from on the builder.
describe('dataset attribution on the terrain DEM source (#1472)', () => {
  it('puts the credit on the terrain source', () => {
    const map = makeMockMap();
    ensureRasterDemTerrainSource(map, '/raster-tiles/ds-1/tiles/{z}/{x}/{y}.png', {
      attribution: SWISSTOPO,
    });
    const spec = (map.addSource as ReturnType<typeof vi.fn>).mock.calls[0][1] as Record<
      string,
      unknown
    >;
    expect(spec.type).toBe('raster-dem');
    expect(spec.attribution).toBe(SWISSTOPO);
  });

  it('omits it when the DEM requires no credit', () => {
    const map = makeMockMap();
    ensureRasterDemTerrainSource(map, '/raster-tiles/ds-1/tiles/{z}/{x}/{y}.png', {
      attribution: null,
    });
    const spec = (map.addSource as ReturnType<typeof vi.fn>).mock.calls[0][1] as Record<
      string,
      unknown
    >;
    expect(spec).not.toHaveProperty('attribution');
  });
});
