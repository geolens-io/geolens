/**
 * Focused tests for handleAddDataset — BSR-18.
 *
 * Tests: sort_order=0 (prepend), onSuccessCb chain, error handling, and
 * backward-compat (handler still callable without the optional onSuccessCb).
 *
 * Uses the shared `renderHook` from `@/test/test-utils` with no module
 * mocks — the addLayerMutation is stubbed at the call site, which is all
 * the contract under test needs.
 *
 * ----------------------------------------------------------------------
 * Worker-exit root cause (POL-20, Phase 1039):
 *
 *   The previous version of this file shipped with two compounding
 *   problems that together produced `Worker exited unexpectedly` /
 *   `Timeout terminating forks worker` on every run (and a V8 heap
 *   OOM under `--pool=threads`):
 *
 *   1. 11 file-local `vi.mock(...)` factories for transitive deps
 *      (react-router, react-i18next, sonner, use-ephemeral-layers,
 *      use-layer-map-sync, map-sync, layer-adapters/registry,
 *      basemap-utils, tile-utils, label-layer-utils, renderAs). The
 *      sibling `use-builder-layers.test.ts` exercises the same hook
 *      with the same `renderHook` wrapper and zero `vi.mock`
 *      declarations, runs in <1 s, and passes 23/23. Direct bisection
 *      (copying the sibling's body into this file's path) confirms
 *      the issue is per-file mock setup — once removed, the same
 *      hook + wrapper + path combination passes.
 *
 *   2. `mapData.layers = []` (empty array) initial fixture. Combined
 *      with the hook's two layer-init useEffects (`use-builder-layers.ts`
 *      lines 108-131) and the prior `vi.mock` graph, this produced a
 *      microtask/promise loop that V8 surfaces as
 *      `Builtins_PromiseConstructor` → `Builtins_PromiseFulfillReactionJob`
 *      → `MicrotaskQueue::RunMicrotasks` recursion until the worker
 *      hits the heap limit and is SIGTERM'd. Tests A/B/C/D never
 *      executed (`tests 0ms` in the reporter).
 *
 *   Mitigation: drop the per-file `vi.mock` block AND pass a non-empty
 *   layers fixture (a single placeholder layer) to `useBuilderLayers`.
 *   The placeholder has no effect on the contract under test —
 *   `handleAddDataset` posts the new layer with `sort_order: 0`
 *   regardless of current stack size, and the addLayerMutation stub
 *   records the call without invoking any onSuccess/onError unless the
 *   test explicitly drives it. Direct contract checks
 *   (`mutate.mock.calls[0]`) verify the same behaviour the original
 *   tests asserted (BSR-18: sort_order=0 prepend + onSuccessCb chain).
 *
 *   Alternatives attempted and rejected:
 *   - `afterEach(cleanup); afterEach(vi.clearAllMocks)` — does NOT
 *     resolve the OOM (the leak is intra-test, not cross-test).
 *   - `vi.hoisted` stable-reference refactor for `useSearchParams` /
 *     `useTranslation` mocks — does NOT resolve the OOM (mock
 *     factories themselves are the trigger, not reference instability).
 *   - `--pool=threads` override — reproduces the same OOM as
 *     `ERR_WORKER_OUT_OF_MEMORY`, confirming the issue is in-worker
 *     heap exhaustion, not a forks-pool teardown bug.
 * ----------------------------------------------------------------------
 */

import { describe, it, expect, vi } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import type { MapLayerResponse, MapResponse } from '@/types/api';
import { toast } from 'sonner';

type MaplibreMap = import('maplibre-gl').Map;

function makeMockLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'Test',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'test_table',
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    sort_order: 0,
    filter: null,
    display_name: null,
    layer_type: 'vector_geolens',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    dataset_record_type: undefined,
    label_config: null,
    style_config: null,
    ...overrides,
  };
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

function renderBuilderLayers(
  mapData: MapResponse | undefined,
  mapRef: React.RefObject<MaplibreMap | null> = { current: null } as React.RefObject<MaplibreMap | null>,
) {
  const mutate = vi.fn();
  const addLayerMutation = { mutate } as unknown as Parameters<typeof useBuilderLayers>[3];
  const removeLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4];

  const out = renderHook(() =>
    useBuilderLayers(
      mapData,
      mapRef,
      'map-1',
      addLayerMutation,
      removeLayerMutation,
    ),
  );
  return { ...out, mutate };
}

