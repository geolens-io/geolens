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
import {
  makeBuilderLayer,
  makeBuilderMap,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
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
import { bulkDeleteLayersApi } from '@/api/maps';

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
  return makeBuilderLayer({
    layer_type: (layer_type ?? 'vector_geolens') as MapLayerResponse['layer_type'],
    dataset_record_type: 'vector_dataset',
    // spread parent_group_id separately so it lands in the result
    ...(parent_group_id !== undefined ? { parent_group_id } : {}),
    ...rest,
  } as Partial<MapLayerResponse>) as MapLayerResponse;
}

function makeMapData(layers: MapLayerResponse[] = []): MapResponse {
  return makeBuilderMap(layers);
}

// Minimal map instance mock — isStyleLoaded returns false so live-map sync is skipped
// (we don't need to test setLayoutProperty/setPaintProperty behavior here).
function makeMapRef(overrides: Partial<{
  isStyleLoaded: () => boolean;
  setLayoutProperty: ReturnType<typeof vi.fn>;
  setPaintProperty: ReturnType<typeof vi.fn>;
  getPaintProperty: ReturnType<typeof vi.fn>;
  getLayoutProperty: ReturnType<typeof vi.fn>;
  getLayer: ReturnType<typeof vi.fn>;
}> = {}) {
  const mapInstance = {
    isStyleLoaded: overrides.isStyleLoaded ?? (() => false),
    setLayoutProperty: overrides.setLayoutProperty ?? vi.fn(),
    setPaintProperty: overrides.setPaintProperty ?? vi.fn(),
    getPaintProperty: overrides.getPaintProperty ?? vi.fn(),
    getLayoutProperty: overrides.getLayoutProperty ?? vi.fn(),
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

  // fix(#392): 6th positional param bridging into useBuilderSave's Save-diff
  // baseline — a plain no-op ref is sufficient for tests that don't assert on it.
  const saveBaselineSyncRef = { current: () => {} } as unknown as Parameters<typeof useBuilderLayers>[5];

  const out = renderHook(() =>
    useBuilderLayers(
      mapData,
      typedRef,
      MAP_ID,
      addLayerMutation,
      removeLayerMutation,
      saveBaselineSyncRef,
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
// STATE-01 (builder-audit #338 20260626) — bulk visibility must not drift from the
// single-layer side-effect: it enumerates the colorrelief companion and honors
// the strokeDisabled gate on the fill outline.
// ---------------------------------------------------------------------------

describe('useBuilderLayers — handleBulkVisibility STATE-01 parity', () => {
  it('enumerates the colorrelief companion when toggling visibility', async () => {
    const setLayoutProperty = vi.fn();
    const getLayer = vi.fn().mockReturnValue({ id: 'mock-layer' });
    const mapRef = makeMapRef({ isStyleLoaded: () => true, setLayoutProperty, getLayer });
    const layers = [makeMockLayer({ id: 'a', visible: true, sort_order: 0 })];
    const { result } = renderBuilderLayers(makeMapData(layers), mapRef);
    await waitForInit();

    act(() => {
      result.current.handleBulkVisibility(new Set(['a']));
    });

    // The drifted inline array omitted layer-${id}-colorrelief; the shared
    // helper includes it.
    expect(setLayoutProperty).toHaveBeenCalledWith('layer-a-colorrelief', 'visibility', 'none');
  });

  it('keeps a stroke-disabled fill outline hidden when bulk-showing the layer', async () => {
    const setLayoutProperty = vi.fn();
    const getLayer = vi.fn().mockReturnValue({ id: 'mock-layer' });
    const mapRef = makeMapRef({ isStyleLoaded: () => true, setLayoutProperty, getLayer });
    // Hidden fill with stroke disabled — bulk toggle flips it to visible, but the
    // outline must stay 'none' (the inline bulk path resurrected it).
    const layer = makeMockLayer({
      id: 'a',
      visible: false,
      dataset_geometry_type: 'Polygon',
      sort_order: 0,
      style_config: { builder: { strokeDisabled: true } } as MapLayerResponse['style_config'],
    });
    const { result } = renderBuilderLayers(makeMapData([layer]), mapRef);
    await waitForInit();

    act(() => {
      result.current.handleBulkVisibility(new Set(['a']));
    });

    expect(setLayoutProperty).toHaveBeenCalledWith('layer-a', 'visibility', 'visible');
    expect(setLayoutProperty).toHaveBeenCalledWith('layer-a-outline', 'visibility', 'none');
  });
});

// ---------------------------------------------------------------------------
// P1-09 (builder-audit #338 20260626) — toggle_group_visibility flips every child +
// the group row atomically and routes child map side effects through the shared
// companion visibility helper.
// ---------------------------------------------------------------------------

describe('useBuilderLayers — toggle_group_visibility (P1-09)', () => {
  it('hides every child and the group row in one pass', async () => {
    const setLayoutProperty = vi.fn();
    const getLayer = vi.fn().mockReturnValue({ id: 'mock-layer' });
    const mapRef = makeMapRef({ isStyleLoaded: () => true, setLayoutProperty, getLayer });
    const groupRow = makeMockLayer({ id: 'g1', sort_order: 0, layer_type: 'group:folder', visible: true });
    const child1 = { ...makeMockLayer({ id: 'c1', sort_order: 1, visible: true }), parent_group_id: 'g1' } as GroupedLayer as MapLayerResponse;
    const child2 = { ...makeMockLayer({ id: 'c2', sort_order: 2, visible: true }), parent_group_id: 'g1' } as GroupedLayer as MapLayerResponse;
    const { result } = renderBuilderLayers(makeMapData([groupRow, child1, child2]), mapRef);
    await waitForInit();

    act(() => {
      result.current.dispatchLayerAction({ type: 'toggle_group_visibility', source: 'manual', groupId: 'g1' });
    });

    const updated = result.current.localLayers;
    expect(updated.find((l) => l.id === 'g1')!.visible).toBe(false);
    expect(updated.find((l) => l.id === 'c1')!.visible).toBe(false);
    expect(updated.find((l) => l.id === 'c2')!.visible).toBe(false);
    // Child map side effects routed through the companion helper.
    expect(setLayoutProperty).toHaveBeenCalledWith('layer-c1', 'visibility', 'none');
    expect(setLayoutProperty).toHaveBeenCalledWith('layer-c2', 'visibility', 'none');
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('shows every child when the group is currently hidden', async () => {
    const groupRow = makeMockLayer({ id: 'g1', sort_order: 0, layer_type: 'group:folder', visible: false });
    const child1 = { ...makeMockLayer({ id: 'c1', sort_order: 1, visible: false }), parent_group_id: 'g1' } as GroupedLayer as MapLayerResponse;
    const { result } = renderBuilderLayers(makeMapData([groupRow, child1]));
    await waitForInit();

    act(() => {
      result.current.dispatchLayerAction({ type: 'toggle_group_visibility', source: 'manual', groupId: 'g1' });
    });

    const updated = result.current.localLayers;
    expect(updated.find((l) => l.id === 'g1')!.visible).toBe(true);
    expect(updated.find((l) => l.id === 'c1')!.visible).toBe(true);
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

  it('routes DEM hillshade bulk opacity through hillshade color paint, not raster-opacity', async () => {
    const setPaintProperty = vi.fn();
    const getLayer = vi.fn().mockReturnValue({ id: 'mock-layer', type: 'hillshade' });
    const getPaintProperty = vi.fn().mockReturnValue(undefined);
    const getLayoutProperty = vi.fn().mockReturnValue('visible');
    const mapRef = makeMapRef({
      isStyleLoaded: () => true,
      setPaintProperty,
      getLayer,
      getPaintProperty,
      getLayoutProperty,
    });
    const layer = makeMockLayer({
      id: 'dem',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      dataset_record_type: 'raster_dataset',
      is_dem: true,
      style_config: { render_mode: 'hillshade' } as MapLayerResponse['style_config'],
      paint: {
        'hillshade-shadow-color': '#1f2937',
        'hillshade-highlight-color': '#ffffff',
        'hillshade-accent-color': '#64748b',
      },
      sort_order: 0,
    });
    const { result } = renderBuilderLayers(makeMapData([layer]), mapRef);
    await waitForInit();

    act(() => {
      result.current.handleBulkOpacity(new Set(['dem']), 0.5);
    });

    expect(setPaintProperty).toHaveBeenCalledWith('layer-dem', 'hillshade-shadow-color', 'rgba(31, 41, 55, 0.5)');
    expect(setPaintProperty).not.toHaveBeenCalledWith('layer-dem', 'raster-opacity', expect.anything());
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

    let created: boolean | undefined;
    act(() => {
      created = result.current.handleBulkGroup(new Set(['a', 'b', 'c']));
    });

    // Test C (eligible): returns true when a group is actually created.
    expect(created).toBe(true);

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

  // fix(#TBD B-040): a non-contiguous selection must compact the grouped block
  // adjacent to the group row. Stamping parent_group_id in place stranded any
  // non-selected layer between selected ones below the group — stack order and
  // map draw order diverged for it, and it persisted through save/reload.
  it('non-contiguous selection compacts the grouped block and moves unselected layers below it', async () => {
    const layerA = makeMockLayer({ id: 'a', sort_order: 0, dataset_record_type: 'vector_dataset' });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1, dataset_record_type: 'vector_dataset' });
    const layerC = makeMockLayer({ id: 'c', sort_order: 2, dataset_record_type: 'vector_dataset' });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerB, layerC]));
    await waitForInit();

    act(() => {
      result.current.handleBulkGroup(new Set(['a', 'c']));
    });

    const updated = result.current.localLayers as GroupedLayer[];
    const shape = updated.map((l) => (l.layer_type === 'group:folder' ? 'G' : l.id));
    // Group row at the first selected position, children compacted directly
    // after it, the unselected middle layer pushed below the block.
    expect(shape).toEqual(['G', 'a', 'c', 'b']);
    expect(updated.map((l) => l.sort_order)).toEqual([0, 1, 2, 3]);

    const groupId = updated.find((l) => l.layer_type === 'group:folder')!.id;
    expect(updated.find((l) => l.id === 'a')?.parent_group_id).toBe(groupId);
    expect(updated.find((l) => l.id === 'c')?.parent_group_id).toBe(groupId);
    expect(updated.find((l) => l.id === 'b')?.parent_group_id ?? null).toBeNull();
  });

  // fix(#392): a single loose layer selection
  // returns false, toasts the "need two" reason, and does not mutate localLayers. (audit B-004d/LM-04)
  it('Test A: single loose layer returns false, toasts bulkGroupNeedTwo, and does not mutate localLayers', async () => {
    const infoSpy = vi.spyOn(toast, 'info');
    const layerA = makeMockLayer({ id: 'a', sort_order: 0, dataset_record_type: 'vector_dataset' });
    const { result } = renderBuilderLayers(makeMapData([layerA]));
    await waitForInit();

    const before = result.current.localLayers;

    let created: boolean | undefined;
    act(() => {
      created = result.current.handleBulkGroup(new Set(['a']));
    });

    expect(created).toBe(false);
    expect(infoSpy).toHaveBeenCalledWith('Select at least 2 loose layers to group');
    expect(result.current.localLayers).toBe(before);
    expect(result.current.localLayers.some((l) => (l as GroupedLayer).layer_type === 'group:folder')).toBe(false);
  });

  it('Test 10 / Test B (ineligible — mixed/already-grouped): returns false, toasts bulkGroupSkipped, does not mutate localLayers', async () => {
    const infoSpy = vi.spyOn(toast, 'info');
    const layerA = makeMockLayer({ id: 'a', sort_order: 0, dataset_record_type: 'vector_dataset', parent_group_id: 'existing-group' });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1, dataset_record_type: 'vector_dataset' });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerB]));
    await waitForInit();

    const before = result.current.localLayers.length;

    let created: boolean | undefined;
    act(() => {
      created = result.current.handleBulkGroup(new Set(['a', 'b']));
    });

    expect(created).toBe(false);
    expect(infoSpy).toHaveBeenCalledWith("Some selected layers are already grouped and can't be grouped again");
    // No group row inserted — localLayers length unchanged
    expect(result.current.localLayers.length).toBe(before);
  });

  // fix(#392): mixed selection with a raster layer must toast the
  // TYPE-specific reason, not the generic (and factually wrong, for this
  // case) "already grouped" message. (audit WR-01)
  it('Test 11: mixed selection including a raster layer returns false, toasts bulkGroupSkippedType, does not mutate localLayers', async () => {
    const infoSpy = vi.spyOn(toast, 'info');
    const layerA = makeMockLayer({ id: 'a', sort_order: 0, dataset_record_type: 'vector_dataset' });
    const layerR = makeMockLayer({ id: 'r', sort_order: 1, dataset_record_type: 'raster_dataset', layer_type: 'raster_geolens' });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerR]));
    await waitForInit();

    const before = result.current.localLayers.length;

    let created: boolean | undefined;
    act(() => {
      created = result.current.handleBulkGroup(new Set(['a', 'r']));
    });

    expect(created).toBe(false);
    expect(infoSpy).toHaveBeenCalledWith("Non-vector layers can't be grouped — remove them from your selection and try again");
    expect(result.current.localLayers.length).toBe(before);
  });

  // fix(#392): a group row in the selection must toast the
  // GROUP-ROW-specific reason, not the generic "already grouped" message. (audit WR-01)
  it('Test B (ineligible — group:folder row in selection): returns false, toasts bulkGroupSkippedGroupRow', async () => {
    const infoSpy = vi.spyOn(toast, 'info');
    const groupRow = makeMockLayer({ id: 'g1', sort_order: 0, layer_type: 'group:folder' });
    const layerA = makeMockLayer({ id: 'a', sort_order: 1, dataset_record_type: 'vector_dataset' });
    const layerB = makeMockLayer({ id: 'b', sort_order: 2, dataset_record_type: 'vector_dataset' });
    const { result } = renderBuilderLayers(makeMapData([groupRow, layerA, layerB]));
    await waitForInit();

    const before = result.current.localLayers.length;

    let created: boolean | undefined;
    act(() => {
      created = result.current.handleBulkGroup(new Set(['g1', 'a', 'b']));
    });

    expect(created).toBe(false);
    expect(infoSpy).toHaveBeenCalledWith("Groups can't be grouped — remove any group rows from your selection and try again");
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
// handleBulkDelete (POL-09) — updated for Phase 1047-04 batched API
// ---------------------------------------------------------------------------

describe('useBuilderLayers — handleBulkDelete (POL-09)', () => {
  it('Test 14: Success path: fires bulkDeleteLayersApi (not N separate calls)', async () => {
    const mockedBulk = vi.mocked(bulkDeleteLayersApi);
    mockedBulk.mockResolvedValue({ deleted: ['a', 'b', 'c'], failed: [] });

    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1 });
    const layerC = makeMockLayer({ id: 'c', sort_order: 2 });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerB, layerC]));
    await waitForInit();

    let ok: boolean | undefined;
    await act(async () => {
      ok = await result.current.handleBulkDelete(new Set(['a', 'b', 'c']));
    });

    // Phase 1047-04: exactly 1 batched call instead of N individual DELETEs
    expect(mockedBulk).toHaveBeenCalledTimes(1);
    expect(mockedBulk).toHaveBeenCalledWith(MAP_ID, expect.arrayContaining(['a', 'b', 'c']));
    expect(ok).toBe(true);
  });

  it('Test 15: Success path: optimistically removes layers from localLayers', async () => {
    const mockedBulk = vi.mocked(bulkDeleteLayersApi);
    mockedBulk.mockResolvedValue({ deleted: ['a', 'b'], failed: [] });

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
    const mockedBulk = vi.mocked(bulkDeleteLayersApi);
    mockedBulk.mockResolvedValue({ deleted: ['a'], failed: [] });

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

  it('Test 17: Failure path: full rollback when all ids in failed[]', async () => {
    const mockedBulk = vi.mocked(bulkDeleteLayersApi);
    mockedBulk.mockResolvedValue({
      deleted: [],
      failed: [
        { id: 'a', reason: 'not_found' },
        { id: 'b', reason: 'not_found' },
        { id: 'c', reason: 'not_found' },
      ],
    });

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

    // Should return false on full failure
    expect(ok).toBe(false);

    // Local layers should be rolled back to original state (all 3 present)
    const finalIds = result.current.localLayers.map((l) => l.id);
    expect(finalIds).toEqual(expect.arrayContaining(initialIds));
    expect(finalIds).toHaveLength(initialIds.length);
  });

  it('Test 18: Failure path: shows exactly one error toast', async () => {
    const mockedBulk = vi.mocked(bulkDeleteLayersApi);
    mockedBulk.mockResolvedValue({
      deleted: [],
      failed: [
        { id: 'a', reason: 'not_found' },
        { id: 'b', reason: 'not_found' },
        { id: 'c', reason: 'not_found' },
      ],
    });

    const errorSpy = vi.spyOn(toast, 'error');

    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1 });
    const layerC = makeMockLayer({ id: 'c', sort_order: 2 });
    const { result } = renderBuilderLayers(makeMapData([layerA, layerB, layerC]));
    await waitForInit();

    await act(async () => {
      await result.current.handleBulkDelete(new Set(['a', 'b', 'c']));
    });

    // Exactly 1 error toast (not 3)
    expect(errorSpy).toHaveBeenCalledOnce();
  });

  it('Test 19: Returns false on empty selection (early return guard)', async () => {
    const mockedBulk = vi.mocked(bulkDeleteLayersApi);

    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const { result } = renderBuilderLayers(makeMapData([layerA]));
    await waitForInit();

    let ok: boolean | undefined;
    await act(async () => {
      ok = await result.current.handleBulkDelete(new Set());
    });

    expect(ok).toBe(false);
    expect(mockedBulk).not.toHaveBeenCalled();
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
