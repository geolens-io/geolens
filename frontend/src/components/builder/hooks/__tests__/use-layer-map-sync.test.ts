/**
 * Phase 1051 BUG-01: Regression test for the layer visibility eye toggle.
 *
 * Asserts that `handleToggleVisibility` from `useLayerMapSync` dispatches the
 * expected `map.setLayoutProperty(...)` calls on every click — both on the main
 * layer id AND on each companion suffix layer (`-outline`, `-label`,
 * `-extrusion`, `-cluster`, `-cluster-count`) when those companion layers
 * exist in the MapLibre style.
 *
 * Mirrors the test setup pattern from `use-layer-map-sync.raf.test.ts` (vi.mock
 * for layer-adapters + map-sync + label-utils + filter-utils, minimal MaplibreMap
 * stub via vi.fn(), renderHook with handcrafted props).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useLayerMapSync } from '../use-layer-map-sync';
import type { MapLayerResponse } from '@/types/api';
import type { Map as MaplibreMap } from 'maplibre-gl';

// ---------------------------------------------------------------------------
// Module mocks (mirror raf test setup so the hook can resolve its imports)
// ---------------------------------------------------------------------------
const mockAdapter = {
  addLayers: vi.fn(),
  syncPaint: vi.fn(),
  syncFilter: vi.fn(),
  syncVisibility: vi.fn(),
};

vi.mock('@/components/builder/layer-adapters/registry', () => ({
  getAdapter: vi.fn(() => mockAdapter),
}));

vi.mock('@/components/builder/map-sync', () => ({
  getLayerType: vi.fn(() => 'fill'),
  resolveAdapterType: vi.fn(() => 'fill'),
  getCompoundOpacity: vi.fn((_paint: Record<string, unknown>, _type: string, opacity: number) => opacity),
  getSourceIdForLayer: vi.fn((layer: { id: string }) => `source-${layer.id}`),
}));

vi.mock('@/lib/maplibre-filter-utils', () => ({
  sanitizeNullableNumericFilter: vi.fn((f: unknown) => f),
}));

vi.mock('@/components/builder/label-layer-utils', () => ({
  buildLabelLayerSpec: vi.fn(),
  syncLabelLayer: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
const LAYER_ID = 'layer-uuid-123';
const COMPANION_SUFFIXES = ['', '-outline', '-label', '-extrusion', '-cluster', '-cluster-count'] as const;
const ALL_COMPANION_IDS = COMPANION_SUFFIXES.map((suffix) => `layer-${LAYER_ID}${suffix}`);

const makeLayer = (overrides: Partial<MapLayerResponse> = {}): MapLayerResponse => ({
  id: LAYER_ID,
  dataset_id: 'ds-1',
  dataset_name: 'Test',
  dataset_geometry_type: 'Polygon',
  dataset_table_name: 'test_table',
  dataset_extent_bbox: null,
  dataset_column_info: null,
  dataset_feature_count: null,
  dataset_sample_values: null,
  display_name: 'Test Layer',
  sort_order: 0,
  visible: true,
  opacity: 1,
  paint: {},
  layout: {},
  filter: null,
  label_config: null,
  style_config: null,
  ...overrides,
});

/**
 * Make a stub MapLibre map where `getLayer` returns truthy for any id in
 * `existingLayerIds` and undefined otherwise. `setLayoutProperty` is a vi.fn()
 * so the test can assert call args.
 */
