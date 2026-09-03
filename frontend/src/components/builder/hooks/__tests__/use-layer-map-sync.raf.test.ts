/**
 * PERF-04 integration test: proves that multiple handlePaintChange calls for
 * the same layer within a single animation frame collapse to exactly ONE
 * adapter.syncPaint call (via coalesceFrame).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useLayerMapSync } from '../use-layer-map-sync';
import { __resetForTest } from '@/lib/builder/raf-coalesce';
import { applyMasterOpacity } from '@/components/builder/map-sync';
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

// We need resolveAdapterType + applyMasterOpacity from map-sync to return something
// consistent. Mock map-sync for the parts use-layer-map-sync imports.
vi.mock('@/components/builder/map-sync', () => ({
  getLayerType: vi.fn(() => 'fill'),
  resolveAdapterType: vi.fn(() => 'fill'),
  applyMasterOpacity: vi.fn(),
  // fix(#1778 codex round 4): applyLayerOpacityToMap consults this before it
  // writes, so the drain-order test below needs it present.
  isDemTerrainVisualSuppressed: vi.fn(() => false),
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

// ---------------------------------------------------------------------------
// fix(#1778 codex round 4 P2): the deferred-write replay drain has to be
// deterministic. A paint write does not touch the map itself, it queues
// adapter.syncPaint on the next animation frame, so replaying it alongside
// synchronous writes put it LAST in wall-clock order however early it was made.
// fillAdapter.syncPaint applies the input.opacity it captured (via
// applyMasterOpacity), so a queued paint edit followed by an opacity edit ended
// with the older frame overwriting the newer opacity.
// Counterfactual: remove the flushCoalescedFrame call from drainLayerWrites and
// the order assertion below inverts.
// ---------------------------------------------------------------------------
describe('useLayerMapSync: deferred replay drains paint work synchronously (#1778)', () => {
  let raf: ReturnType<typeof mockRaf>;

  beforeEach(() => {
    vi.clearAllMocks();
    raf = mockRaf();
    vi.stubGlobal('requestAnimationFrame', raf.requestAnimationFrame);
    vi.stubGlobal('cancelAnimationFrame', raf.cancelAnimationFrame);
  });

  afterEach(() => {
    __resetForTest();
    raf.flush();
    vi.unstubAllGlobals();
  });

  it('a paint edit queued during a style swap lands BEFORE a later opacity edit', () => {
    const layer = makeLayer();
    const mapStub = makeMapStub();
    const isStyleLoaded = mapStub.isStyleLoaded as unknown as ReturnType<typeof vi.fn>;
    // The basemap style is mid-swap, so the paint write is deferred.
    isStyleLoaded.mockReturnValue(false);
    const mapRef = { current: mapStub };

    const { result, rerender } = renderHook(
      ({ layers }: { layers: MapLayerResponse[] }) =>
        useLayerMapSync(layers, vi.fn(), vi.fn(), mapRef),
      { initialProps: { layers: [layer] } },
    );

    // A: paint edit, queued behind `idle`.
    act(() => { result.current.handlePaintChange(layer.id, { 'fill-color': '#00ff00' }); });
    expect(mockSyncPaint).not.toHaveBeenCalled();

    // The style finishes loading before `idle` fires.
    isStyleLoaded.mockReturnValue(true);
    rerender({ layers: [{ ...layer, paint: { ...layer.paint, 'fill-color': '#00ff00' } }] });

    // B: opacity edit. The queued paint must be drained and FLUSHED first.
    act(() => { result.current.handleOpacityChange(layer.id, 0.25); });

    const opacityMock = vi.mocked(applyMasterOpacity);
    expect(mockSyncPaint).toHaveBeenCalledTimes(1);
    expect(opacityMock).toHaveBeenCalledTimes(1);
    // Chronological order is the whole point: paint A, then opacity B.
    expect(mockSyncPaint.mock.invocationCallOrder[0])
      .toBeLessThan(opacityMock.mock.invocationCallOrder[0]);
    expect(opacityMock.mock.calls[0][4]).toBe(0.25);

    // Advancing a frame must not replay the older paint on top of the opacity.
    act(() => { raf.flush(); });
    expect(mockSyncPaint).toHaveBeenCalledTimes(1);
    expect(opacityMock.mock.invocationCallOrder.at(-1))
      .toBeGreaterThan(mockSyncPaint.mock.invocationCallOrder.at(-1)!);
  });

  it('replays a paint edit and a later opacity edit in order from the idle listener', () => {
    const layer = makeLayer();
    const mapStub = makeMapStub();
    const isStyleLoaded = mapStub.isStyleLoaded as unknown as ReturnType<typeof vi.fn>;
    isStyleLoaded.mockReturnValue(false);
    const onceCalls: [string, () => void][] = [];
    (mapStub as unknown as { once: unknown }).once = vi.fn((event: string, cb: () => void) => {
      onceCalls.push([event, cb]);
    });
    const mapRef = { current: mapStub };

    const { result } = renderHook(() =>
      useLayerMapSync([layer], vi.fn(), vi.fn(), mapRef),
    );

    act(() => { result.current.handlePaintChange(layer.id, { 'fill-color': '#00ff00' }); });
    act(() => { result.current.handleOpacityChange(layer.id, 0.25); });
    expect(mockSyncPaint).not.toHaveBeenCalled();

    isStyleLoaded.mockReturnValue(true);
    const idle = onceCalls.find(([event]) => event === 'idle');
    expect(idle).toBeDefined();
    act(() => { idle![1](); });

    const opacityMock = vi.mocked(applyMasterOpacity);
    expect(mockSyncPaint.mock.invocationCallOrder[0])
      .toBeLessThan(opacityMock.mock.invocationCallOrder[0]);

    act(() => { raf.flush(); });
    expect(mockSyncPaint).toHaveBeenCalledTimes(1);
  });
});
