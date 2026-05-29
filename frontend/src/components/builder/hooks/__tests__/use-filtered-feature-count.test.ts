import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@/test/test-utils';
import type { MapLayerResponse } from '@/types/api';
import { useFilteredFeatureCount } from '../use-filtered-feature-count';

// ---------------------------------------------------------------------------
// Mock map factory — matches the shape used by use-builder-save.test.ts
// ---------------------------------------------------------------------------
function createMockMap(overrides: {
  getLayerResult?: unknown;
  noLayer?: boolean; // when true, getLayer returns undefined regardless
  queryRenderedFeaturesResult?: unknown[];
} = {}) {
  return {
    getLayer: vi.fn<(layerId: string) => unknown>(
      () => overrides.noLayer ? undefined : (overrides.getLayerResult ?? { id: 'mock-layer' }),
    ),
    queryRenderedFeatures: vi.fn<
      (geometry?: unknown, options?: { layers?: string[] }) => unknown[]
    >(() => overrides.queryRenderedFeaturesResult ?? []),
    on: vi.fn(),
    off: vi.fn(),
  };
}

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'Test',
    dataset_geometry_type: 'POLYGON',
    dataset_table_name: 'test_table',
    dataset_extent_bbox: [0, 0, 1, 1],
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: overrides.filter ?? ['all', ['==', ['get', 'name'], 'x']],
    label_config: null,
    popup_config: null,
    style_config: null,
    layer_type: null,
    dataset_record_type: 'vector_dataset',
    show_in_legend: true,
    is_dem: false,
    dem_vertical_units: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useFilteredFeatureCount', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('EASY-18 — returns null when map is null', () => {
    const layer = makeLayer({ filter: ['all', ['==', ['get', 'name'], 'x']] });
    const { result } = renderHook(() =>
      useFilteredFeatureCount(null, layer),
    );
    expect(result.current).toBeNull();
  });

  it('EASY-18 — returns null when layer is null', () => {
    const mockMap = createMockMap();
    const { result } = renderHook(() =>
      useFilteredFeatureCount(mockMap as never, null),
    );
    expect(result.current).toBeNull();
  });

  it('EASY-18 — returns null when layer has no filter set', () => {
    const mockMap = createMockMap();
    const layerNoFilter = makeLayer({ filter: null });
    const { result } = renderHook(() =>
      useFilteredFeatureCount(mockMap as never, layerNoFilter),
    );
    expect(result.current).toBeNull();
  });

  it('EASY-18 — returns null when layer is not yet on the map (getLayer returns undefined)', () => {
    const mockMap = createMockMap({ noLayer: true });
    const layer = makeLayer({ filter: ['all', ['==', ['get', 'name'], 'x']] });
    const { result } = renderHook(() =>
      useFilteredFeatureCount(mockMap as never, layer),
    );
    // Layer not on map — count must be null; queryRenderedFeatures must NOT be called
    expect(result.current).toBeNull();
    expect(mockMap.queryRenderedFeatures).not.toHaveBeenCalled();
  });

  it('EASY-18 — returns 0 when queryRenderedFeatures returns []', () => {
    const mockMap = createMockMap({
      getLayerResult: { id: 'layer-1' },
      queryRenderedFeaturesResult: [],
    });
    const layer = makeLayer({ filter: ['all', ['==', ['get', 'name'], 'x']] });
    const { result } = renderHook(() =>
      useFilteredFeatureCount(mockMap as never, layer),
    );
    expect(result.current).toBe(0);
  });

  it('EASY-18 — returns 3 when queryRenderedFeatures returns 3 features', () => {
    const mockMap = createMockMap({
      getLayerResult: { id: 'layer-1' },
      queryRenderedFeaturesResult: [{}, {}, {}],
    });
    const layer = makeLayer({ filter: ['all', ['==', ['get', 'name'], 'x']] });
    const { result } = renderHook(() =>
      useFilteredFeatureCount(mockMap as never, layer),
    );
    expect(result.current).toBe(3);
  });

  it('EASY-18 — unmount removes idle handler + clears pending debounce timer', () => {
    const mockMap = createMockMap({
      getLayerResult: { id: 'layer-1' },
      queryRenderedFeaturesResult: [{}],
    });
    const layer = makeLayer({ filter: ['all', ['==', ['get', 'name'], 'x']] });
    const { unmount } = renderHook(() =>
      useFilteredFeatureCount(mockMap as never, layer),
    );

    // Simulate an idle event to enqueue the debounce timer
    const idleCall = mockMap.on.mock.calls.find((c) => c[0] === 'idle');
    if (idleCall) {
      act(() => {
        (idleCall[1] as () => void)();
      });
    }

    // Unmount before the 250ms debounce fires
    unmount();

    // Verify map.off was called with 'idle' (cleanup ran)
    const offCalls = mockMap.off.mock.calls;
    const idleOffCall = offCalls.find((c) => c[0] === 'idle');
    expect(idleOffCall).toBeDefined();

    // Advance timers past the debounce — should not throw
    act(() => {
      vi.advanceTimersByTime(500);
    });
  });
});
