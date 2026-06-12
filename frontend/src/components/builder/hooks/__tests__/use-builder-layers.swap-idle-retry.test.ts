/**
 * BUG-018 regression: swapLayerOnMap idle-retry during style transitions.
 *
 * Pre-fix: swapLayerOnMap did `if (!map || !map.isStyleLoaded()) return;`
 * which silently dropped render-mode switches while the style was transitioning.
 *
 * Post-fix: on `!isStyleLoaded()` the function registers
 * `map.once('idle', () => swapLayerOnMap(...))` and returns early — the swap
 * is deferred to the idle event rather than dropped.
 *
 * IMPORTANT — Worker OOM note (mirrors use-builder-layers.add-dataset.test.ts):
 *   - Do NOT use vi.mock() declarations in this file.
 *   - Do NOT create mapData inside the renderHook callback — that creates a
 *     new object reference on every render, making mapData a dep-array unstable
 *     reference and causing an infinite re-render → heap OOM.
 *   - mapData MUST be created outside renderHook and passed in as a stable ref.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import {
  makeBuilderLayer,
  makeBuilderMap,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import type { MapLayerResponse } from '@/types/api';

type MaplibreMap = import('maplibre-gl').Map;

// ---------------------------------------------------------------------------
// Fixtures — created ONCE per test scope (stable references)
// ---------------------------------------------------------------------------

const LAYER_ID = 'layer-uuid-018';

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return makeBuilderLayer({
    id: LAYER_ID,
    dataset_id: 'ds-018',
    dataset_geometry_type: 'Point',
    dataset_table_name: 'test_018',
    layer_type: 'vector_geolens',
    ...overrides,
  });
}

/**
 * Render useBuilderLayers with a given mapRef.
 * mapData MUST be pre-created outside this function to avoid the infinite
 * re-render loop caused by new-object-on-every-render.
 */
function renderBuilderLayersHook(
  mapData: ReturnType<typeof makeBuilderMap>,
  mapRef: React.RefObject<MaplibreMap | null>,
) {
  const addLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3];
  const removeLayerMutation = {
    mutate: vi.fn(),
  } as unknown as Parameters<typeof useBuilderLayers>[4];
  return renderHook(() =>
    useBuilderLayers(
      mapData,
      mapRef,
      'map-018',
      addLayerMutation,
      removeLayerMutation,
    ),
  );
}

// ---------------------------------------------------------------------------
// Map stub helpers
// ---------------------------------------------------------------------------

type IdleCallback = () => void;

function makeTransitioningMapStub(existingLayerIds: string[] = []): MaplibreMap & {
  _idleCallbacks: IdleCallback[];
  _fireIdle: () => void;
} {
  const existing = new Set(existingLayerIds);
  const idleCallbacks: IdleCallback[] = [];
  let styleLoaded = false;

  const stub = {
    isStyleLoaded: vi.fn(() => styleLoaded),
    getLayer: vi.fn((id: string) => (existing.has(id) ? { id } : undefined)),
    getSource: vi.fn(() => ({ tiles: ['/tiles/mock/{z}/{x}/{y}.pbf'] })),
    addSource: vi.fn(),
    removeSource: vi.fn(),
    addLayer: vi.fn((spec: { id: string }) => { existing.add(spec.id); }),
    removeLayer: vi.fn((id: string) => { existing.delete(id); }),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    setFilter: vi.fn(),
    moveLayer: vi.fn(),
    setLayerZoomRange: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    once: vi.fn((event: string, cb: IdleCallback) => {
      if (event === 'idle') idleCallbacks.push(cb);
    }),
    getStyle: vi.fn(() => ({ layers: [] })),
    fitBounds: vi.fn(),
    setTransformRequest: vi.fn(),
    resize: vi.fn(),
    loaded: vi.fn(() => false),
    _idleCallbacks: idleCallbacks,
    _fireIdle: () => {
      styleLoaded = true;
      (stub.isStyleLoaded as ReturnType<typeof vi.fn>).mockReturnValue(true);
      for (const cb of [...idleCallbacks]) cb();
    },
  } as unknown as MaplibreMap & { _idleCallbacks: IdleCallback[]; _fireIdle: () => void };

  return stub;
}

