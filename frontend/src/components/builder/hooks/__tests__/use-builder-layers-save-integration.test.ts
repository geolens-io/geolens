/**
 * Duplicate-layer-on-save regression.
 *
 * useBuilderLayers' handleAddDataset / handleDuplicateRendering insert a
 * server-created layer into localLayers AND mark the map dirty in the SAME
 * update (the sort_order-renumber fix requires this — the sibling
 * renumber is itself an unpersisted diff). useBuilderSave's baselineLayersRef
 * (the Save-diff baseline buildLayerDiff reads) previously only refreshed
 * while `!hasUnsavedChanges`, so it never learned about the new server layer
 * id. A subsequent Save's buildLayerDiff then classified the already-created
 * layer as `diff.added`, and the PATCH endpoint created a SECOND layer for it.
 *
 * The fix threads a `saveBaselineSyncRef` callback ref between the two hooks
 * (owned by MapBuilderPage, mirrored here) so the layer-create paths register
 * the server-created layer into the Save-diff baseline immediately.
 *
 * This test wires useBuilderLayers + useBuilderSave together exactly as
 * MapBuilderPage does (shared mapId/localLayers/groupMeta/hasUnsavedChanges +
 * the saveBaselineSyncRef bridge), drives a real add-dataset, and asserts the
 * created layer is NOT re-submitted as `added` on Save.
 *
 * RED/GREEN check: this test fails on pre-fix code — reverting the
 * saveBaselineSyncRef wiring in use-builder-save.ts + use-builder-layers.ts
 * makes `diff.added` contain the created layer (see PR #392 description).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook as baseRenderHook } from '@testing-library/react';
import { createElement, useRef, type ReactNode } from 'react';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { renderHook } from '@/test/test-utils';
import { queryKeys } from '@/lib/query-keys';
import { resolveBasemapId } from '@/lib/basemap-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import { useBuilderSave, __resetThumbnailDebounceForTests, type SaveBaselineSync } from '@/components/builder/hooks/use-builder-save';
import {
  makeBuilderLayer,
  makeBuilderMap,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import type { MapLayerResponse, MapResponse } from '@/types/api';

type MaplibreMap = import('maplibre-gl').Map;

/* ── Mocks (mirrors use-builder-save.test.ts) ─────────────────────────── */

const mockUpdateMapMutateAsync = vi.fn();
const mockPatchMapLayersMutateAsync = vi.fn();
const mockDuplicateMapMutateAsync = vi.fn();

