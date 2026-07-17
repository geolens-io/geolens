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
import {
  makeBuilderLayer,
  makeBuilderMap,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import type { MapLayerResponse, MapResponse } from '@/types/api';
import { toast } from 'sonner';
import { prepareLayersForPersistence, hydrateFolderGroupLayers } from '@/components/builder/folder-groups';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';

type MaplibreMap = import('maplibre-gl').Map;
type GroupedLayer = MapLayerResponse & { parent_group_id?: string | null };

const makeMockLayer = makeBuilderLayer;

function makeMapData(layers: MapLayerResponse[] = []): MapResponse {
  return makeBuilderMap(layers);
}

function renderBuilderLayers(
  mapData: MapResponse | undefined,
  mapRef: React.RefObject<MaplibreMap | null> = { current: null } as React.RefObject<MaplibreMap | null>,
) {
  const mutate = vi.fn();
  const addLayerMutation = { mutate } as unknown as Parameters<typeof useBuilderLayers>[3];
  const removeLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4];
  // fix(#392): 6th positional param bridging into useBuilderSave's Save-diff baseline.
  const saveBaselineSync = vi.fn();
  const saveBaselineSyncRef = { current: saveBaselineSync } as unknown as Parameters<typeof useBuilderLayers>[5];

  const out = renderHook(() =>
    useBuilderLayers(
      mapData,
      mapRef,
      'map-1',
      addLayerMutation,
      removeLayerMutation,
      saveBaselineSyncRef,
    ),
  );
  return { ...out, mutate, saveBaselineSync };
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

  it('P1-08: optimistically merges the created layer into localLayers immediately (non-group add)', () => {
    const existing = makeMockLayer({ id: 'existing', sort_order: 0 });
    const { result, mutate } = renderBuilderLayers(makeMapData([existing]));

    act(() => {
      result.current.handleAddDataset('ds-42');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'created-layer-id', dataset_id: 'ds-42' }); });

    // The created layer appears right away (prepended at top of the stack) even
    // though no refetch/invalidation has rehydrated state — so a dirty map shows
    // the add immediately instead of staying hidden until save/reload.
    const ids = result.current.localLayers.map((l) => l.id);
    expect(ids).toContain('created-layer-id');
    expect(ids[0]).toBe('created-layer-id');
    // And it is recorded in the saved baseline so it is treated as persisted.
    expect(result.current.savedLayerBaseline.some((l) => l.id === 'created-layer-id')).toBe(true);
  });

  it('fix(#545): first layer on a fresh empty map does NOT mark the map dirty (no false unsaved-changes prompt)', () => {
    const { result, mutate } = renderBuilderLayers(makeMapData([]));

    act(() => {
      result.current.handleAddDataset('ds-42');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'created-layer-id', dataset_id: 'ds-42', sort_order: 0 }); });

    // The POST-created layer alone IS the saved state — nothing was renumbered.
    expect(result.current.localLayers.map((l) => l.id)).toEqual(['created-layer-id']);
    expect(result.current.hasUnsavedChanges).toBe(false);
  });

  it('fix(#554 codex P2): two adds resolving in one batch on a fresh map still mark dirty (second add renumbers the first)', () => {
    const { result, mutate } = renderBuilderLayers(makeMapData([]));

    act(() => {
      result.current.handleAddDataset('ds-1');
      result.current.handleAddDataset('ds-2');
    });

    const [, { onSuccess: onSuccess1 }] = mutate.mock.calls[0];
    const [, { onSuccess: onSuccess2 }] = mutate.mock.calls[1];
    // Both resolve inside ONE act/batch: layersRef has not committed layer-1
    // yet when layer-2's onSuccess runs, but the renumber of layer-1 is real
    // unpersisted local state — the map must be dirty.
    act(() => {
      onSuccess1({ id: 'layer-1', dataset_id: 'ds-1', sort_order: 0 });
      onSuccess2({ id: 'layer-2', dataset_id: 'ds-2', sort_order: 0 });
    });

    expect(result.current.localLayers.map((l) => l.id)).toEqual(['layer-2', 'layer-1']);
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('fix(#545)/WR-02: add onto a map with existing layers STILL marks dirty (sibling renumber is unpersisted)', () => {
    const existing = makeMockLayer({ id: 'existing', sort_order: 0 });
    const { result, mutate } = renderBuilderLayers(makeMapData([existing]));

    act(() => {
      result.current.handleAddDataset('ds-42');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'created-layer-id', dataset_id: 'ds-42', sort_order: 0 }); });

    expect(result.current.hasUnsavedChanges).toBe(true);
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
    // fix(#394) LM-01/B-021: assert POSITION too — the row must sit inside the
    // group's block (immediately after the group row here), not merely carry
    // parent_group_id from wherever it happened to be.
    const ids = result.current.localLayers.map((l) => l.id);
    expect(ids.indexOf('child-layer-id')).toBe(ids.indexOf('group-1') + 1);
  });

  it('Test E2: fix(#394) LM-01/B-021 — kebab Add-to-group splices into the group block and renumbers', () => {
    // The loose row starts ABOVE the group: before the fix it kept its array
    // position and only gained parent_group_id, so hydrateFolderGroupLayers
    // re-anchored the whole group at the old position after save+reload.
    const loose = makeMockLayer({ id: 'loose-1', dataset_id: 'ds-1', sort_order: 0 });
    const group = makeMockLayer({ id: 'group-1', layer_type: 'folder_group' as MapLayerResponse['layer_type'], sort_order: 1 });
    const below = makeMockLayer({ id: 'below-1', dataset_id: 'ds-3', sort_order: 2 });
    const { result } = renderBuilderLayers(makeMapData([loose, group, below]));

    act(() => {
      result.current.handleAddLayerToExistingGroup('loose-1', 'group-1');
    });

    const ids = result.current.localLayers.map((l) => l.id);
    expect(ids).toEqual(['group-1', 'loose-1', 'below-1']);
    expect((result.current.localLayers[1] as GroupedLayer).parent_group_id).toBe('group-1');
    expect(result.current.localLayers.map((l) => l.sort_order)).toEqual([0, 1, 2]);
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

// ---------------------------------------------------------------------------
// fix(#392): dropping a dataset onto a folder group must insert
// adjacent to the group's existing block, not at array index 0 — otherwise
// hydrateFolderGroupLayers (which anchors the group at its FIRST child) drags
// the whole group to the stack top after a save/reload round-trip. (audit B-004c/LM-03)
// ---------------------------------------------------------------------------
describe('handleAddDataset — group-drop adjacency (B-004c / LM-03)', () => {
  it('Test 1: inserts the new child adjacent to the group block, not at index 0', () => {
    const before = makeMockLayer({ id: 'before', sort_order: 0 });
    // fix(#392): 'group:folder' is a frontend-only synthetic layer_type (GroupedLayer); cast only.
    const groupRow = { ...makeMockLayer({ id: 'group-1', sort_order: 1 }), layer_type: 'group:folder' } as unknown as MapLayerResponse;
    const child1 = {
      ...makeMockLayer({ id: 'child1', sort_order: 2 }),
      parent_group_id: 'group-1',
    } as GroupedLayer as MapLayerResponse;
    const afterOutside = makeMockLayer({ id: 'after-outside', sort_order: 3 });

    const { result, mutate } = renderBuilderLayers(makeMapData([before, groupRow, child1, afterOutside]));

    act(() => {
      result.current.handleAddDataset('ds-99', undefined, 'group-1');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'new-child', dataset_id: 'ds-99' }); });

    const updated = result.current.localLayers as GroupedLayer[];
    const newChildIdx = updated.findIndex((l) => l.id === 'new-child');
    const child1Idx = updated.findIndex((l) => l.id === 'child1');

    // Adjacent to the group's existing last child, NOT array index 0.
    expect(newChildIdx).toBe(child1Idx + 1);
    expect(newChildIdx).not.toBe(0);
    expect(updated.find((l) => l.id === 'new-child')?.parent_group_id).toBe('group-1');
    // sort_order renumbered by array index (not the raw sort_order:0 request hint)
    expect(updated.find((l) => l.id === 'new-child')?.sort_order).not.toBe(0);
  });

  it('Test 2: the group anchor survives a prepareLayersForPersistence -> hydrateFolderGroupLayers round-trip', () => {
    const before = makeMockLayer({ id: 'before', sort_order: 0 });
    // fix(#392): 'group:folder' is a frontend-only synthetic layer_type (GroupedLayer); cast only.
    const groupRow = { ...makeMockLayer({ id: 'group-1', sort_order: 1 }), layer_type: 'group:folder' } as unknown as MapLayerResponse;
    const child1 = {
      ...makeMockLayer({ id: 'child1', sort_order: 2 }),
      parent_group_id: 'group-1',
    } as GroupedLayer as MapLayerResponse;
    const afterOutside = makeMockLayer({ id: 'after-outside', sort_order: 3 });

    const { result, mutate } = renderBuilderLayers(makeMapData([before, groupRow, child1, afterOutside]));

    // Capture the group's position BEFORE the drop.
    const groupIdxBeforeDrop = result.current.localLayers.findIndex((l) => l.id === 'group-1');

    act(() => {
      result.current.handleAddDataset('ds-99', undefined, 'group-1');
    });
    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'new-child', dataset_id: 'ds-99' }); });

    const persisted = prepareLayersForPersistence(result.current.localLayers, result.current.groupMeta);
    const rehydrated = hydrateFolderGroupLayers(persisted);

    const groupIdxAfterRoundTrip = rehydrated.layers.findIndex((l) => isFolderGroupLayer(l));

    // The group must NOT be re-anchored to the stack top (index 0) — it stays
    // at the same relative position it held before the drop.
    expect(groupIdxAfterRoundTrip).not.toBe(0);
    expect(groupIdxAfterRoundTrip).toBe(groupIdxBeforeDrop);
  });

  // Test 3 (loose add unchanged, no regression to the P1-08 top-of-stack UX)
  // is already covered by 'Test A: posts with sort_order: 0' and the P1-08
  // optimistic-merge test above — both exercise handleAddDataset with
  // parentGroupId omitted/undefined and assert the created layer prepends at
  // array index 0. No new test needed; re-asserted here for traceability.
  it('Test 3: loose (non-group) add still prepends at the top of the user stack', () => {
    const existing = makeMockLayer({ id: 'existing', sort_order: 0 });
    const { result, mutate } = renderBuilderLayers(makeMapData([existing]));

    act(() => {
      result.current.handleAddDataset('ds-42');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'new-loose', dataset_id: 'ds-42' }); });

    const ids = result.current.localLayers.map((l) => l.id);
    expect(ids[0]).toBe('new-loose');
  });

  // fix(#392): a loose (non-group) add renumbers every existing layer's sort_order
  // locally, but the backend does not renumber sibling rows on this path
  // (maps/service_layers.py:106-120) — so that renumber is an unpersisted diff
  // the apiLayers resync effect could silently clobber before Save unless the
  // map is marked dirty. Fails on pre-fix code (hasUnsavedChanges stayed false). (audit WR-02)
  it('Test 4 (WR-02): non-grouped add-dataset that renumbers sibling sort_order marks the map dirty', () => {
    const existingA = makeMockLayer({ id: 'existing-a', sort_order: 0 });
    const existingB = makeMockLayer({ id: 'existing-b', sort_order: 1 });
    const { result, mutate } = renderBuilderLayers(makeMapData([existingA, existingB]));

    expect(result.current.hasUnsavedChanges).toBe(false);

    act(() => {
      result.current.handleAddDataset('ds-42');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'new-loose', dataset_id: 'ds-42' }); });

    // Sanity: the sibling rows were in fact renumbered by array index.
    const bySortOrder = [...result.current.localLayers].sort((a, b) => a.sort_order - b.sort_order);
    expect(bySortOrder.map((l) => l.id)).toEqual(['new-loose', 'existing-a', 'existing-b']);

    expect(result.current.hasUnsavedChanges).toBe(true);
  });
});