function makeMapStub(existingLayerIds: string[] = ALL_COMPANION_IDS) {
  const existing = new Set(existingLayerIds);
  return {
    isStyleLoaded: vi.fn(() => true),
    getLayer: vi.fn((id: string) => (existing.has(id) ? { id } : undefined)),
    getSource: vi.fn(() => undefined),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    setFilter: vi.fn(),
    addLayer: vi.fn(),
    addSource: vi.fn(),
    removeLayer: vi.fn(),
    removeSource: vi.fn(),
    setLayerZoomRange: vi.fn(),
  } as unknown as MaplibreMap;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('useLayerMapSync — handleToggleVisibility (BUG-01 regression)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('Test 1: toggles a visible layer → setLayoutProperty(id, "visibility", "none")', () => {
    const layer = makeLayer({ visible: true });
    const mapStub = makeMapStub();
    const mapRef = { current: mapStub };
    const setLocalLayers = vi.fn();
    const setHasUnsavedChanges = vi.fn();

    const { result } = renderHook(() =>
      useLayerMapSync([layer], setLocalLayers, setHasUnsavedChanges, mapRef),
    );

    act(() => {
      result.current.handleToggleVisibility(layer.id);
    });

    // Main layer received setLayoutProperty('visibility', 'none')
    expect(mapStub.setLayoutProperty).toHaveBeenCalledWith(
      `layer-${LAYER_ID}`,
      'visibility',
      'none',
    );
    // State updated
    expect(setLocalLayers).toHaveBeenCalled();
    expect(setHasUnsavedChanges).toHaveBeenCalledWith(true);
  });

  it('Test 2: visible → hidden → visible round-trip dispatches setLayoutProperty twice with correct values', () => {
    // First toggle: layer is visible → expect 'none'
    const visibleLayer = makeLayer({ visible: true });
    const mapStub1 = makeMapStub();
    const mapRef1 = { current: mapStub1 };
    const setLocalLayers1 = vi.fn();
    const { result: result1 } = renderHook(() =>
      useLayerMapSync([visibleLayer], setLocalLayers1, vi.fn(), mapRef1),
    );

    act(() => {
      result1.current.handleToggleVisibility(visibleLayer.id);
    });

    expect(mapStub1.setLayoutProperty).toHaveBeenCalledWith(
      `layer-${LAYER_ID}`,
      'visibility',
      'none',
    );

    // Second toggle simulates the layer now being hidden: rerender the hook
    // with the post-toggle state. (Each renderHook call gets a fresh layersRef,
    // and the side-effect cares about layersRef.current — which is mirrored
    // via useLayoutEffect from the props.)
    const hiddenLayer = makeLayer({ visible: false });
    const mapStub2 = makeMapStub();
    const mapRef2 = { current: mapStub2 };
    const setLocalLayers2 = vi.fn();
    const { result: result2 } = renderHook(() =>
      useLayerMapSync([hiddenLayer], setLocalLayers2, vi.fn(), mapRef2),
    );

    act(() => {
      result2.current.handleToggleVisibility(hiddenLayer.id);
    });

    expect(mapStub2.setLayoutProperty).toHaveBeenCalledWith(
      `layer-${LAYER_ID}`,
      'visibility',
      'visible',
    );
  });

  it('Test 3: all 6 companion suffixes receive setLayoutProperty when they exist on the map', () => {
    const layer = makeLayer({ visible: true });
    const mapStub = makeMapStub(ALL_COMPANION_IDS);
    const mapRef = { current: mapStub };
    const { result } = renderHook(() =>
      useLayerMapSync([layer], vi.fn(), vi.fn(), mapRef),
    );

    act(() => {
      result.current.handleToggleVisibility(layer.id);
    });

    // Each companion id must have received setLayoutProperty('visibility', 'none')
    for (const cid of ALL_COMPANION_IDS) {
      expect(mapStub.setLayoutProperty).toHaveBeenCalledWith(cid, 'visibility', 'none');
    }
    // Exactly 6 calls — one per companion that exists
    expect(mapStub.setLayoutProperty).toHaveBeenCalledTimes(ALL_COMPANION_IDS.length);
  });

  it('Test 4: companion suffixes that do NOT exist on the map are skipped (getLayer guard)', () => {
    const layer = makeLayer({ visible: true });
    // Only the main layer exists — no companions
    const mapStub = makeMapStub([`layer-${LAYER_ID}`]);
    const mapRef = { current: mapStub };
    const { result } = renderHook(() =>
      useLayerMapSync([layer], vi.fn(), vi.fn(), mapRef),
    );

    act(() => {
      result.current.handleToggleVisibility(layer.id);
    });

    // Main got the dispatch
    expect(mapStub.setLayoutProperty).toHaveBeenCalledWith(
      `layer-${LAYER_ID}`,
      'visibility',
      'none',
    );
    // No companion dispatched
    expect(mapStub.setLayoutProperty).toHaveBeenCalledTimes(1);
  });

  it('Test 5: applyLayerUpdate early-exit fires for unknown layerId (no dispatch, no state mutation)', () => {
    const layer = makeLayer({ visible: true });
    const mapStub = makeMapStub();
    const mapRef = { current: mapStub };
    const setLocalLayers = vi.fn();
    const setHasUnsavedChanges = vi.fn();
    const { result } = renderHook(() =>
      useLayerMapSync([layer], setLocalLayers, setHasUnsavedChanges, mapRef),
    );

    act(() => {
      result.current.handleToggleVisibility('layer-that-does-not-exist');
    });

    // No state mutation
    expect(setLocalLayers).not.toHaveBeenCalled();
    expect(setHasUnsavedChanges).not.toHaveBeenCalled();
    // No map mutation
    expect(mapStub.setLayoutProperty).not.toHaveBeenCalled();
  });

  it('Test 6: valid layerId does NOT early-exit (regression guard against false-positive guard match)', () => {
    const layer = makeLayer({ visible: true });
    const mapStub = makeMapStub();
    const mapRef = { current: mapStub };
    const setLocalLayers = vi.fn();
    const setHasUnsavedChanges = vi.fn();
    const { result } = renderHook(() =>
      useLayerMapSync([layer], setLocalLayers, setHasUnsavedChanges, mapRef),
    );

    act(() => {
      result.current.handleToggleVisibility(layer.id);
    });

    // The guard must not block valid updates — state + map both touched
    expect(setLocalLayers).toHaveBeenCalledTimes(1);
    expect(setHasUnsavedChanges).toHaveBeenCalledWith(true);
    expect(mapStub.setLayoutProperty).toHaveBeenCalled();
  });

  it('Test 7: explicit visible=false param wins over toggle logic', () => {
    // Layer is already hidden; explicit visible=false should still dispatch 'none'
    const layer = makeLayer({ visible: false });
    const mapStub = makeMapStub();
    const mapRef = { current: mapStub };
    const { result } = renderHook(() =>
      useLayerMapSync([layer], vi.fn(), vi.fn(), mapRef),
    );

    act(() => {
      result.current.handleToggleVisibility(layer.id, false);
    });

    // Was hidden, explicitly set to hidden → still 'none' (idempotent dispatch)
    expect(mapStub.setLayoutProperty).toHaveBeenCalledWith(
      `layer-${LAYER_ID}`,
      'visibility',
      'none',
    );
  });

  it('Test 8: visibility dispatch is synchronous (not gated through rAF coalesceFrame)', () => {
    const layer = makeLayer({ visible: true });
    const mapStub = makeMapStub();
    const mapRef = { current: mapStub };
    const { result } = renderHook(() =>
      useLayerMapSync([layer], vi.fn(), vi.fn(), mapRef),
    );

    // Stub requestAnimationFrame so we can confirm visibility does NOT wait for it
    const rafSpy = vi.spyOn(globalThis, 'requestAnimationFrame');

    act(() => {
      result.current.handleToggleVisibility(layer.id);
    });

    expect(mapStub.setLayoutProperty).toHaveBeenCalled();
    expect(rafSpy).not.toHaveBeenCalled();

    rafSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// Adapter addLayers visibility regression (BUG-01 follow-up)
//
// Diagnosis: the eye toggle handler is wired correctly, but a layer can drift
// out of sync with the map when ANY non-sync code path calls `adapter.addLayers`
// (e.g. `swapLayerOnMap` for render-mode switches, or the raster re-add branch
// in `handleStyleConfigChange`). Those call sites do NOT then call
// `adapter.syncVisibility`, so a layer with `visible=false` is silently rendered
// on the map until the next React-triggered runSync. The user then perceives
// the next eye click as a no-op because the map is already at the "wrong"
// visibility — clicking flips React state (visible=false → true) and the
// handler dispatches `setLayoutProperty('visibility', 'visible')`, which is a
// MapLibre no-op because the layer was already visible.
//
// Fix surface: every adapter's `addLayers` must honor `input.visible` so that
// any caller (sync or swap) gets a layer in the correct initial visibility
// state without depending on a follow-up `syncVisibility` call.
// ---------------------------------------------------------------------------
describe('adapter.addLayers respects input.visible (BUG-01 root cause)', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
  });

  function makeAddLayerMap() {
    const layerSpecs = new Map<string, { layout?: Record<string, unknown> }>();
    const sources = new Map<string, unknown>();
    const layoutProps = new Map<string, Record<string, unknown>>();
    return {
      addLayer: vi.fn((layer: { id: string; layout?: Record<string, unknown> }) => {
        layerSpecs.set(layer.id, { layout: layer.layout });
        if (layer.layout) layoutProps.set(layer.id, { ...layer.layout });
      }),
      getLayer: vi.fn((id: string) => (layerSpecs.has(id) ? { id } : null)),
      addSource: vi.fn((id: string, spec: unknown) => { sources.set(id, spec); }),
      getSource: vi.fn((id: string) => sources.get(id) ?? null),
      removeLayer: vi.fn(),
      removeSource: vi.fn(),
      setPaintProperty: vi.fn(),
      setLayoutProperty: vi.fn((id: string, prop: string, value: unknown) => {
        const props = layoutProps.get(id) ?? {};
        props[prop] = value;
        layoutProps.set(id, props);
      }),
      getLayoutProperty: vi.fn((id: string, prop: string) => layoutProps.get(id)?.[prop]),
      setFilter: vi.fn(),
      setLayerZoomRange: vi.fn(),
      hasImage: vi.fn(() => false),
      addImage: vi.fn(),
      getSprite: vi.fn(() => []),
      addSprite: vi.fn(),
      isStyleLoaded: vi.fn(() => true),
      __layerSpecs: layerSpecs,
      __layoutProps: layoutProps,
    } as unknown as MaplibreMap & {
      __layerSpecs: Map<string, { layout?: Record<string, unknown> }>;
      __layoutProps: Map<string, Record<string, unknown>>;
    };
  }

  function commonInput(layerId: string, visible: boolean) {
    return {
      id: layerId,
      dataset_table_name: 'shared',
      dataset_geometry_type: 'Polygon',
      opacity: 1,
      visible,
      paint: {},
      layout: {},
      filter: null,
      sourceId: `source-${layerId}`,
      layerId: `layer-${layerId}`,
      sourceLayer: 'data.shared',
      tileUrl: '/tiles/shared/{z}/{x}/{y}.pbf',
    };
  }

  it('fillAdapter.addLayers with visible=false ends with main layer visibility "none"', async () => {
    const { fillAdapter } = await import('@/components/builder/layer-adapters/fill-adapter');
    const map = makeAddLayerMap();
    const input = commonInput('hidden-fill', false);

    fillAdapter.addLayers(map as unknown as MaplibreMap, input as never);

    const vis = (map as unknown as { getLayoutProperty: (id: string, prop: string) => unknown })
      .getLayoutProperty('layer-hidden-fill', 'visibility');
    expect(vis).toBe('none');

    // Outline companion must also be hidden (it shares the parent's visibility).
    const outlineVis = (map as unknown as { getLayoutProperty: (id: string, prop: string) => unknown })
      .getLayoutProperty('layer-hidden-fill-outline', 'visibility');
    expect(outlineVis).toBe('none');
  });

  it('fillAdapter.addLayers with visible=true ends with main layer visibility "visible"', async () => {
    const { fillAdapter } = await import('@/components/builder/layer-adapters/fill-adapter');
    const map = makeAddLayerMap();
    const input = commonInput('shown-fill', true);

    fillAdapter.addLayers(map as unknown as MaplibreMap, input as never);

    const vis = (map as unknown as { getLayoutProperty: (id: string, prop: string) => unknown })
      .getLayoutProperty('layer-shown-fill', 'visibility');
    // Either explicit 'visible' or undefined (MapLibre default) is acceptable.
    expect(vis === 'visible' || vis === undefined).toBe(true);
  });

  it('lineAdapter.addLayers with visible=false ends with main layer visibility "none"', async () => {
    const { lineAdapter } = await import('@/components/builder/layer-adapters/line-adapter');
    const map = makeAddLayerMap();
    const input = { ...commonInput('hidden-line', false), dataset_geometry_type: 'LineString' };

    lineAdapter.addLayers(map as unknown as MaplibreMap, input as never);

    const vis = (map as unknown as { getLayoutProperty: (id: string, prop: string) => unknown })
      .getLayoutProperty('layer-hidden-line', 'visibility');
    expect(vis).toBe('none');
  });

  it('circleAdapter.addLayers with visible=false ends with main layer visibility "none"', async () => {
    const { circleAdapter } = await import('@/components/builder/layer-adapters/circle-adapter');
    const map = makeAddLayerMap();
    const input = { ...commonInput('hidden-circle', false), dataset_geometry_type: 'Point' };

    circleAdapter.addLayers(map as unknown as MaplibreMap, input as never);

    const vis = (map as unknown as { getLayoutProperty: (id: string, prop: string) => unknown })
      .getLayoutProperty('layer-hidden-circle', 'visibility');
    expect(vis).toBe('none');
  });

  it('heatmapAdapter.addLayers with visible=false ends with main layer visibility "none"', async () => {
    const { heatmapAdapter } = await import('@/components/builder/layer-adapters/heatmap-adapter');
    const map = makeAddLayerMap();
    const input = { ...commonInput('hidden-heatmap', false), dataset_geometry_type: 'Point' };

    heatmapAdapter.addLayers(map as unknown as MaplibreMap, input as never);

    const vis = (map as unknown as { getLayoutProperty: (id: string, prop: string) => unknown })
      .getLayoutProperty('layer-hidden-heatmap', 'visibility');
    expect(vis).toBe('none');
  });
});