vi.mock('@/hooks/use-maps', () => ({
  useUpdateMap: () => ({ mutateAsync: mockUpdateMapMutateAsync, isPending: false }),
  usePatchMapLayers: () => ({ mutateAsync: mockPatchMapLayersMutateAsync, isPending: false }),
  useDuplicateMap: () => ({ mutateAsync: mockDuplicateMapMutateAsync, isPending: false }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useEnabledPlugins: () => ({ data: null, isLoading: false }),
  useTileConfig: () => ({
    data: { cdn_base_url: null, mvt_source_layer_prefix: 'data' },
  }),
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => ({ edition: 'community', features: [], isEnterprise: false, isLoading: false }),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

const mockBulkDeleteLayers = vi.fn();
vi.mock('@/api/maps', () => ({
  bulkDeleteLayersApi: (...args: unknown[]) => mockBulkDeleteLayers(...args),
  getMap: vi.fn(),
  uploadThumbnail: vi.fn(() => Promise.resolve()),
  uploadOgImage: vi.fn(() => Promise.resolve()),
}));

// useUnsavedGuard's useBlocker requires a Data Router; MemoryRouter (used by
// the shared renderHook wrapper) doesn't provide one — stub it like
// use-builder-save.test.ts does.
const mockBlocker = { state: 'unblocked' as const, reset: vi.fn(), proceed: vi.fn() };
vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return { ...actual, useBlocker: () => mockBlocker };
});

/* ── Harness: wires the two hooks exactly as MapBuilderPage does ─────── */

function useCombinedBuilder(
  mapData: MapResponse | undefined,
  mapId: string,
  addLayerMutation: Parameters<typeof useBuilderLayers>[3],
  removeLayerMutation: Parameters<typeof useBuilderLayers>[4],
) {
  const mapInstanceRef = useRef<MaplibreMap | null>(null);
  // The SAME callback-ref bridge MapBuilderPage owns between
  // useBuilderLayers and useBuilderSave — see MapBuilderPage.tsx (~line 204+7)
  // and use-builder-save.ts's `saveBaselineSyncRef` effect.
  const saveBaselineSyncRef = useRef<SaveBaselineSync>({ add: () => {}, remove: () => {} });

  const layers = useBuilderLayers(
    mapData,
    mapInstanceRef,
    mapId,
    addLayerMutation,
    removeLayerMutation,
    saveBaselineSyncRef,
  );

  const save = useBuilderSave({
    mapId,
    localLayers: layers.localLayers,
    groupMeta: layers.groupMeta,
    localBasemap: layers.localBasemap,
    showBasemapLabels: layers.showBasemapLabels,
    basemapConfig: layers.basemapConfig,
    terrainConfig: layers.localTerrainConfig,
    localName: layers.localName,
    localDescription: layers.localDescription,
    legendTitle: layers.localLegendTitle,
    dockNotes: '',
    mapInstanceRef,
    setHasUnsavedChanges: layers.setHasUnsavedChanges,
    hasUnsavedChanges: layers.hasUnsavedChanges,
    hasUnsavedEdits: layers.hasUnsavedEdits,
    hasThumbnail: true,
    saveBaselineSyncRef,
    saveFence: layers.saveFence,
  });

  return { ...layers, ...save };
}

function renderCombined(mapData: MapResponse, mapId = 'map-1') {
  const mutate = vi.fn();
  const removeMutate = vi.fn();
  const addLayerMutation = { mutate } as unknown as Parameters<typeof useBuilderLayers>[3];
  const removeLayerMutation = { mutate: removeMutate } as unknown as Parameters<typeof useBuilderLayers>[4];

  const out = renderHook(() => useCombinedBuilder(mapData, mapId, addLayerMutation, removeLayerMutation));
  return { ...out, mutate, removeMutate };
}

describe('duplicate-layer-on-save: Save-diff baseline sync', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    __resetThumbnailDebounceForTests();
    mockUpdateMapMutateAsync.mockImplementation(async (payload: { id: string }) => ({ id: payload.id, layers: [] }));
    mockPatchMapLayersMutateAsync.mockResolvedValue({ id: 'map-1', layers: [] });
  });

  it('non-grouped add-dataset on a clean map does NOT re-submit the created layer as diff.added on Save (no duplicate PATCH-create)', async () => {
    const existingA = makeBuilderLayer({ id: 'existing-a', dataset_id: 'ds-existing-a', sort_order: 0 });
    const existingB = makeBuilderLayer({ id: 'existing-b', dataset_id: 'ds-existing-b', sort_order: 1 });
    const mapData = makeBuilderMap([existingA, existingB]);

    const { result, mutate } = renderCombined(mapData);

    expect(result.current.hasUnsavedChanges).toBe(false);

    act(() => {
      result.current.handleAddDataset('ds-new');
    });

    expect(mutate).toHaveBeenCalledOnce();
    const [, { onSuccess }] = mutate.mock.calls[0];
    const createdLayer = makeBuilderLayer({ id: 'created-1', dataset_id: 'ds-new', sort_order: 0 });
    act(() => { onSuccess(createdLayer); });

    // Sanity: the add did in fact dirty the map (sibling-renumber fix) and
    // the created layer is immediately visible (optimistic merge).
    expect(result.current.hasUnsavedChanges).toBe(true);
    expect(result.current.localLayers.some((l) => l.id === 'created-1')).toBe(true);

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledOnce();
    const [{ diff }] = mockPatchMapLayersMutateAsync.mock.calls[0];

    // THE regression: pre-fix, `diff.added` contained the just-created layer
    // and the backend PATCH endpoint created a SECOND layer for it.
    expect(diff.added).toBeUndefined();
    // The sibling sort_order renumber (prepend pushed existing-a/-b down) still
    // surfaces as a legitimate reorder diff — this must NOT regress.
    expect(diff.order).toEqual(['created-1', 'existing-a', 'existing-b']);
  });

  it('grouped add-dataset: the created layer is not diff.added, but its folder-group membership still shows as an update diff (must not silently drop the PATCH)', async () => {
    const existingA = makeBuilderLayer({ id: 'existing-a', dataset_id: 'ds-existing-a', sort_order: 0 });
    const mapData = makeBuilderMap([existingA]);

    const { result, mutate } = renderCombined(mapData);

    // Create a real folder group around existing-a (well-tested existing action).
    act(() => {
      result.current.handleCreateGroupWithLayer('existing-a');
    });
    const groupRow = result.current.localLayers.find((l) => isFolderGroupLayer(l));
    expect(groupRow).toBeDefined();
    const groupId = groupRow!.id;

    // Add a new dataset directly into that group.
    act(() => {
      result.current.handleAddDataset('ds-new', undefined, groupId);
    });

    // handleCreateGroupWithLayer is a local-only action (no API call) — mutate
    // fires exactly once, for the add-dataset call above.
    expect(mutate).toHaveBeenCalledOnce();
    const [, { onSuccess }] = mutate.mock.calls[0];
    const createdLayer = makeBuilderLayer({ id: 'created-1', dataset_id: 'ds-new', sort_order: 0 });
    act(() => { onSuccess(createdLayer); });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledOnce();
    const [{ diff }] = mockPatchMapLayersMutateAsync.mock.calls[0];

    // No duplicate creation for the grouped add either.
    expect(diff.added).toBeUndefined();

    // But grouping is frontend-only state until Save — the created layer's
    // folder-group membership must still show up as a real update diff (the
    // baseline holds the PURE createdLayer with no parent_group_id).
    const createdUpdate = diff.updated?.find((u: { id: string }) => u.id === 'created-1');
    expect(createdUpdate).toBeDefined();
    const builder = (createdUpdate?.style_config as { builder?: { folderGroupId?: string } } | undefined)?.builder;
    expect(builder?.folderGroupId).toBe(groupId);
  });
});

