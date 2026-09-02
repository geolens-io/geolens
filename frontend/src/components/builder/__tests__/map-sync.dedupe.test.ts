import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  syncLayersToMap,
  getSourceIdForLayer,
  type SyncLayerInput,
} from '@/components/builder/map-sync';
import type { TileToken, VectorTileToken } from '@/api/tiles';

vi.mock('@/lib/tile-utils', () => ({
  getMvtSourceLayerName: (table: string, prefix = 'data') => `${prefix}.${table}`,
  buildSignedTileUrl: vi.fn(
    (table: string) => `/tiles/${table}/{z}/{x}/{y}.pbf`,
  ),
  buildClusterTileUrl: vi.fn(() => '/tiles/clusters/mock/{z}/{x}/{y}.pbf'),
}));

Object.defineProperty(window, 'location', {
  value: { origin: 'http://localhost:8080' },
  writable: true,
});

function createMockMap() {
  const sources = new Map<string, { type: string; tiles?: string[] }>();
  // fix(#1778): record the whole spec, not just the id. getStyle() on a real
  // map reports each layer's `source`, and the orphan prune reads it to tell a
  // managed data layer apart from a basemap layer that happens to be named
  // `layer-*`.
  const layerSpecs = new Map<string, { id: string; source?: string }>();
  const layerIds = new Set<string>();
  return {
    getSource: vi.fn((id: string) => sources.get(id) ?? null),
    addSource: vi.fn((id: string, spec: { type: string; tiles?: string[] }) => {
      sources.set(id, spec);
    }),
    removeSource: vi.fn((id: string) => {
      sources.delete(id);
    }),
    addLayer: vi.fn((layer: { id: string; source?: string }) => {
      layerIds.add(layer.id);
      layerSpecs.set(layer.id, layer);
    }),
    getLayer: vi.fn((id: string) => (layerIds.has(id) ? { id } : null)),
    removeLayer: vi.fn((id: string) => {
      layerIds.delete(id);
      layerSpecs.delete(id);
    }),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getPaintProperty: vi.fn(),
    getLayoutProperty: vi.fn(),
    setFilter: vi.fn(),
    getFilter: vi.fn().mockReturnValue(null),
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({
      layers: Array.from(layerIds).map((id) => layerSpecs.get(id) ?? { id }),
    })),
    moveLayer: vi.fn(),
    setLayerZoomRange: vi.fn(),
  } as unknown as import('maplibre-gl').Map;
}

function makeVectorToken(
  overrides: Partial<VectorTileToken> = {},
): VectorTileToken {
  return {
    kind: 'vector',
    sig: 'abc',
    exp: 9999999999,
    scope: 'test',
    expires_in: 3600,
    ...overrides,
  };
}

function makeLayer(overrides: Partial<SyncLayerInput> = {}): SyncLayerInput {
  return {
    id: 'layer-x',
    dataset_id: 'ds-x',
    dataset_table_name: 'shared_table',
    dataset_geometry_type: 'Polygon',
    opacity: 1,
    visible: true,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    style_config: null,
    is_dem: false,
    is_3d: false,
    feature_count: 100,
    ...overrides,
  };
}

