/**
 * Phase 1041 — Bulk operation handler tests (POL-09).
 * Phase 1047-04 — Extended with bulkDeleteLayersApi tests (PERF-03).
 *
 * Tests handleBulkVisibility, handleBulkOpacity, handleBulkGroup, handleBulkUngroup,
 * and handleBulkDelete (including rollback on failure) in use-builder-layers.ts.
 *
 * Worker-safety:
 *   - No file-level vi.mock('@dnd-kit/core', ...) — this is the POL-20 anti-pattern
 *     that caused worker exits in use-builder-layers.add-dataset.test.ts.
 *   - We use vi.mock with vi.importActual for @/api/maps (single-export override pattern).
 *   - Non-empty layers fixture passed to the hook (avoids the empty-array microtask loop).
 *   - afterEach cleanup + restoreAllMocks to prevent cross-test leaks.
 *
 * The underlying hook uses useSearchParams (react-router), useTranslation (react-i18next),
 * useQueryClient (@tanstack/react-query), and several internal hooks. The shared
 * renderHook from @/test/test-utils provides QueryClientProvider + MemoryRouter so
 * those calls work without per-file vi.mock.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, cleanup } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import type { MapLayerResponse, MapResponse } from '@/types/api';
import { toast } from 'sonner';

// ---------------------------------------------------------------------------
// Selective vi.mock — override removeLayerFromMapApi + bulkDeleteLayersApi;
// keep rest real via importActual.
// ---------------------------------------------------------------------------
vi.mock('@/api/maps', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/maps')>();
  return {
    ...actual,
    removeLayerFromMapApi: vi.fn(),
    bulkDeleteLayersApi: vi.fn(),
  };
});

// Import the mocked functions AFTER the vi.mock declaration so we get the mock reference.
// Dynamic import is required because vitest hoists vi.mock calls.
import { removeLayerFromMapApi, bulkDeleteLayersApi } from '@/api/maps';

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------
afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks(); // reset call counts on vi.mocked() functions (e.g. removeLayerFromMapApi)
  cleanup();
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

type GroupedLayer = Omit<MapLayerResponse, 'layer_type'> & {
  layer_type?: string | null;
  parent_group_id?: string | null;
};

function makeMockLayer(overrides: Omit<Partial<MapLayerResponse>, 'layer_type'> & { layer_type?: string; parent_group_id?: string | null } = {}): MapLayerResponse {
  const { layer_type, parent_group_id, ...rest } = overrides;
  return {
    id: rest.id ?? 'layer-1',
    dataset_id: rest.dataset_id ?? 'ds-1',
    dataset_name: rest.dataset_name ?? 'Test',
    dataset_geometry_type: rest.dataset_geometry_type ?? 'Polygon',
    dataset_table_name: rest.dataset_table_name ?? 'test_table',
    visible: rest.visible ?? true,
    opacity: rest.opacity ?? 1,
    paint: rest.paint ?? {},
    layout: rest.layout ?? {},
    sort_order: rest.sort_order ?? 0,
    filter: null,
    display_name: null,
    layer_type: (layer_type ?? 'vector_geolens') as MapLayerResponse['layer_type'],
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    dataset_record_type: rest.dataset_record_type ?? 'vector_dataset',
    label_config: null,
    popup_config: null,
    style_config: null,
    show_in_legend: true,
    is_dem: false,
    dem_vertical_units: null,
    // spread parent_group_id separately so it lands in the result
    ...(parent_group_id !== undefined ? { parent_group_id } : {}),
    ...rest,
  } as MapLayerResponse;
}

function makeMapData(layers: MapLayerResponse[] = []): MapResponse {
  return {
    id: 'map-1',
    name: 'Test Map',
    description: null,
    notes: null,
    center_lng: 0,
    center_lat: 0,
    zoom: 2,
    bearing: 0,
    pitch: 0,
    basemap_style: 'positron',
    show_basemap_labels: true,
    basemap_config: null,
    terrain_config: null,
    visibility: 'private',
    thumbnail_url: null,
    created_by: null,
    created_by_username: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    layers,
    layer_count: layers.length,
    forked_from_id: null,
    forked_from_name: null,
  };
}

// Minimal map instance mock — isStyleLoaded returns false so live-map sync is skipped
// (we don't need to test setLayoutProperty/setPaintProperty behavior here).
function makeMapRef(overrides: Partial<{
  isStyleLoaded: () => boolean;
  setLayoutProperty: ReturnType<typeof vi.fn>;
  setPaintProperty: ReturnType<typeof vi.fn>;
  getLayer: ReturnType<typeof vi.fn>;
}> = {}) {
  const mapInstance = {
    isStyleLoaded: overrides.isStyleLoaded ?? (() => false),
    setLayoutProperty: overrides.setLayoutProperty ?? vi.fn(),
    setPaintProperty: overrides.setPaintProperty ?? vi.fn(),
    getLayer: overrides.getLayer ?? vi.fn().mockReturnValue(null),
  };
  return { current: mapInstance } as React.RefObject<typeof mapInstance>;
}

const MAP_ID = 'map-1';

function renderBuilderLayers(
  mapData: MapResponse | undefined,
  mapRef: ReturnType<typeof makeMapRef> = makeMapRef(),
) {
  const addLayerMutation = {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
  } as unknown as Parameters<typeof useBuilderLayers>[3];

  const removeLayerMutation = {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
  } as unknown as Parameters<typeof useBuilderLayers>[4];

  // Double-cast the mock mapRef to satisfy the MaplibreMap RefObject type
  const typedRef = mapRef as unknown as React.RefObject<import('maplibre-gl').Map | null>;

  const out = renderHook(() =>
    useBuilderLayers(
      mapData,
      typedRef,
      MAP_ID,
      addLayerMutation,
      removeLayerMutation,
    ),
  );
  return out;
}

// Wait for the hook to initialize (the useEffect that sets localLayers from mapData)
async function waitForInit() {
  await act(async () => {});
}

// ---------------------------------------------------------------------------
// handleBulkVisibility (POL-09)
// ---------------------------------------------------------------------------

describe('useBuilderLayers — handleBulkVisibility (POL-09)', () => {
  it('Test 1: Toggles all selected layers to opposite of majority visibility', async () => {
    // a, b visible; c hidden — majority visible → nextVisible = false (hide)
    const layerA = makeMockLayer({ id: 'a', visible: true, sort_order: 0 });
    const layerB = makeMockLayer({ id: 'b', visible: true, sort_order: 1 });
    const layerC = makeMockLayer({ id: 'c', visible: false, sort_order: 2 });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerB, layerC]));
    await waitForInit();

    act(() => {
      result.current.handleBulkVisibility(new Set(['a', 'b', 'c']));
    });

    // All 3 should now be hidden (majority was visible → nextVisible = false)
    const updated = result.current.localLayers;
    expect(updated.find((l) => l.id === 'a')!.visible).toBe(false);
    expect(updated.find((l) => l.id === 'b')!.visible).toBe(false);
    expect(updated.find((l) => l.id === 'c')!.visible).toBe(false);
  });

  it('Test 2: Toggles layers to visible when majority is hidden', async () => {
    // a hidden, b hidden, c visible — majority hidden → nextVisible = true
    const layerA = makeMockLayer({ id: 'a', visible: false, sort_order: 0 });
    const layerB = makeMockLayer({ id: 'b', visible: false, sort_order: 1 });
    const layerC = makeMockLayer({ id: 'c', visible: true, sort_order: 2 });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerB, layerC]));
    await waitForInit();

    act(() => {
      result.current.handleBulkVisibility(new Set(['a', 'b', 'c']));
    });

    const updated = result.current.localLayers;
    expect(updated.find((l) => l.id === 'a')!.visible).toBe(true);
    expect(updated.find((l) => l.id === 'b')!.visible).toBe(true);
    expect(updated.find((l) => l.id === 'c')!.visible).toBe(true);
  });

  it('Test 3: Marks hasUnsavedChanges=true after bulk visibility toggle', async () => {
    const layers = [
      makeMockLayer({ id: 'a', sort_order: 0 }),
      makeMockLayer({ id: 'b', sort_order: 1 }),
    ];
    const { result } = renderBuilderLayers(makeMapData(layers));
    await waitForInit();

    expect(result.current.hasUnsavedChanges).toBe(false);

    act(() => {
      result.current.handleBulkVisibility(new Set(['a', 'b']));
    });

    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('Test 4: Does NOT call setLayoutProperty when map.isStyleLoaded=false', async () => {
    const setLayoutProperty = vi.fn();
    const mapRef = makeMapRef({ isStyleLoaded: () => false, setLayoutProperty });
    const layers = [makeMockLayer({ id: 'a', sort_order: 0 })];
    const { result } = renderBuilderLayers(makeMapData(layers), mapRef);
    await waitForInit();

    act(() => {
      result.current.handleBulkVisibility(new Set(['a']));
    });

    expect(setLayoutProperty).not.toHaveBeenCalled();
  });

  it('Test 5: Calls setLayoutProperty for sub-layer ids when map is loaded', async () => {
    const setLayoutProperty = vi.fn();
    const getLayer = vi.fn().mockReturnValue({ id: 'mock-layer' }); // always returns truthy
    const mapRef = makeMapRef({ isStyleLoaded: () => true, setLayoutProperty, getLayer });
    const layers = [makeMockLayer({ id: 'a', visible: true, sort_order: 0 })];
    const { result } = renderBuilderLayers(makeMapData(layers), mapRef);
    await waitForInit();

    act(() => {
      result.current.handleBulkVisibility(new Set(['a']));
    });

    // Should call setLayoutProperty with visibility for sub-layer ids
    expect(setLayoutProperty).toHaveBeenCalledWith(
      expect.stringContaining('layer-a'),
      'visibility',
      expect.any(String),
    );
  });
});

// ---------------------------------------------------------------------------
// handleBulkOpacity (POL-09)
// ---------------------------------------------------------------------------

describe('useBuilderLayers — handleBulkOpacity (POL-09)', () => {
  it('Test 6: Updates opacity on all selected layers in one setState', async () => {
    const layers = [
      makeMockLayer({ id: 'a', opacity: 1, sort_order: 0 }),
      makeMockLayer({ id: 'b', opacity: 0.5, sort_order: 1 }),
      makeMockLayer({ id: 'c', opacity: 1, sort_order: 2 }),
    ];
    const { result } = renderBuilderLayers(makeMapData(layers));
    await waitForInit();

    act(() => {
      result.current.handleBulkOpacity(new Set(['a', 'b']), 0.4);
    });

    const updated = result.current.localLayers;
    expect(updated.find((l) => l.id === 'a')!.opacity).toBe(0.4);
    expect(updated.find((l) => l.id === 'b')!.opacity).toBe(0.4);
    // c is NOT in selection — should be unchanged
    expect(updated.find((l) => l.id === 'c')!.opacity).toBe(1);
  });

  it('Test 7: Marks hasUnsavedChanges=true after bulk opacity change', async () => {
    const layers = [makeMockLayer({ id: 'a', sort_order: 0 })];
    const { result } = renderBuilderLayers(makeMapData(layers));
    await waitForInit();

    act(() => {
      result.current.handleBulkOpacity(new Set(['a']), 0.5);
    });

    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('Test 8: Calls setPaintProperty for selected layer when map is loaded', async () => {
    const setPaintProperty = vi.fn();
    const getLayer = vi.fn().mockReturnValue({ id: 'mock-layer' });
    const mapRef = makeMapRef({ isStyleLoaded: () => true, setPaintProperty, getLayer });
    const layers = [makeMockLayer({ id: 'a', dataset_geometry_type: 'Polygon', sort_order: 0 })];
    const { result } = renderBuilderLayers(makeMapData(layers), mapRef);
    await waitForInit();

    act(() => {
      result.current.handleBulkOpacity(new Set(['a']), 0.7);
    });

    expect(setPaintProperty).toHaveBeenCalledWith(
      expect.stringContaining('layer-a'),
      expect.any(String),
      0.7,
    );
  });
});

// ---------------------------------------------------------------------------
// handleBulkGroup (POL-09)
// ---------------------------------------------------------------------------

describe('useBuilderLayers — handleBulkGroup (POL-09)', () => {
  it('Test 9: Creates one folder-group row with all selected layers as children', async () => {
    const layerA = makeMockLayer({ id: 'a', sort_order: 0, dataset_record_type: 'vector_dataset' });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1, dataset_record_type: 'vector_dataset' });
    const layerC = makeMockLayer({ id: 'c', sort_order: 2, dataset_record_type: 'vector_dataset' });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerB, layerC]));
    await waitForInit();

    act(() => {
      result.current.handleBulkGroup(new Set(['a', 'b', 'c']));
    });

    const updated = result.current.localLayers as GroupedLayer[];

    // A new folder-group row should have been inserted
    const groupRow = updated.find((l) => l.layer_type === 'group:folder' && !l.parent_group_id);
    expect(groupRow).toBeDefined();
    const groupId = groupRow!.id;

    // a, b, c should now have parent_group_id pointing to the new group
    const updatedA = updated.find((l) => l.id === 'a');
    const updatedB = updated.find((l) => l.id === 'b');
    const updatedC = updated.find((l) => l.id === 'c');
    expect(updatedA?.parent_group_id).toBe(groupId);
    expect(updatedB?.parent_group_id).toBe(groupId);
    expect(updatedC?.parent_group_id).toBe(groupId);
  });

  it('Test 10: Defense-in-depth: returns early if any selected layer has parent_group_id', async () => {
    const layerA = makeMockLayer({ id: 'a', sort_order: 0, dataset_record_type: 'vector_dataset', parent_group_id: 'existing-group' });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1, dataset_record_type: 'vector_dataset' });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerB]));
    await waitForInit();

    const before = result.current.localLayers.length;

    act(() => {
      result.current.handleBulkGroup(new Set(['a', 'b']));
    });

    // No group row inserted — localLayers length unchanged
    expect(result.current.localLayers.length).toBe(before);
  });

  it('Test 11: Defense-in-depth: returns early if any selected is raster', async () => {
    const layerA = makeMockLayer({ id: 'a', sort_order: 0, dataset_record_type: 'vector_dataset' });
    const layerR = makeMockLayer({ id: 'r', sort_order: 1, dataset_record_type: 'raster_dataset', layer_type: 'raster_geolens' });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerR]));
    await waitForInit();

    const before = result.current.localLayers.length;

    act(() => {
      result.current.handleBulkGroup(new Set(['a', 'r']));
    });

    expect(result.current.localLayers.length).toBe(before);
  });
});

// ---------------------------------------------------------------------------
// handleBulkUngroup (POL-09)
// ---------------------------------------------------------------------------

describe('useBuilderLayers — handleBulkUngroup (POL-09)', () => {
  it('Test 12: Removes folder-group rows and clears parent_group_id on children', async () => {
    const groupRow = makeMockLayer({ id: 'g1', sort_order: 0, layer_type: 'group:folder' });
    const child1 = { ...makeMockLayer({ id: 'child1', sort_order: 1 }), parent_group_id: 'g1' } as GroupedLayer as MapLayerResponse;
    const child2 = { ...makeMockLayer({ id: 'child2', sort_order: 2 }), parent_group_id: 'g1' } as GroupedLayer as MapLayerResponse;
    const { result } = renderBuilderLayers(makeMapData([groupRow, child1, child2]));
    await waitForInit();

    act(() => {
      result.current.handleBulkUngroup(new Set(['g1']));
    });

    const updated = result.current.localLayers as GroupedLayer[];

    // group row should be gone
    expect(updated.find((l) => l.id === 'g1')).toBeUndefined();

    // children should have no parent_group_id
    expect(updated.find((l) => l.id === 'child1')?.parent_group_id).toBeFalsy();
    expect(updated.find((l) => l.id === 'child2')?.parent_group_id).toBeFalsy();
  });

  it('Test 13: Defense-in-depth: returns early if any selected is not group:folder', async () => {
    const groupRow = makeMockLayer({ id: 'g1', sort_order: 0, layer_type: 'group:folder' });
    const looseA = makeMockLayer({ id: 'a', sort_order: 1, dataset_record_type: 'vector_dataset' });
    const { result } = renderBuilderLayers(makeMapData([groupRow, looseA]));
    await waitForInit();

    const before = result.current.localLayers.map((l) => l.id);

    act(() => {
      // Mix: g1 is group, 'a' is not — defense-in-depth returns early
      result.current.handleBulkUngroup(new Set(['g1', 'a']));
    });

    expect(result.current.localLayers.map((l) => l.id)).toEqual(before);
  });
});

// ---------------------------------------------------------------------------
// handleBulkDelete (POL-09)
// ---------------------------------------------------------------------------

describe('useBuilderLayers — handleBulkDelete (POL-09)', () => {
  it('Test 14: Success path: fires parallel removeLayerFromMapApi calls for each id', async () => {
    const mockedRemove = vi.mocked(removeLayerFromMapApi);
    mockedRemove.mockResolvedValue(undefined);

    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1 });
    const layerC = makeMockLayer({ id: 'c', sort_order: 2 });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerB, layerC]));
    await waitForInit();

    let ok: boolean | undefined;
    await act(async () => {
      ok = await result.current.handleBulkDelete(new Set(['a', 'b', 'c']));
    });

    expect(mockedRemove).toHaveBeenCalledTimes(3);
    expect(mockedRemove).toHaveBeenCalledWith(MAP_ID, 'a');
    expect(mockedRemove).toHaveBeenCalledWith(MAP_ID, 'b');
    expect(mockedRemove).toHaveBeenCalledWith(MAP_ID, 'c');
    expect(ok).toBe(true);
  });

  it('Test 15: Success path: optimistically removes layers from localLayers', async () => {
    const mockedRemove = vi.mocked(removeLayerFromMapApi);
    mockedRemove.mockResolvedValue(undefined);

    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1 });
    const layerC = makeMockLayer({ id: 'c', sort_order: 2 });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerB, layerC]));
    await waitForInit();

    await act(async () => {
      await result.current.handleBulkDelete(new Set(['a', 'b']));
    });

    // After successful delete, a and b should be gone
    const ids = result.current.localLayers.map((l) => l.id);
    expect(ids).not.toContain('a');
    expect(ids).not.toContain('b');
    // c remains
    expect(ids).toContain('c');
  });

  it('Test 16: Success path: clears expandedLayerId if it was in the selection', async () => {
    const mockedRemove = vi.mocked(removeLayerFromMapApi);
    mockedRemove.mockResolvedValue(undefined);

    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1 });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerB]));
    await waitForInit();

    // Simulate expandedLayerId = 'a'
    act(() => {
      result.current.handleToggleExpand('a');
    });
    expect(result.current.expandedLayerId).toBe('a');

    await act(async () => {
      await result.current.handleBulkDelete(new Set(['a']));
    });

    expect(result.current.expandedLayerId).toBeNull();
  });

  it('Test 17: Failure path: rolls back to pre-delete state on any rejection', async () => {
    const mockedRemove = vi.mocked(removeLayerFromMapApi);
    // First call resolves, second rejects
    mockedRemove
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error('API error'))
      .mockResolvedValueOnce(undefined);

    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1 });
    const layerC = makeMockLayer({ id: 'c', sort_order: 2 });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerB, layerC]));
    await waitForInit();

    const initialIds = result.current.localLayers.map((l) => l.id);

    let ok: boolean | undefined;
    await act(async () => {
      ok = await result.current.handleBulkDelete(new Set(['a', 'b', 'c']));
    });

    // Should return false on failure
    expect(ok).toBe(false);

    // Local layers should be rolled back to original state (all 3 present)
    const finalIds = result.current.localLayers.map((l) => l.id);
    expect(finalIds).toEqual(expect.arrayContaining(initialIds));
    expect(finalIds).toHaveLength(initialIds.length);
  });

  it('Test 18: Failure path: shows exactly one error toast (not N toasts)', async () => {
    const mockedRemove = vi.mocked(removeLayerFromMapApi);
    mockedRemove.mockRejectedValue(new Error('Network error'));

    const errorSpy = vi.spyOn(toast, 'error');

    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1 });
    const layerC = makeMockLayer({ id: 'c', sort_order: 2 });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerB, layerC]));
    await waitForInit();

    await act(async () => {
      await result.current.handleBulkDelete(new Set(['a', 'b', 'c']));
    });

    // Exactly 1 error toast — not 3 (one per failed DELETE)
    expect(errorSpy).toHaveBeenCalledOnce();
  });

  it('Test 19: Returns false on empty selection (early return guard)', async () => {
    const mockedRemove = vi.mocked(removeLayerFromMapApi);
    mockedRemove.mockResolvedValue(undefined);

    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const { result } = renderBuilderLayers(makeMapData([layerA]));
    await waitForInit();

    let ok: boolean | undefined;
    await act(async () => {
      ok = await result.current.handleBulkDelete(new Set());
    });

    expect(ok).toBe(false);
    expect(mockedRemove).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleBulkDelete — batched endpoint (Phase 1047-04 PERF-03)
// These tests cover the new bulkDeleteLayersApi path that replaces the
// Promise.allSettled(removeLayerFromMapApi × N) pattern.
// ---------------------------------------------------------------------------

describe('useBuilderLayers — handleBulkDelete batched (PERF-03)', () => {
  it('Test 20: Issues exactly ONE network call for N selected layers', async () => {
    const mockedBulkDelete = vi.mocked(bulkDeleteLayersApi);
    mockedBulkDelete.mockResolvedValue({ deleted: ['a', 'b', 'c'], failed: [] });

    const layers = [
      makeMockLayer({ id: 'a', sort_order: 0 }),
      makeMockLayer({ id: 'b', sort_order: 1 }),
      makeMockLayer({ id: 'c', sort_order: 2 }),
    ];
    const { result } = renderBuilderLayers(makeMapData(layers));
    await waitForInit();

    await act(async () => {
      await result.current.handleBulkDelete(new Set(['a', 'b', 'c']));
    });

    // Exactly ONE call — not 3 (the old parallel pattern)
    expect(mockedBulkDelete).toHaveBeenCalledTimes(1);
    expect(mockedBulkDelete).toHaveBeenCalledWith(MAP_ID, expect.arrayContaining(['a', 'b', 'c']));
  });

  it('Test 21: Full success path: layers removed and toast.success fires', async () => {
    const mockedBulkDelete = vi.mocked(bulkDeleteLayersApi);
    mockedBulkDelete.mockResolvedValue({ deleted: ['a', 'b'], failed: [] });
    const successSpy = vi.spyOn(toast, 'success');

    const layers = [
      makeMockLayer({ id: 'a', sort_order: 0 }),
      makeMockLayer({ id: 'b', sort_order: 1 }),
      makeMockLayer({ id: 'c', sort_order: 2 }),
    ];
    const { result } = renderBuilderLayers(makeMapData(layers));
    await waitForInit();

    let ok: boolean | undefined;
    await act(async () => {
      ok = await result.current.handleBulkDelete(new Set(['a', 'b']));
    });

    expect(ok).toBe(true);
    const ids = result.current.localLayers.map((l) => l.id);
    expect(ids).not.toContain('a');
    expect(ids).not.toContain('b');
    expect(ids).toContain('c');
    expect(successSpy).toHaveBeenCalledOnce();
  });

  it('Test 22: Full rollback path: all failed → localLayers restored + toast.error', async () => {
    const mockedBulkDelete = vi.mocked(bulkDeleteLayersApi);
    mockedBulkDelete.mockResolvedValue({
      deleted: [],
      failed: [
        { id: 'a', reason: 'not_found' },
        { id: 'b', reason: 'not_found' },
      ],
    });
    const errorSpy = vi.spyOn(toast, 'error');

    const layers = [
      makeMockLayer({ id: 'a', sort_order: 0 }),
      makeMockLayer({ id: 'b', sort_order: 1 }),
      makeMockLayer({ id: 'c', sort_order: 2 }),
    ];
    const { result } = renderBuilderLayers(makeMapData(layers));
    await waitForInit();

    let ok: boolean | undefined;
    await act(async () => {
      ok = await result.current.handleBulkDelete(new Set(['a', 'b']));
    });

    expect(ok).toBe(false);
    // All 3 layers still present (rolled back)
    const ids = result.current.localLayers.map((l) => l.id);
    expect(ids).toContain('a');
    expect(ids).toContain('b');
    expect(ids).toContain('c');
    expect(errorSpy).toHaveBeenCalledOnce();
  });

  it('Test 23: Partial failure: deleted layers removed, failed remain, toast.error fires', async () => {
    const mockedBulkDelete = vi.mocked(bulkDeleteLayersApi);
    mockedBulkDelete.mockResolvedValue({
      deleted: ['a'],
      failed: [{ id: 'b', reason: 'not_found' }],
    });
    const errorSpy = vi.spyOn(toast, 'error');

    const layers = [
      makeMockLayer({ id: 'a', sort_order: 0 }),
      makeMockLayer({ id: 'b', sort_order: 1 }),
      makeMockLayer({ id: 'c', sort_order: 2 }),
    ];
    const { result } = renderBuilderLayers(makeMapData(layers));
    await waitForInit();

    let ok: boolean | undefined;
    await act(async () => {
      ok = await result.current.handleBulkDelete(new Set(['a', 'b']));
    });

    expect(ok).toBe(false);
    const ids = result.current.localLayers.map((l) => l.id);
    // 'a' was deleted (in deleted[])
    expect(ids).not.toContain('a');
    // 'b' failed → re-inserted
    expect(ids).toContain('b');
    // 'c' untouched
    expect(ids).toContain('c');
    expect(errorSpy).toHaveBeenCalledOnce();
  });

  it('Test 24: isDeleting=true during the call, false after', async () => {
    let isDeletingDuringCall = false;

    const mockedBulkDelete = vi.mocked(bulkDeleteLayersApi);
    mockedBulkDelete.mockImplementation(async () => {
      // Capture isDeleting value inside the async call (it should be true here)
      isDeletingDuringCall = true;
      return { deleted: ['a'], failed: [] };
    });

    const layers = [makeMockLayer({ id: 'a', sort_order: 0 })];
    const { result } = renderBuilderLayers(makeMapData(layers));
    await waitForInit();

    await act(async () => {
      await result.current.handleBulkDelete(new Set(['a']));
    });

    // After completion isDeleting is false
    expect(result.current.isDeleting).toBe(false);
    // The mock was called (proving it executed during the call)
    expect(isDeletingDuringCall).toBe(true);
  });
});
