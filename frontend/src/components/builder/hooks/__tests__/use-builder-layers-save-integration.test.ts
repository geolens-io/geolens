/**
 * fix(#392): duplicate-layer-on-save P1 regression.
 *
 * useBuilderLayers' handleAddDataset / handleDuplicateRendering insert a
 * server-created layer into localLayers AND mark the map dirty in the SAME
 * update (the WR-02/CR-01 sort_order-renumber fix requires this — the sibling
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
import { act } from '@testing-library/react';
import { useRef } from 'react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import { useBuilderSave, __resetThumbnailDebounceForTests } from '@/components/builder/hooks/use-builder-save';
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
  // fix(#392): the SAME callback-ref bridge MapBuilderPage owns between
  // useBuilderLayers and useBuilderSave — see MapBuilderPage.tsx (~line 204+7)
  // and use-builder-save.ts's `saveBaselineSyncRef` effect.
  const saveBaselineSyncRef = useRef<(layer: MapLayerResponse) => void>(() => {});

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
    hasThumbnail: true,
    saveBaselineSyncRef,
  });

  return { ...layers, ...save };
}

function renderCombined(mapData: MapResponse, mapId = 'map-1') {
  const mutate = vi.fn();
  const addLayerMutation = { mutate } as unknown as Parameters<typeof useBuilderLayers>[3];
  const removeLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4];

  const out = renderHook(() => useCombinedBuilder(mapData, mapId, addLayerMutation, removeLayerMutation));
  return { ...out, mutate };
}

describe('fix(#392): duplicate-layer-on-save P1 — Save-diff baseline sync', () => {
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

    // Sanity: the add did in fact dirty the map (WR-02 sibling-renumber fix) and
    // the created layer is immediately visible (P1-08 optimistic merge).
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