describe('getSourceIdForLayer (dedupe contract)', () => {
  it('two non-cluster vector layers on the same dataset_table_name resolve to the same source id', () => {
    const a = makeLayer({ id: 'a', dataset_table_name: 'reefs' });
    const b = makeLayer({ id: 'b', dataset_table_name: 'reefs' });
    expect(getSourceIdForLayer(a)).toBe(getSourceIdForLayer(b));
    expect(getSourceIdForLayer(a)).toBe('source-data-reefs');
  });

  it('two non-cluster vector layers on DIFFERENT datasets resolve to different source ids', () => {
    const a = makeLayer({ id: 'a', dataset_table_name: 'reefs' });
    const b = makeLayer({ id: 'b', dataset_table_name: 'countries' });
    expect(getSourceIdForLayer(a)).not.toBe(getSourceIdForLayer(b));
  });

  it('cluster layer + non-cluster layer on the SAME dataset get DIFFERENT source ids', () => {
    const cluster = makeLayer({
      id: 'c1',
      dataset_table_name: 'points',
      dataset_geometry_type: 'POINT',
      style_config: { render_mode: 'cluster' } as SyncLayerInput['style_config'],
      feature_count: 100,
    });
    const nonCluster = makeLayer({
      id: 'n1',
      dataset_table_name: 'points',
      dataset_geometry_type: 'POINT',
      style_config: null,
      feature_count: 100,
    });
    expect(getSourceIdForLayer(cluster)).not.toBe(getSourceIdForLayer(nonCluster));
    // Non-cluster goes through the dedupe path
    expect(getSourceIdForLayer(nonCluster)).toBe('source-data-points');
  });

  it('cluster layer keeps a per-layer source id (preserves cluster radius/minPoints scoping)', () => {
    const cluster = makeLayer({
      id: 'c1',
      dataset_table_name: 'points',
      dataset_geometry_type: 'POINT',
      style_config: { render_mode: 'cluster' } as SyncLayerInput['style_config'],
      feature_count: 100,
    });
    const cluster2 = makeLayer({
      id: 'c2',
      dataset_table_name: 'points',
      dataset_geometry_type: 'POINT',
      style_config: { render_mode: 'cluster' } as SyncLayerInput['style_config'],
      feature_count: 100,
    });
    // Cluster layers MUST stay per-layer (different radius/minPoints per layer).
    expect(getSourceIdForLayer(cluster)).not.toBe(getSourceIdForLayer(cluster2));
    expect(getSourceIdForLayer(cluster)).toContain('c1');
    expect(getSourceIdForLayer(cluster2)).toContain('c2');
  });

  it('layer without dataset_table_name falls back to per-layer source id', () => {
    const layer = makeLayer({ id: 'orphan', dataset_table_name: '' });
    expect(getSourceIdForLayer(layer)).toBe('source-orphan');
  });
});

