import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  syncLayersToMap,
  getSourceIdForLayer,
  type SyncLayerInput,
} from '@/components/builder/map-sync';
import type { TileToken, VectorTileToken } from '@/api/tiles';

vi.mock('@/lib/tile-utils', () => ({
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
  const layerIds = new Set<string>();
  return {
    getSource: vi.fn((id: string) => sources.get(id) ?? null),
    addSource: vi.fn((id: string, spec: { type: string; tiles?: string[] }) => {
      sources.set(id, spec);
    }),
    removeSource: vi.fn((id: string) => {
      sources.delete(id);
    }),
    addLayer: vi.fn((layer: { id: string }) => {
      layerIds.add(layer.id);
    }),
    getLayer: vi.fn((id: string) => (layerIds.has(id) ? { id } : null)),
    removeLayer: vi.fn((id: string) => {
      layerIds.delete(id);
    }),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getPaintProperty: vi.fn(),
    getLayoutProperty: vi.fn(),
    setFilter: vi.fn(),
    getFilter: vi.fn().mockReturnValue(null),
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({
      layers: Array.from(layerIds).map((id) => ({ id })),
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