/**
 * "layer deletes prune the clean-state baseline but never the
 * save-diff baseline, so a delete on an already-dirty map guarantees a stale
 * diff on the next save" (codebase audit 2026-08-30).
 *
 * There are two baselines. `savedLayerBaselineRef` (use-builder-layers) IS
 * pruned by both delete paths. The save-diff baseline `baselineLayersRef`
 * (use-builder-save) only refreshes while the map is CLEAN, and the bridge
 * between them was add-only, so "style something, then delete a layer, then
 * save" emitted the already-deleted id in diff.removed. The backend rejects
 * that with 400 "Layer diff references layer ids outside this map".
 *
 * Counterfactual: with the `remove` half of the bridge taken out, both tests
 * below see `diff.removed` carry the deleted id.
 */
describe('delete prunes the Save-diff baseline on an already-dirty map', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    __resetThumbnailDebounceForTests();
    mockUpdateMapMutateAsync.mockImplementation(async (payload: { id: string }) => ({ id: payload.id, layers: [] }));
    mockPatchMapLayersMutateAsync.mockResolvedValue({ id: 'map-1', layers: [] });
  });

  it('single delete after an unrelated edit emits no removed id', async () => {
    const keep = makeBuilderLayer({ id: 'keep', dataset_id: 'ds-keep', sort_order: 0 });
    const doomed = makeBuilderLayer({ id: 'doomed', dataset_id: 'ds-doomed', sort_order: 1 });
    const { result, removeMutate } = renderCombined(makeBuilderMap([keep, doomed]));

    // Dirty the map first. This is the precondition that froze the baseline.
    act(() => { result.current.handleOpacityChange('keep', 0.4); });
    expect(result.current.hasUnsavedChanges).toBe(true);

    act(() => { result.current.handleRemove('doomed'); });
    expect(removeMutate).toHaveBeenCalledOnce();
    const [, handlers] = removeMutate.mock.calls[0];
    act(() => { handlers.onSuccess(); });

    await act(async () => { await result.current.handleSave(); });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledOnce();
    const [{ diff }] = mockPatchMapLayersMutateAsync.mock.calls[0];
    expect(diff.removed).toBeUndefined();
    // The real edit still goes out.
    expect(diff.updated).toEqual([{ id: 'keep', opacity: 0.4 }]);
  });

  // The baseline prune used to run only when the
  // WHOLE batch succeeded. On a partial success the confirmed-deleted rows left
  // local state anyway, so they stayed in both baselines, the next Save
  // re-emitted them in diff.removed, and the stale-conflict recovery fired (or
  // the save failed outright when the refetch was unavailable).
  // Counterfactual: drop the prune from the partial branch and diff.removed
  // carries bulk-a.
  it('partial bulk delete prunes only the confirmed-deleted ids from the baselines', async () => {
    const keep = makeBuilderLayer({ id: 'keep', dataset_id: 'ds-keep', sort_order: 0 });
    const a = makeBuilderLayer({ id: 'bulk-a', dataset_id: 'ds-a', sort_order: 1 });
    const b = makeBuilderLayer({ id: 'bulk-b', dataset_id: 'ds-b', sort_order: 2 });
    const { result } = renderCombined(makeBuilderMap([keep, a, b]));

    act(() => { result.current.handleOpacityChange('keep', 0.4); });
    expect(result.current.hasUnsavedChanges).toBe(true);

    mockBulkDeleteLayers.mockResolvedValueOnce({
      deleted: ['bulk-a'],
      failed: [{ id: 'bulk-b', reason: 'layer in use' }],
    });
    await act(async () => { await result.current.handleBulkDelete(new Set(['bulk-a', 'bulk-b'])); });

    // bulk-b's delete failed, so it is back in local state.
    expect(result.current.localLayers.map((l) => l.id)).toContain('bulk-b');
    expect(result.current.localLayers.map((l) => l.id)).not.toContain('bulk-a');
    // Only the confirmed-deleted id leaves the refetch-resync baseline. Checked
    // before the save, because a clean map lets the apiLayers resync effect
    // rehydrate this ref from the (static) mock map payload.
    expect(result.current.savedLayerBaseline.map((l) => l.id)).toContain('bulk-b');
    expect(result.current.savedLayerBaseline.map((l) => l.id)).not.toContain('bulk-a');

    await act(async () => { await result.current.handleSave(); });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledOnce();
    const [{ diff }] = mockPatchMapLayersMutateAsync.mock.calls[0];
    // bulk-a is gone server-side, so naming it would be the stale diff again.
    // bulk-b is still on the server and still local, so it is not removed either.
    expect(diff.removed).toBeUndefined();
  });

  it('bulk delete after an unrelated edit emits no removed ids', async () => {
    const keep = makeBuilderLayer({ id: 'keep', dataset_id: 'ds-keep', sort_order: 0 });
    const a = makeBuilderLayer({ id: 'bulk-a', dataset_id: 'ds-a', sort_order: 1 });
    const b = makeBuilderLayer({ id: 'bulk-b', dataset_id: 'ds-b', sort_order: 2 });
    const { result } = renderCombined(makeBuilderMap([keep, a, b]));

    act(() => { result.current.handleOpacityChange('keep', 0.4); });
    expect(result.current.hasUnsavedChanges).toBe(true);

    mockBulkDeleteLayers.mockResolvedValueOnce({ deleted: ['bulk-a', 'bulk-b'], failed: [] });
    await act(async () => { await result.current.handleBulkDelete(new Set(['bulk-a', 'bulk-b'])); });

    await act(async () => { await result.current.handleSave(); });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledOnce();
    const [{ diff }] = mockPatchMapLayersMutateAsync.mock.calls[0];
    expect(diff.removed).toBeUndefined();
    expect(diff.updated).toEqual([{ id: 'keep', opacity: 0.4 }]);
  });
});