describe('syncLayersToMap dedupes addSource by dataset_table_name', () => {
  let map: ReturnType<typeof createMockMap>;
  let managedSourcesRef: { current: Set<string> };

  beforeEach(() => {
    map = createMockMap();
    managedSourcesRef = { current: new Set() };
  });

  it('renders against the tenant-prefixed MVT source layer', () => {
    const layer = makeLayer({ dataset_table_name: 'parcels' });
    const tokenMap = new Map<string, TileToken>([
      ['ds-x', makeVectorToken()],
    ]);
    const prefix = 'data_t_12345678_1234_1234_1234_123456789abc';

    syncLayersToMap(
      map,
      [layer],
      tokenMap,
      undefined,
      managedSourcesRef,
      { current: '' },
      undefined,
      { mvtSourceLayerPrefix: prefix },
    );

    const renderedLayer = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls
      .map(([spec]) => spec as Record<string, unknown>)
      .find((spec) => spec.id === 'layer-layer-x');
    expect(renderedLayer?.['source-layer']).toBe(`${prefix}.parcels`);
  });

  it('4 non-cluster vector layers across 2 datasets fires addSource exactly 2 times (M for M, not N)', () => {
    const layers: SyncLayerInput[] = [
      makeLayer({ id: 'l1', dataset_id: 'ds-reefs', dataset_table_name: 'reefs' }),
      makeLayer({ id: 'l2', dataset_id: 'ds-reefs', dataset_table_name: 'reefs' }),
      makeLayer({ id: 'l3', dataset_id: 'ds-countries', dataset_table_name: 'countries' }),
      makeLayer({ id: 'l4', dataset_id: 'ds-countries', dataset_table_name: 'countries' }),
    ];
    const tokenMap = new Map<string, TileToken>([
      ['ds-reefs', makeVectorToken()],
      ['ds-countries', makeVectorToken()],
    ]);

    syncLayersToMap(map, layers, tokenMap, undefined, managedSourcesRef, {
      current: '',
    });

    expect(map.addSource).toHaveBeenCalledTimes(2);
    const callArgs = (map.addSource as ReturnType<typeof vi.fn>).mock.calls.map(
      (c) => c[0],
    );
    expect(callArgs).toContain('source-data-reefs');
    expect(callArgs).toContain('source-data-countries');
  });

  it('removeStaleSourcesAndLayers does NOT remove a shared source while a layer in desiredSources still references it', () => {
    // First sync: 2 layers on same dataset
    const layers: SyncLayerInput[] = [
      makeLayer({ id: 'l1', dataset_id: 'ds-reefs', dataset_table_name: 'reefs' }),
      makeLayer({ id: 'l2', dataset_id: 'ds-reefs', dataset_table_name: 'reefs' }),
    ];
    const tokenMap = new Map<string, TileToken>([
      ['ds-reefs', makeVectorToken()],
    ]);

    syncLayersToMap(map, layers, tokenMap, undefined, managedSourcesRef, {
      current: '',
    });

    // Sanity: one source added
    expect(map.addSource).toHaveBeenCalledTimes(1);
    (map.removeSource as ReturnType<typeof vi.fn>).mockClear();

    // Second sync: drop one layer; the source is STILL referenced by the other.
    syncLayersToMap(
      map,
      [layers[1]],
      tokenMap,
      undefined,
      managedSourcesRef,
      { current: '' },
    );

    // The shared source must NOT be removed — the other layer still uses it.
    expect(map.removeSource).not.toHaveBeenCalledWith('source-data-reefs');
  });

  // fix(#1778): the source prune is keyed on the SOURCE, and the whole prune
  // body sits behind `if (desiredSources.has(sourceId)) continue`. Under the
  // SF-04 dedupe the deleted layer's source is still desired by its sibling, so
  // nothing ever reclaimed the orphan layer rows. They kept rendering with no
  // stack row, no legend entry and no way to remove them short of a reload.
  // Counterfactual: on main the three assertions below all find the layers
  // still present.
  it('removes the layer rows of a deleted layer whose deduped source is still shared', () => {
    const layers: SyncLayerInput[] = [
      makeLayer({ id: 'l1', dataset_id: 'ds-reefs', dataset_table_name: 'reefs' }),
      makeLayer({ id: 'l2', dataset_id: 'ds-reefs', dataset_table_name: 'reefs' }),
    ];
    const tokenMap = new Map<string, TileToken>([['ds-reefs', makeVectorToken()]]);

    syncLayersToMap(map, layers, tokenMap, undefined, managedSourcesRef, { current: '' });
    expect(map.getLayer('layer-l1')).toBeTruthy();

    // The companions the delete path would normally have swept, left behind
    // because removePerLayerCompanions ran mid-style-swap.
    map.addLayer({ id: 'layer-l1-outline', type: 'line', source: 'source-data-reefs' } as never);
    map.addLayer({ id: 'layer-l1-label', type: 'symbol', source: 'source-data-reefs' } as never);

    syncLayersToMap(map, [layers[1]], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.getLayer('layer-l1')).toBeNull();
    expect(map.getLayer('layer-l1-outline')).toBeNull();
    expect(map.getLayer('layer-l1-label')).toBeNull();
    // The surviving sibling and the shared source are untouched.
    expect(map.getLayer('layer-l2')).toBeTruthy();
    expect(map.removeSource).not.toHaveBeenCalledWith('source-data-reefs');
  });

  it('leaves style layers outside the managed layer- namespace alone', () => {
    const layers: SyncLayerInput[] = [
      makeLayer({ id: 'l1', dataset_id: 'ds-reefs', dataset_table_name: 'reefs' }),
    ];
    const tokenMap = new Map<string, TileToken>([['ds-reefs', makeVectorToken()]]);
    syncLayersToMap(map, layers, tokenMap, undefined, managedSourcesRef, { current: '' });

    map.addLayer({ id: 'water', type: 'fill', source: 'openmaptiles' } as never);
    map.addLayer({ id: 'ephemeral-result-fill', type: 'fill', source: 'ephemeral' } as never);

    syncLayersToMap(map, layers, tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.getLayer('water')).toBeTruthy();
    expect(map.getLayer('ephemeral-result-fill')).toBeTruthy();
  });

  it('two non-cluster vector layers on the SAME dataset BOTH render (2nd layer on a shared source still gets added)', () => {
    // Regression for #311: casing modeled as a second line layer on one dataset.
    // The shared source is created by the first layer; the second layer hits the
    // "source already exists" branch — which previously only ran syncPaint, and
    // syncPaint no-ops when the layer is missing (line-adapter.ts:212). Result:
    // the casing layer was never added on a fresh load.
    const layers: SyncLayerInput[] = [
      makeLayer({
        id: 'base',
        dataset_id: 'ds-rivers',
        dataset_table_name: 'rivers',
        dataset_geometry_type: 'LineString',
      }),
      makeLayer({
        id: 'casing',
        dataset_id: 'ds-rivers',
        dataset_table_name: 'rivers',
        dataset_geometry_type: 'LineString',
      }),
    ];
    const tokenMap = new Map<string, TileToken>([
      ['ds-rivers', makeVectorToken()],
    ]);

    syncLayersToMap(map, layers, tokenMap, undefined, managedSourcesRef, {
      current: '',
    });

    // One shared source, but BOTH layers must be on the map.
    expect(map.addSource).toHaveBeenCalledTimes(1);
    expect(map.getLayer('layer-base')).toBeTruthy();
    expect(map.getLayer('layer-casing')).toBeTruthy();
  });

  it('removeStaleSourcesAndLayers DOES remove a source when no remaining layer references it', () => {
    const layers: SyncLayerInput[] = [
      makeLayer({ id: 'l1', dataset_id: 'ds-reefs', dataset_table_name: 'reefs' }),
    ];
    const tokenMap = new Map<string, TileToken>([
      ['ds-reefs', makeVectorToken()],
    ]);

    syncLayersToMap(map, layers, tokenMap, undefined, managedSourcesRef, {
      current: '',
    });
    expect(map.addSource).toHaveBeenCalledTimes(1);
    (map.removeSource as ReturnType<typeof vi.fn>).mockClear();

    // Drop the only consumer.
    syncLayersToMap(map, [], tokenMap, undefined, managedSourcesRef, {
      current: '',
    });

    expect(map.removeSource).toHaveBeenCalledWith('source-data-reefs');
  });
});

