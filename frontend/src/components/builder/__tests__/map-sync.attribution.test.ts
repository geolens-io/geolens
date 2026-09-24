// A dataset credit reaches the builder's sync input and the terrain DEM source.
import { describe, expect, it, vi } from 'vitest';
import { ensureRasterDemTerrainSource, toSyncInput } from '../map-sync';
import type { MapLayerResponse } from '@/types/api';

const SWISSTOPO = '© swisstopo — swissALTI3D';

function makeMockMap() {
  const sources = new Map<string, { type: string }>();
  return {
    getSource: vi.fn((id: string) => sources.get(id) ?? null),
    addSource: vi.fn((id: string, spec: { type: string }) => {
      sources.set(id, { ...spec });
    }),
    removeSource: vi.fn((id: string) => { sources.delete(id); }),
    setTerrain: vi.fn(),
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

describe('dataset attribution on the builder sync input', () => {
  it('copies dataset_attribution onto the sync input', () => {
    expect(toSyncInput(makeLayer()).attribution).toBe(SWISSTOPO);
  });

  it('nulls the sync input when the dataset requires no credit', () => {
    expect(toSyncInput(makeLayer({ dataset_attribution: null })).attribution).toBeNull();
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
