import { describe, it, expect, vi } from 'vitest';
import {
  syncLayersToMap,
  getSourceIdForLayer,
  type SyncLayerInput,
} from '@/components/builder/map-sync';
import type { TileToken, VectorTileToken } from '@/api/tiles';

// buildSignedTileUrl embeds the requested `cols` so the tile URL changes exactly
// when the projected column set changes — the signal the existing-source refresh
// guard keys on.
vi.mock('@/lib/tile-utils', () => ({
  getMvtSourceLayerName: (table: string) => `data.${table}`,
  buildSignedTileUrl: vi.fn(
    (table: string, _t: unknown, _b: unknown, _u: unknown, cols?: string[] | null) =>
      `/tiles/${table}/{z}/{x}/{y}.pbf?cols=${(cols ?? []).slice().sort().join(',')}`,
  ),
  buildClusterTileUrl: vi.fn(() => '/tiles/clusters/mock/{z}/{x}/{y}.pbf'),
}));

Object.defineProperty(window, 'location', {
  value: { origin: 'http://localhost:8080' },
  writable: true,
});

function createMockMap() {
  const sources = new Map<string, { type: string; tiles?: string[]; setTiles?: ReturnType<typeof vi.fn> }>();
  const layerIds = new Set<string>();
  return {
    getSource: vi.fn((id: string) => sources.get(id) ?? null),
    addSource: vi.fn((id: string, spec: { type: string; tiles?: string[] }) => {
      // Vector sources expose setTiles in MapLibre — mirror that so the refresh
      // path under test can be exercised and counted.
      sources.set(id, spec.type === 'vector' ? { ...spec, setTiles: vi.fn() } : { ...spec });
    }),
    removeSource: vi.fn((id: string) => { sources.delete(id); }),
    addLayer: vi.fn((layer: { id: string }) => { layerIds.add(layer.id); }),
    getLayer: vi.fn((id: string) => (layerIds.has(id) ? { id } : null)),
    removeLayer: vi.fn((id: string) => { layerIds.delete(id); }),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getPaintProperty: vi.fn(),
    getLayoutProperty: vi.fn(),
    setFilter: vi.fn(),
    getFilter: vi.fn().mockReturnValue(null),
    isStyleLoaded: vi.fn(() => true),
    refreshTiles: vi.fn(),
    getStyle: vi.fn(() => ({ layers: Array.from(layerIds).map((id) => ({ id })) })),
    moveLayer: vi.fn(),
    setLayerZoomRange: vi.fn(),
  } as unknown as import('maplibre-gl').Map;
}

function makeVectorToken(overrides: Partial<VectorTileToken> = {}): VectorTileToken {
  return { kind: 'vector', sig: 'abc', exp: 9999999999, scope: 'test', expires_in: 3600, ...overrides };
}

function makeLayer(overrides: Partial<SyncLayerInput> = {}): SyncLayerInput {
  return {
    id: 'layer-x',
    dataset_id: 'ds-x',
    dataset_table_name: 'parcels',
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

function getSetTiles(map: import('maplibre-gl').Map, sourceId: string) {
  const src = map.getSource(sourceId) as unknown as { setTiles?: ReturnType<typeof vi.fn> } | null;
  return src?.setTiles;
}

describe('syncLayersToMap non-cluster vector tile refresh guard', () => {
  it('does NOT refetch tiles on repeated syncs when the tile URL is unchanged', () => {
    const map = createMockMap();
    const managed = { current: new Set<string>() };
    const order = { current: '' };
    const layer = makeLayer();
    const tokens = new Map<string, TileToken>([[layer.dataset_id, makeVectorToken()]]);
    const sourceId = getSourceIdForLayer(layer);

    syncLayersToMap(map, [layer], tokens, undefined, managed, order); // create
    const setTiles = getSetTiles(map, sourceId)!;
    expect(setTiles).not.toHaveBeenCalled(); // create seeds the signature; no redundant refresh

    // Repeated syncs with identical inputs (e.g. unrelated state changes) must not
    // re-issue setTiles — the regression this guards (the `!canUseCluster` block
    // previously cleared the tileurl signature every pass, defeating the guard).
    syncLayersToMap(map, [layer], tokens, undefined, managed, order);
    syncLayersToMap(map, [layer], tokens, undefined, managed, order);
    expect(setTiles).not.toHaveBeenCalled();
  });

  it('refetches tiles exactly once when a label column changes the cols= set, then stays quiet', () => {
    const map = createMockMap();
    const managed = { current: new Set<string>() };
    const order = { current: '' };
    const layer = makeLayer();
    const tokens = new Map<string, TileToken>([[layer.dataset_id, makeVectorToken()]]);
    const sourceId = getSourceIdForLayer(layer);

    syncLayersToMap(map, [layer], tokens, undefined, managed, order); // create (cols=)
    const setTiles = getSetTiles(map, sourceId)!;
    expect(setTiles).not.toHaveBeenCalled();

    // Add a label on a column not otherwise styled → cols= now includes it → URL changes.
    const labeled = makeLayer({ label_config: { column: 'name' } });
    syncLayersToMap(map, [labeled], tokens, undefined, managed, order);
    expect(setTiles).toHaveBeenCalledTimes(1);
    expect(setTiles).toHaveBeenCalledWith([expect.stringContaining('cols=name')]);

    // Re-syncing the labeled layer with no further change must not refetch again.
    syncLayersToMap(map, [labeled], tokens, undefined, managed, order);
    expect(setTiles).toHaveBeenCalledTimes(1);
  });

  it('fix(#584): popup visible_fields ride cols= and the reload is re-issued via refreshTiles on a macrotask', () => {
    vi.useFakeTimers();
    try {
      const map = createMockMap();
      const managed = { current: new Set<string>() };
      const order = { current: '' };
      const layer = makeLayer();
      const tokens = new Map<string, TileToken>([[layer.dataset_id, makeVectorToken()]]);
      const sourceId = getSourceIdForLayer(layer);

      syncLayersToMap(map, [layer], tokens, undefined, managed, order); // create
      const setTiles = getSetTiles(map, sourceId)!;

      // Selecting a popup field changes the cols= set → setTiles fires...
      const withPopup = makeLayer({
        popup_config: { enabled: true, expression: null, visible_fields: ['borough'] },
      });
      syncLayersToMap(map, [withPopup], tokens, undefined, managed, order);
      expect(setTiles).toHaveBeenCalledTimes(1);
      expect(setTiles).toHaveBeenCalledWith([expect.stringContaining('cols=borough')]);

      // ...and the reload backstop is deferred to a macrotask (after the
      // source's async load() adopts the new URL), because maplibre 5.x drops
      // setTiles' own reload when the TileManager is paused.
      const refreshTiles = (map as unknown as { refreshTiles: ReturnType<typeof vi.fn> }).refreshTiles;
      expect(refreshTiles).not.toHaveBeenCalled();
      vi.runAllTimers();
      expect(refreshTiles).toHaveBeenCalledWith(sourceId);
    } finally {
      vi.useRealTimers();
    }
  });
});
