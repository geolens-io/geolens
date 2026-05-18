/**
 * Phase 1051 Plan 02 — handleRemove (single-layer delete) regression tests (BUG-02).
 *
 * BUG-02: handleRemove was a no-op from the user's perspective because it called
 * removeLayerMutation.mutate but never optimistically removed the layer from
 * localLayers. The mutation's invalidateQueries refetch is gated by the
 * useEffect at use-builder-layers.ts:181-186 (`!hasUnsavedChanges`) which is
 * usually false during the builder editing flow — so the deleted layer remains
 * visible in the sidebar until a fresh page load.
 *
 * Fix mirrors the handleBulkDelete optimistic-update + rollback pattern (lines
 * 580-661 of use-builder-layers.ts).
 *
 * Worker-safety: mirrors the bulk-ops test harness — selective vi.mock on
 * @/api/maps with importActual, non-empty layers fixture, afterEach cleanup.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, cleanup } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import type { MapLayerResponse, MapResponse } from '@/types/api';

// ---------------------------------------------------------------------------
// Selective vi.mock — preserve everything in @/api/maps except the one
// function called by the useRemoveLayer mutation under test.
// ---------------------------------------------------------------------------
vi.mock('@/api/maps', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/maps')>();
  return {
    ...actual,
    removeLayerFromMapApi: vi.fn(),
  };
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
  cleanup();
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeMockLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'ds-1',
    dataset_name: overrides.dataset_name ?? 'Test',
    dataset_geometry_type: overrides.dataset_geometry_type ?? 'Polygon',
    dataset_table_name: overrides.dataset_table_name ?? 'test_table',
    visible: overrides.visible ?? true,
    opacity: overrides.opacity ?? 1,
    paint: overrides.paint ?? {},
    layout: overrides.layout ?? {},
    sort_order: overrides.sort_order ?? 0,
    filter: null,
    display_name: null,
    layer_type: overrides.layer_type ?? 'vector_geolens',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    dataset_record_type: overrides.dataset_record_type ?? 'vector_dataset',
    label_config: null,
    popup_config: null,
    style_config: null,
    show_in_legend: true,
    is_dem: false,
    dem_vertical_units: null,
    ...overrides,
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

// Minimal map instance mock — isStyleLoaded returns true so removePerLayerCompanions
// will iterate suffixes and call getLayer/removeLayer. We can spy on these to confirm
// the companion sweep ran.
function makeMapRef(overrides: Partial<{
  isStyleLoaded: () => boolean;
  getLayer: ReturnType<typeof vi.fn>;
  removeLayer: ReturnType<typeof vi.fn>;
}> = {}) {
  const mapInstance = {
    isStyleLoaded: overrides.isStyleLoaded ?? (() => true),
    getLayer: overrides.getLayer ?? vi.fn().mockReturnValue({ id: 'mock' }),
    removeLayer: overrides.removeLayer ?? vi.fn(),
  };
  return { current: mapInstance } as React.RefObject<typeof mapInstance>;
}

const MAP_ID = 'map-1';

function renderBuilderLayers(
  mapData: MapResponse | undefined,
  mapRef: ReturnType<typeof makeMapRef> = makeMapRef(),
  removeLayerMutationOverride?: {
    mutate?: ReturnType<typeof vi.fn>;
  },
) {
  const addLayerMutation = {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
  } as unknown as Parameters<typeof useBuilderLayers>[3];

  // Default removeLayerMutation: capture mutate calls and synchronously invoke
  // onSuccess. Tests can override to simulate onError or async timing.
  const removeLayerMutation = {
    mutate: removeLayerMutationOverride?.mutate ?? vi.fn((_vars, opts) => {
      // Default: success path. Tests that want error path supply their own mutate.
      opts?.onSuccess?.();
    }),
    mutateAsync: vi.fn(),
  } as unknown as Parameters<typeof useBuilderLayers>[4];

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
  return { ...out, removeLayerMutation };
}

async function waitForInit() {
  await act(async () => {});
}

// ---------------------------------------------------------------------------
// handleRemove (BUG-02)
// ---------------------------------------------------------------------------

describe('useBuilderLayers — handleRemove (BUG-02)', () => {
  it('Test 1: Optimistically removes the layer from localLayers immediately', async () => {
    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1 });
    const layerC = makeMockLayer({ id: 'c', sort_order: 2 });

    // Override the mutate to NOT call onSuccess — this proves the optimistic
    // filter happens before the API responds (which is the core of BUG-02).
    const mutateSpy = vi.fn();
    const { result } = renderBuilderLayers(
      makeMapData([layerA, layerB, layerC]),
      makeMapRef(),
      { mutate: mutateSpy },
    );
    await waitForInit();

    expect(result.current.localLayers).toHaveLength(3);

    act(() => {
      result.current.handleRemove('b');
    });

    // After handleRemove, 'b' must be gone from localLayers EVEN though
    // the mutation onSuccess has not fired (mutateSpy doesn't call it).
    const ids = result.current.localLayers.map((l) => l.id);
    expect(ids).toEqual(['a', 'c']);
  });

  it('Test 2: Re-indexes sort_order on remaining layers after optimistic remove', async () => {
    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1 });
    const layerC = makeMockLayer({ id: 'c', sort_order: 2 });

    const { result } = renderBuilderLayers(
      makeMapData([layerA, layerB, layerC]),
      makeMapRef(),
      { mutate: vi.fn() }, // never resolves
    );
    await waitForInit();

    act(() => {
      result.current.handleRemove('a');
    });

    // After removing 'a', remaining layers should be re-indexed 0, 1
    const remaining = result.current.localLayers;
    expect(remaining).toHaveLength(2);
    expect(remaining.find((l) => l.id === 'b')!.sort_order).toBe(0);
    expect(remaining.find((l) => l.id === 'c')!.sort_order).toBe(1);
  });

  it('Test 3: Invokes removePerLayerCompanions for the removed layer (calls map.removeLayer with layer-{id})', async () => {
    const removeLayer = vi.fn();
    const getLayer = vi.fn().mockReturnValue({ id: 'mock' });
    const mapRef = makeMapRef({ isStyleLoaded: () => true, getLayer, removeLayer });

    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const { result } = renderBuilderLayers(
      makeMapData([layerA]),
      mapRef,
      { mutate: vi.fn() },
    );
    await waitForInit();

    act(() => {
      result.current.handleRemove('a');
    });

    // removePerLayerCompanions iterates 7 suffixes per layer id, calling
    // removeLayer for each one whose getLayer returns truthy.
    expect(removeLayer).toHaveBeenCalledWith('layer-a');
    expect(removeLayer).toHaveBeenCalledWith('layer-a-outline');
    expect(removeLayer).toHaveBeenCalledWith('layer-a-label');
  });

  it('Test 4: Fires removeLayerMutation.mutate with { mapId, layerId }', async () => {
    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const mutateSpy = vi.fn();
    const { result } = renderBuilderLayers(
      makeMapData([layerA]),
      makeMapRef(),
      { mutate: mutateSpy },
    );
    await waitForInit();

    act(() => {
      result.current.handleRemove('a');
    });

    expect(mutateSpy).toHaveBeenCalledTimes(1);
    const [vars] = mutateSpy.mock.calls[0];
    expect(vars).toEqual({ mapId: MAP_ID, layerId: 'a' });
  });

  it('Test 5: On mutation onError, restores localLayers (rollback)', async () => {
    const layerA = makeMockLayer({ id: 'a', sort_order: 0 });
    const layerB = makeMockLayer({ id: 'b', sort_order: 1 });

    // Override mutate to synchronously fire onError (simulates network failure).
    const mutateSpy = vi.fn((_vars, opts) => {
      opts?.onError?.(new Error('network'));
    });

    const { result } = renderBuilderLayers(
      makeMapData([layerA, layerB]),
      makeMapRef(),
      { mutate: mutateSpy },
    );
    await waitForInit();

    expect(result.current.localLayers).toHaveLength(2);

    act(() => {
      result.current.handleRemove('a');
    });

    // After onError fires, 'a' must be restored to localLayers.
    const ids = result.current.localLayers.map((l) => l.id);
    expect(ids).toEqual(expect.arrayContaining(['a', 'b']));
    expect(ids).toHaveLength(2);
  });

});