describe('clean checks after a save', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    __resetThumbnailDebounceForTests();
  });

  const layer = makeBuilderLayer({ id: 'layer-1', visible: true });
  const detailKey = queryKeys.maps.detail('map-1');
  const otherMap = makeBuilderMap([makeBuilderLayer({ id: 'layer-b', visible: true })], { id: 'map-2' });

  // mapData comes from the detail query, as in MapBuilderPage. The query
  // fetches only when invalidated, and each fetch waits for refetch(). With
  // `observe: false` the harness reads the cache without subscribing, so only
  // the hooks' own subscriptions can re-render it.
  function renderCached({ observe = true } = {}) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient.setQueryData(detailKey, makeBuilderMap([layer]));
    queryClient.setQueryData(queryKeys.maps.detail('map-2'), otherMap);
    const removeLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4];
    const addLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3];
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, createElement(MemoryRouter, null, children));
    const fetches: Array<(map: MapResponse) => void> = [];
    const useObservedDetail = (mapId: string) => useQuery<MapResponse>({
      queryKey: queryKeys.maps.detail(mapId),
      queryFn: () => new Promise<MapResponse>((resolve) => { fetches.push(resolve); }),
      staleTime: Infinity,
    }).data;
    const useUnobservedDetail = (mapId: string) => queryClient.getQueryData<MapResponse>(queryKeys.maps.detail(mapId));
    const useDetail = observe ? useObservedDetail : useUnobservedDetail;
    const { result, rerender } = baseRenderHook(({ mapId }: { mapId: string }) =>
      useCombinedBuilder(useDetail(mapId), mapId, addLayerMutation, removeLayerMutation),
    { wrapper, initialProps: { mapId: 'map-1' } });
    // Query observers notify on a timer, so wait one out.
    const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
    // Answers the detail fetch the save's invalidation started.
    const refetch = (map: MapResponse) => act(async () => {
      expect(fetches).toHaveLength(1);
      fetches.shift()!(map);
      await flush();
    });
    // Delivers detail data with no fetch pending, as a refetch landing mid-save does.
    const deliver = (map: MapResponse) => act(async () => {
      queryClient.setQueryData(detailKey, map);
      await flush();
    });
    const cachedMap = () => queryClient.getQueryData<MapResponse>(detailKey)!;
    const switchTo = (mapId: string) => act(() => rerender({ mapId }));
    return { result, refetch, deliver, cachedMap, switchTo };
  }

  // Start a save whose requests wait for finishSave().
  function startSave(result: { current: { handleSave: () => Promise<void> } }) {
    const pending: Array<() => void> = [];
    const hold = (payload: { id: string }) =>
      new Promise((resolve) => { pending.push(() => resolve({ id: payload.id, layers: [] })); });
    mockPatchMapLayersMutateAsync.mockImplementation(hold);
    mockUpdateMapMutateAsync.mockImplementation(hold);
    let saving!: Promise<void>;
    act(() => { saving = result.current.handleSave(); });
    return () => act(async () => {
      // The PATCH resolves before the metadata PUT is sent.
      while (pending.length) {
        pending.shift()!();
        await Promise.resolve();
      }
      await saving;
    });
  }

  const toggle = (result: { current: { handleToggleVisibility: (id: string) => void } }, layerId = 'layer-1') =>
    act(() => result.current.handleToggleVisibility(layerId));
  const layerVisible = (layers: MapLayerResponse[]) => layers.find((l) => l.id === 'layer-1')?.visible;
  const savedMap = () => makeBuilderMap([{ ...layer, visible: false }]);

  // Hide the layer, save, and show it again before the save resolves.
  async function showDuringSave() {
    const out = renderCached();
    toggle(out.result);
    const finishSave = startSave(out.result);
    toggle(out.result);
    await finishSave();
    return out;
  }

  it('keeps a mid-save visibility edit unsaved through the refetch', async () => {
    const { result, refetch } = await showDuringSave();
    await refetch(savedMap());

    expect(result.current.hasUnsavedChanges).toBe(true);
    expect(layerVisible(result.current.localLayers)).toBe(true);
  });

  it('compares a later toggle pair against the saved layers, not the pre-save ones', async () => {
    const { result, refetch } = await showDuringSave();
    await refetch(savedMap());

    toggle(result);
    toggle(result);

    expect(layerVisible(result.current.localLayers)).toBe(true);
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('waits for the refetch before an undo can read as saved', async () => {
    const { result, refetch } = await showDuringSave();

    toggle(result);
    expect(result.current.hasUnsavedChanges).toBe(true);
    expect(layerVisible(result.current.localLayers)).toBe(false);

    await refetch(savedMap());
    expect(result.current.hasUnsavedChanges).toBe(false);
    expect(layerVisible(result.current.localLayers)).toBe(false);
  });

  it('keeps showing the saved layers while the refetch is pending', async () => {
    const { result } = renderCached();
    toggle(result);
    const finishSave = startSave(result);
    await finishSave();

    expect(result.current.hasUnsavedChanges).toBe(false);
    expect(layerVisible(result.current.localLayers)).toBe(false);
  });

  it('fences the clean check after a save whose PATCH landed but whose PUT failed', async () => {
    const { result, refetch } = renderCached();
    mockPatchMapLayersMutateAsync.mockResolvedValue({ id: 'map-1', layers: [] });
    mockUpdateMapMutateAsync.mockRejectedValue(new Error('metadata PUT failed'));
    toggle(result);
    await act(async () => { await result.current.handleSave(); });

    toggle(result);
    expect(result.current.hasUnsavedChanges).toBe(true);

    await refetch(savedMap());
    expect(result.current.hasUnsavedChanges).toBe(true);
    expect(layerVisible(result.current.localLayers)).toBe(true);

    toggle(result);
    expect(result.current.hasUnsavedChanges).toBe(false);
  });

  it('lifts the fence on data fetched after the save even when a refetch landed before it settled', async () => {
    const { result, refetch, deliver } = renderCached();
    toggle(result);
    const finishSave = startSave(result);
    await deliver(savedMap());
    toggle(result);
    await finishSave();

    toggle(result);
    expect(result.current.hasUnsavedChanges).toBe(true);

    await refetch(savedMap());
    expect(result.current.hasUnsavedChanges).toBe(false);
    expect(layerVisible(result.current.localLayers)).toBe(false);
  });

  it('lifts the fence when the post-save refetch returns unchanged data', async () => {
    const { result, deliver, cachedMap } = renderCached({ observe: false });
    toggle(result);
    const finishSave = startSave(result);
    await deliver(savedMap());
    await finishSave();

    toggle(result);
    toggle(result);
    expect(result.current.hasUnsavedChanges).toBe(true);

    const cached = cachedMap();
    await deliver(structuredClone(cached));
    // Structural sharing keeps the cached object, so mapData doesn't change.
    expect(cachedMap()).toBe(cached);
    expect(result.current.hasUnsavedChanges).toBe(false);
  });

  type Builder = ReturnType<typeof renderCached>['result']['current'];
  it.each<[string, (b: Builder) => void, (b: Builder) => void]>([
    ['rename', (b) => b.setLocalName('New Name'), (b) => b.setLocalName('Test Map')],
    ['basemap change', (b) => b.setLocalBasemap('dark-matter'), (b) => b.setLocalBasemap(resolveBasemapId('positron'))],
  ])('keeps a mid-save %s undone unsaved when a toggle pair follows before the refetch', async (_, edit, undo) => {
    const { result } = renderCached();
    act(() => {
      edit(result.current);
      result.current.setHasUnsavedChanges(true);
    });
    const finishSave = startSave(result);
    act(() => undo(result.current));
    await finishSave();

    toggle(result);
    toggle(result);

    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  // Hide layer-1 on map-1, start its save, and switch to map-2 before it lands.
  function switchDuringSave() {
    const { result, switchTo } = renderCached();
    toggle(result);
    const finishSave = startSave(result);
    switchTo('map-2');
    return { result, finishSave };
  }

  it('leaves the next map clean-checkable when a save lands after a switch', async () => {
    const { result, finishSave } = switchDuringSave();
    await finishSave();

    toggle(result, 'layer-b');
    toggle(result, 'layer-b');

    expect(result.current.hasUnsavedChanges).toBe(false);
  });

  it('diffs the next map against its own layers when a save lands after a switch', async () => {
    const { result, finishSave } = switchDuringSave();
    await finishSave();
    mockPatchMapLayersMutateAsync.mockResolvedValue({ id: 'map-2', layers: [] });
    mockUpdateMapMutateAsync.mockResolvedValue({ id: 'map-2', layers: [] });

    toggle(result, 'layer-b');
    await act(async () => { await result.current.handleSave(); });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenLastCalledWith({
      id: 'map-2',
      diff: { updated: [{ id: 'layer-b', visible: false }] },
    });
  });

  it('lets another map save and clean-check while one save is in flight', async () => {
    const { result, finishSave } = switchDuringSave();

    toggle(result, 'layer-b');
    toggle(result, 'layer-b');
    expect(result.current.hasUnsavedChanges).toBe(false);

    toggle(result, 'layer-b');
    let second!: Promise<void>;
    act(() => { second = result.current.handleSave(); });
    expect(mockPatchMapLayersMutateAsync).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'map-2' }));
    await finishSave();
    await act(async () => { await second; });
  });

  it('ignores a second save while the first is in flight', async () => {
    const { result } = renderCached();
    toggle(result);
    const finishSave = startSave(result);

    let second!: Promise<void>;
    act(() => { second = result.current.handleSave(); });
    await finishSave();
    await act(async () => { await second; });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledOnce();
  });
});