function makeLoadedMapStub(existingLayerIds: string[] = []): MaplibreMap {
  const existing = new Set(existingLayerIds);
  return {
    isStyleLoaded: vi.fn(() => true),
    getLayer: vi.fn((id: string) => (existing.has(id) ? { id } : undefined)),
    getSource: vi.fn(() => ({ tiles: ['/tiles/mock/{z}/{x}/{y}.pbf'] })),
    addSource: vi.fn(),
    removeSource: vi.fn(),
    addLayer: vi.fn((spec: { id: string }) => { existing.add(spec.id); }),
    removeLayer: vi.fn(),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    setFilter: vi.fn(),
    moveLayer: vi.fn(),
    setLayerZoomRange: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    once: vi.fn(),
    getStyle: vi.fn(() => ({ layers: [] })),
    fitBounds: vi.fn(),
    setTransformRequest: vi.fn(),
    resize: vi.fn(),
    loaded: vi.fn(() => true),
  } as unknown as MaplibreMap;
}

// ---------------------------------------------------------------------------
// Tests — BUG-018
// ---------------------------------------------------------------------------

describe('swapLayerOnMap — idle-retry during style transition (BUG-018)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('Test 1: registers map.once("idle", cb) when isStyleLoaded() is false (no immediate swap)', () => {
    const layer = makeLayer();
    // mapData is stable — created outside renderHook callback
    const mapData = makeBuilderMap([layer]);
    const mapStub = makeTransitioningMapStub([`layer-${LAYER_ID}`]);
    const mapRef = { current: mapStub as unknown as MaplibreMap } as React.RefObject<MaplibreMap | null>;

    const { result } = renderBuilderLayersHook(mapData, mapRef);

    act(() => {
      result.current.handleRenderAsChange(LAYER_ID, 'heatmap');
    });

    // once('idle', ...) must have been registered (BUG-018 fix)
    expect(mapStub.once).toHaveBeenCalledWith('idle', expect.any(Function));
    // No immediate swap — addLayer NOT called yet (deferred to idle)
    expect(mapStub.addLayer).not.toHaveBeenCalled();
  });

  it('Test 2: invoking the idle callback performs the swap (addLayer called after idle fires)', () => {
    const layer = makeLayer();
    const mapData = makeBuilderMap([layer]);
    const mapStub = makeTransitioningMapStub([`layer-${LAYER_ID}`]);
    const mapRef = { current: mapStub as unknown as MaplibreMap } as React.RefObject<MaplibreMap | null>;

    const { result } = renderBuilderLayersHook(mapData, mapRef);

    act(() => {
      result.current.handleRenderAsChange(LAYER_ID, 'heatmap');
    });

    // Idle callback was captured
    expect(mapStub._idleCallbacks.length).toBeGreaterThan(0);
    const addLayerBefore = (mapStub.addLayer as ReturnType<typeof vi.fn>).mock.calls.length;

    // Fire idle — flips isStyleLoaded → true then invokes cb
    act(() => {
      mapStub._fireIdle();
    });

    // After idle: addLayer called (the swap ran)
    const addLayerAfter = (mapStub.addLayer as ReturnType<typeof vi.fn>).mock.calls.length;
    expect(addLayerAfter).toBeGreaterThan(addLayerBefore);
  });

  it('Test 3: when isStyleLoaded() is true, swap happens immediately without once("idle")', () => {
    const layer = makeLayer();
    const mapData = makeBuilderMap([layer]);
    const mapStub = makeLoadedMapStub([`layer-${LAYER_ID}`]);
    const mapRef = { current: mapStub } as React.RefObject<MaplibreMap | null>;

    const { result } = renderBuilderLayersHook(mapData, mapRef);

    act(() => {
      result.current.handleRenderAsChange(LAYER_ID, 'heatmap');
    });

    // No idle registration when style is already loaded
    expect(mapStub.once).not.toHaveBeenCalledWith('idle', expect.any(Function));
    // Swap happened immediately
    expect(mapStub.addLayer).toHaveBeenCalled();
  });

  it('Test 4: exactly one idle registration per swap call (no infinite once loop)', () => {
    const layer = makeLayer();
    const mapData = makeBuilderMap([layer]);
    const mapStub = makeTransitioningMapStub([]);
    const mapRef = { current: mapStub as unknown as MaplibreMap } as React.RefObject<MaplibreMap | null>;

    const { result } = renderBuilderLayersHook(mapData, mapRef);

    act(() => {
      // Use 'heatmap' (not 'circle' which is already the default for Point)
      // so buildRenderAsPatch returns a real mutation and swapLayerOnMap is called.
      result.current.handleRenderAsChange(LAYER_ID, 'heatmap');
    });

    const idleCalls = (mapStub.once as ReturnType<typeof vi.fn>).mock.calls.filter(
      (args: unknown[]) => args[0] === 'idle',
    );
    expect(idleCalls).toHaveLength(1);
  });
});
