/**
 * PERF-04 integration test: proves that multiple handlePaintChange calls for
 * the same layer within a single animation frame collapse to exactly ONE
 * adapter.syncPaint call (via coalesceFrame).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useLayerMapSync } from '../use-layer-map-sync';
import { __resetForTest } from '@/lib/builder/raf-coalesce';
import type { MapLayerResponse } from '@/types/api';
import type { Map as MaplibreMap } from 'maplibre-gl';

// ---------------------------------------------------------------------------
// Mock the layer-adapters registry so syncPaint is a vi.fn() we can assert on
// ---------------------------------------------------------------------------
const mockSyncPaint = vi.fn();
const mockAdapter = {
  addLayers: vi.fn(),
  syncPaint: mockSyncPaint,
  syncFilter: vi.fn(),
  syncVisibility: vi.fn(),
};

vi.mock('@/components/builder/layer-adapters/registry', () => ({
  getAdapter: vi.fn(() => mockAdapter),
}));

// We need resolveAdapterType + getCompoundOpacity from map-sync to return something
// consistent. Mock map-sync for the parts use-layer-map-sync imports.
vi.mock('@/components/builder/map-sync', () => ({
  getLayerType: vi.fn(() => 'fill'),
  resolveAdapterType: vi.fn(() => 'fill'),
  getCompoundOpacity: vi.fn((paint: Record<string, unknown>, _type: string, opacity: number) => opacity),
  // Phase 1050 SF-04: use-layer-map-sync now routes through this helper.
  // The PERF-04 test only asserts call counts (does not validate sourceId
  // values), so a simple per-layer string is sufficient here.
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
// rAF mock helpers (same pattern as raf-coalesce.test.ts)
// ---------------------------------------------------------------------------
type RafCallback = (time: number) => void;

function mockRaf() {
  let _handle = 0;
  const _queue = new Map<number, RafCallback>();

  const requestAnimationFrame = vi.fn((cb: RafCallback): number => {
    const handle = ++_handle;
    _queue.set(handle, cb);
    return handle;
  });

  const cancelAnimationFrame = vi.fn((handle: number): void => {
    _queue.delete(handle);
  });

  function flush(time = 0): void {
    const entries = Array.from(_queue.entries());
    _queue.clear();
    for (const [, cb] of entries) {
      cb(time);
    }
  }

  return { requestAnimationFrame, cancelAnimationFrame, flush };
}

// ---------------------------------------------------------------------------
// Minimal test doubles
// ---------------------------------------------------------------------------
const makeLayer = (id = 'layer-1'): MapLayerResponse => ({
  id,
  dataset_id: 'ds-1',
  dataset_name: 'test-dataset',
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
  paint: { 'fill-color': '#ff0000', 'fill-opacity': 1 },
  layout: {},
  filter: null,
  label_config: null,
  style_config: null,
});

const makeMapStub = (layerExists = true): MaplibreMap => ({
  isStyleLoaded: vi.fn(() => true),
  getLayer: vi.fn(() => layerExists ? { id: 'layer-layer-1' } : undefined),
  getSource: vi.fn(() => ({ tiles: ['http://localhost/tiles/{z}/{x}/{y}.pbf'] })),
  setLayoutProperty: vi.fn(),
  setPaintProperty: vi.fn(),
  setFilter: vi.fn(),
  addLayer: vi.fn(),
  addSource: vi.fn(),
  removeLayer: vi.fn(),
  removeSource: vi.fn(),
  setLayerZoomRange: vi.fn(),
} as unknown as MaplibreMap);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('useLayerMapSync — rAF paint coalescing (PERF-04)', () => {
  let raf: ReturnType<typeof mockRaf>;

  beforeEach(() => {
    vi.clearAllMocks();
    // Reset the raf-coalesce module state between tests
    // (we import the test helpers from the module under test)
    raf = mockRaf();
    vi.stubGlobal('requestAnimationFrame', raf.requestAnimationFrame);
    vi.stubGlobal('cancelAnimationFrame', raf.cancelAnimationFrame);
  });

  afterEach(() => {
    __resetForTest(); // clear module-level pending + rafHandle (CR-02)
    raf.flush();      // drain any remaining mock rAF queue entries
    vi.unstubAllGlobals();
  });

  // -------------------------------------------------------------------------
  // Test 1: 10 successive handlePaintChange calls → 1 syncPaint call after rAF tick
  // -------------------------------------------------------------------------
  it('Test 1: 10 rapid handlePaintChange calls for the same layer → 1 syncPaint after rAF tick', () => {
    const layer = makeLayer();
    const mapRef = { current: makeMapStub() };
    const setLocalLayers = vi.fn();
    const setHasUnsavedChanges = vi.fn();

    const { result } = renderHook(() =>
      useLayerMapSync(
        [layer],
        setLocalLayers,
        setHasUnsavedChanges,
        mapRef,
      ),
    );

    const { handlePaintChange } = result.current;

    // Call handlePaintChange 10 times rapidly
    act(() => {
      for (let i = 0; i < 10; i++) {
        handlePaintChange(layer.id, { 'fill-color': `#ff${i}${i}${i}${i}` });
      }
    });

    // Before rAF tick: syncPaint should NOT have been called yet
    expect(mockSyncPaint).not.toHaveBeenCalled();

    // Flush the rAF tick
    act(() => {
      raf.flush();
    });

    // After rAF tick: syncPaint called exactly ONCE (last value wins)
    expect(mockSyncPaint).toHaveBeenCalledTimes(1);
  });

  // -------------------------------------------------------------------------
  // Test 2: handlePaintChange for DIFFERENT layers both fire on same rAF tick
  // -------------------------------------------------------------------------
  it('Test 2: handlePaintChange for two different layers both fire on the same rAF tick', () => {
    const layerA = makeLayer('layer-a');
    const layerB = makeLayer('layer-b');
    const mapRef = { current: makeMapStub() };
    const setLocalLayers = vi.fn();
    const setHasUnsavedChanges = vi.fn();

    const { result } = renderHook(() =>
      useLayerMapSync(
        [layerA, layerB],
        setLocalLayers,
        setHasUnsavedChanges,
        mapRef,
      ),
    );

    const { handlePaintChange } = result.current;

    act(() => {
      handlePaintChange(layerA.id, { 'fill-color': '#aaaaaa' });
      handlePaintChange(layerB.id, { 'fill-color': '#bbbbbb' });
    });

    expect(mockSyncPaint).not.toHaveBeenCalled();

    act(() => {
      raf.flush();
    });

    // Both layers' syncPaint called — different keys don't coalesce
    expect(mockSyncPaint).toHaveBeenCalledTimes(2);
  });

  // -------------------------------------------------------------------------
  // Test 3: Visibility changes stay synchronous (not coalesced through rAF)
  // -------------------------------------------------------------------------
  it('Test 3: handleToggleVisibility fires synchronously (not via rAF)', () => {
    const layer = makeLayer();
    const mapRef = { current: makeMapStub() };
    const setLocalLayers = vi.fn();
    const setHasUnsavedChanges = vi.fn();

    const { result } = renderHook(() =>
      useLayerMapSync(
        [layer],
        setLocalLayers,
        setHasUnsavedChanges,
        mapRef,
      ),
    );

    const { handleToggleVisibility } = result.current;

    act(() => {
      handleToggleVisibility(layer.id, false);
    });

    // Visibility is synchronous — setLayoutProperty should have been called
    // WITHOUT needing a rAF flush. (map.setLayoutProperty is the sync path)
    expect(mapRef.current.setLayoutProperty).toHaveBeenCalled();
    // syncPaint was NOT called for visibility (different handler)
    expect(mockSyncPaint).not.toHaveBeenCalled();
    // No rAF was needed (raf queue is either empty or we can flush to confirm nothing extra)
    const syncPaintCallsBeforeFlush = mockSyncPaint.mock.calls.length;
    raf.flush();
    expect(mockSyncPaint.mock.calls.length).toBe(syncPaintCallsBeforeFlush);
  });
});