describe('vector source spec (MVT-03 / MVT-06)', () => {
  it('creates the vector source with minzoom 0, maxzoom 14, and dataset bounds', () => {
    const map = createMockMap();
    const managedSourcesRef = { current: new Set<string>() };
    const layer = makeLayer({
      id: 'l1',
      dataset_id: 'ds-1',
      dataset_table_name: 'parcels',
      bounds: [-10, -5, 10, 5],
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeVectorToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    const call = (map.addSource as ReturnType<typeof vi.fn>).mock.calls.find(
      ([id]) => id === 'source-data-parcels',
    );
    expect(call).toBeDefined();
    const spec = call![1] as { type: string; minzoom: number; maxzoom: number; bounds?: number[] };
    expect(spec.type).toBe('vector');
    // MVT-03: z0 world data is requested (minzoom 0, not 1).
    expect(spec.minzoom).toBe(0);
    // MVT-04 over-fetch: overzoom above the data maxzoom instead of refetching to z22.
    expect(spec.maxzoom).toBe(14);
    // MVT-06: bounds threaded from the dataset spatial extent.
    expect(spec.bounds).toEqual([-10, -5, 10, 5]);
  });

  it('omits bounds when the dataset has no usable extent', () => {
    const map = createMockMap();
    const managedSourcesRef = { current: new Set<string>() };
    const layer = makeLayer({ id: 'l1', dataset_id: 'ds-1', dataset_table_name: 'nobounds', bounds: null });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeVectorToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    const call = (map.addSource as ReturnType<typeof vi.fn>).mock.calls.find(
      ([id]) => id === 'source-data-nobounds',
    );
    const spec = call![1] as { bounds?: number[] };
    expect(spec.bounds).toBeUndefined();
  });
});