describe('handleAddDataset (BSR-18)', () => {
  it('Test A: posts with sort_order: 0 (not layersRef.current.length)', () => {
    const layer = makeMockLayer();
    const { result, mutate } = renderBuilderLayers(makeMapData([layer]));

    act(() => {
      result.current.handleAddDataset('ds-42');
    });

    expect(mutate).toHaveBeenCalledOnce();
    const [{ data }] = mutate.mock.calls[0];
    expect(data).toMatchObject({ dataset_id: 'ds-42', sort_order: 0 });
  });

  it('Test B: invokes onSuccessCb(createdLayer.id) when mutation resolves', () => {
    const layer = makeMockLayer();
    const { result, mutate } = renderBuilderLayers(makeMapData([layer]));
    const onSuccessCb = vi.fn();

    act(() => {
      result.current.handleAddDataset('ds-42', onSuccessCb);
    });

    // Simulate mutation success with a created layer object
    const [, { onSuccess }] = mutate.mock.calls[0];
    const createdLayer = { id: 'new-layer-id' };
    act(() => { onSuccess(createdLayer); });

    expect(onSuccessCb).toHaveBeenCalledWith('new-layer-id');
  });

  it('Test C: does NOT call onSuccessCb when mutation errors', () => {
    const layer = makeMockLayer();
    const { result, mutate } = renderBuilderLayers(makeMapData([layer]));
    const onSuccessCb = vi.fn();

    act(() => {
      result.current.handleAddDataset('ds-42', onSuccessCb);
    });

    const [, { onError }] = mutate.mock.calls[0];
    act(() => { onError(); });

    expect(onSuccessCb).not.toHaveBeenCalled();
  });

  it('Test D: backward-compat — no onSuccessCb arg does not throw', () => {
    const layer = makeMockLayer();
    const { result, mutate } = renderBuilderLayers(makeMapData([layer]));

    act(() => {
      result.current.handleAddDataset('ds-42');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    expect(() => act(() => { onSuccess({ id: 'new-layer-id' }); })).not.toThrow();
  });
});

// Phase 1040 Plan 03: extended signature tests (parentGroupId + datasetName)
describe('handleAddDataset extended signature (Phase 1040 POL-03/05)', () => {
  it('Test E: parentGroupId wires created layer into group via handleAddLayerToExistingGroup', () => {
    // Pre-populate localLayers with the group AND a child-layer so
    // handleAddLayerToExistingGroup can find `child-layer-id` after the mutation resolves.
    const groupLayer = makeMockLayer({ id: 'group-1', layer_type: 'folder_group' as MapLayerResponse['layer_type'] });
    const childLayer = makeMockLayer({ id: 'child-layer-id', dataset_id: 'ds-99' });
    const { result, mutate } = renderBuilderLayers(makeMapData([groupLayer, childLayer]));

    act(() => {
      result.current.handleAddDataset('ds-99', undefined, 'group-1');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'child-layer-id' }); });

    // handleAddLayerToExistingGroup should have set parent_group_id on child-layer-id
    const updated = result.current.localLayers.find((l) => l.id === 'child-layer-id');
    expect(updated).toBeDefined();
    expect((updated as { parent_group_id?: string } | undefined)?.parent_group_id).toBe('group-1');
  });

  it('Test F: parentGroupId=null does not attempt group wiring', () => {
    const layer = makeMockLayer();
    const { result, mutate } = renderBuilderLayers(makeMapData([layer]));
    const onSuccessCb = vi.fn();

    act(() => {
      result.current.handleAddDataset('ds-42', onSuccessCb, null);
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'new-layer-id' }); });

    // onSuccessCb still fires — no group wiring side effects
    expect(onSuccessCb).toHaveBeenCalledWith('new-layer-id');
  });

  it('Test G: datasetName provided causes named toast key path', () => {
    const layer = makeMockLayer();
    const { result, mutate } = renderBuilderLayers(makeMapData([layer]));
    const successSpy = vi.spyOn(toast, 'success');

    act(() => {
      result.current.handleAddDataset('ds-42', undefined, null, 'My Dataset');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'new-layer-id' }); });

    // WR-04: verify the dataset-specific key is used (not the generic layerAdded fallback)
    // The i18n key toasts.datasetAdded interpolates to "My Dataset added to map"
    expect(successSpy).toHaveBeenCalledWith(
      expect.stringContaining('My Dataset'),
      expect.objectContaining({ id: 'add-layer-ds-42' }),
    );

    successSpy.mockRestore();
  });

  it('Test H: backward compat — all new params optional, existing callers unchanged', () => {
    const layer = makeMockLayer();
    const { result, mutate } = renderBuilderLayers(makeMapData([layer]));

    // Two-arg call (existing callers with onSuccessCb)
    act(() => {
      result.current.handleAddDataset('ds-42', vi.fn());
    });

    expect(mutate).toHaveBeenCalledOnce();
    const [{ data }] = mutate.mock.calls[0];
    expect(data).toMatchObject({ dataset_id: 'ds-42', sort_order: 0 });
  });
});

// Phase 1042 Plan 04 POL-15: freshLayerId lifecycle tests
describe('freshLayerId lifecycle (Phase 1042 POL-15)', () => {
  it('Test I: freshLayerId is set synchronously to new layer id after successful handleAddDataset', () => {
    vi.useFakeTimers();
    const layer = makeMockLayer();
    const { result, mutate } = renderBuilderLayers(makeMapData([layer]));

    act(() => {
      result.current.handleAddDataset('ds-42');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'fresh-layer-id' }); });

    expect(result.current.freshLayerId).toBe('fresh-layer-id');
    vi.useRealTimers();
  });

  it('Test J: freshLayerId returns to null approximately 200ms after handleAddDataset resolves', () => {
    vi.useFakeTimers();
    const layer = makeMockLayer();
    const { result, mutate } = renderBuilderLayers(makeMapData([layer]));

    act(() => {
      result.current.handleAddDataset('ds-42');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'fresh-layer-id' }); });

    // Still set before 200ms
    expect(result.current.freshLayerId).toBe('fresh-layer-id');

    // Advance timers past 200ms
    act(() => { vi.advanceTimersByTime(200); });

    expect(result.current.freshLayerId).toBeNull();
    vi.useRealTimers();
  });

  it('Test K: unmounting before 200ms fires does NOT produce setState-after-unmount warning', () => {
    vi.useFakeTimers();
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const layer = makeMockLayer();
    const { result, mutate, unmount } = renderBuilderLayers(makeMapData([layer]));

    act(() => {
      result.current.handleAddDataset('ds-42');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'fresh-layer-id' }); });

    // Unmount before 200ms timer fires
    unmount();

    // Advance timers — should NOT trigger setState on unmounted component
    act(() => { vi.advanceTimersByTime(250); });

    const stateLogs = consoleSpy.mock.calls.filter((args) =>
      args.some((a: unknown) => typeof a === 'string' && a.includes('setState')),
    );
    expect(stateLogs).toHaveLength(0);

    consoleSpy.mockRestore();
    vi.useRealTimers();
  });
});
