/**
 * fix(#392): focused tests for handleDuplicateRendering. (audit B-004b/LM-02)
 *
 * Duplicating a layer that lives inside a folder group must produce a copy
 * that stays inside that same group, positioned adjacent to the source —
 * not appended at the stack bottom with parent_group_id lost.
 *
 * Mirrors the renderHook + mutation-mock setup from
 * use-builder-layers.add-dataset.test.ts (no per-file vi.mock, non-empty
 * layers fixture — see that file's header comment for the worker-exit
 * root-cause this convention avoids).
 */

import { describe, it, expect } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import {
  makeBuilderLayer,
  makeBuilderMap,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import type { MapLayerResponse, MapResponse, StyleConfig } from '@/types/api';
import { vi } from 'vitest';

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

describe('handleDuplicateRendering — grouped-duplicate positioning (B-004b / LM-02)', () => {
  it('Test 2: duplicating a grouped layer keeps parent_group_id and splices adjacent to the source', () => {
    const before = makeMockLayer({ id: 'before', sort_order: 0 });
    // fix(#392): 'group:folder' is a frontend-only synthetic layer_type (GroupedLayer); cast only.
    const groupRow = { ...makeMockLayer({ id: 'group-1', sort_order: 1 }), layer_type: 'group:folder' } as unknown as MapLayerResponse;
    const source = {
      ...makeMockLayer({ id: 'src', sort_order: 2 }),
      parent_group_id: 'group-1',
    } as GroupedLayer as MapLayerResponse;
    const after = makeMockLayer({ id: 'after', sort_order: 3 });

    const { result, mutate } = renderBuilderLayers(makeMapData([before, groupRow, source, after]));

    act(() => {
      result.current.handleDuplicateRendering('src');
    });

    expect(mutate).toHaveBeenCalledOnce();
    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'dup-1', dataset_id: 'ds-1' }); });

    const updated = result.current.localLayers as GroupedLayer[];
    const dup = updated.find((l) => l.id === 'dup-1');
    expect(dup).toBeDefined();
    expect(dup!.parent_group_id).toBe('group-1');

    // Spliced immediately after the source, inside the group block.
    const srcIdx = updated.findIndex((l) => l.id === 'src');
    const dupIdx = updated.findIndex((l) => l.id === 'dup-1');
    expect(dupIdx).toBe(srcIdx + 1);

    // Dirty flag set so the frontend-only group membership survives Save.
    expect(result.current.hasUnsavedChanges).toBe(true);

    // Baseline carries the pure server layer (no parent_group_id).
    const baselineEntry = result.current.savedLayerBaseline.find((l) => l.id === 'dup-1') as GroupedLayer | undefined;
    expect(baselineEntry).toBeDefined();
    expect(baselineEntry?.parent_group_id).toBeUndefined();
  });

  it('Test 3: duplicating a loose (ungrouped) layer is unchanged apart from adjacent positioning', () => {
    const source = makeMockLayer({ id: 'src', sort_order: 0 });
    const other = makeMockLayer({ id: 'other', sort_order: 1 });

    const { result, mutate } = renderBuilderLayers(makeMapData([source, other]));

    act(() => {
      result.current.handleDuplicateRendering('src');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'dup-2', dataset_id: 'ds-1' }); });

    const updated = result.current.localLayers as GroupedLayer[];
    const dup = updated.find((l) => l.id === 'dup-2');
    expect(dup).toBeDefined();
    expect(dup!.parent_group_id ?? null).toBeNull();

    const srcIdx = updated.findIndex((l) => l.id === 'src');
    const dupIdx = updated.findIndex((l) => l.id === 'dup-2');
    expect(dupIdx).toBe(srcIdx + 1);
  });

  // fix(#392): a NON-grouped duplicate must also mark the map dirty.
  // The splice in handleDuplicateRendering's onSuccess renumbers sort_order
  // for the FULL local array unconditionally (adjacent-insert, not append) —
  // this is a real, unpersisted diff regardless of grouping. Before the fix,
  // setHasUnsavedChanges(true) was only called when sourceParentGroupId was
  // truthy, so this non-grouped case left hasUnsavedChanges false. That let
  // addLayerMutation's own query-invalidation-triggered refetch run the
  // `!hasUnsavedChanges`-gated apiLayers resync effect and silently overwrite
  // the just-spliced adjacent placement with server order before Save —
  // reproducing the race the unit test's bare `vi.fn()` mutation mock can't
  // otherwise observe. This test fails on pre-fix code (hasUnsavedChanges
  // would be false here). (audit CR-01)
  it('Test 3b: duplicating a loose (ungrouped) layer marks hasUnsavedChanges true so the query-invalidation resync cannot revert the adjacent splice (CR-01)', () => {
    const source = makeMockLayer({ id: 'src', sort_order: 0 });
    const other = makeMockLayer({ id: 'other', sort_order: 1 });

    const { result, mutate } = renderBuilderLayers(makeMapData([source, other]));
    expect(result.current.hasUnsavedChanges).toBe(false);

    act(() => {
      result.current.handleDuplicateRendering('src');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'dup-2b', dataset_id: 'ds-1' }); });

    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('Test 4: savedLayerBaselineRef receives the pure server createdLayer without parent_group_id', () => {
    const source = {
      ...makeMockLayer({ id: 'src', sort_order: 0 }),
      parent_group_id: 'group-1',
    } as GroupedLayer as MapLayerResponse;

    const { result, mutate } = renderBuilderLayers(makeMapData([source]));

    act(() => {
      result.current.handleDuplicateRendering('src');
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    act(() => { onSuccess({ id: 'dup-3', dataset_id: 'ds-1' }); });

    const baselineEntry = result.current.savedLayerBaseline.find((l) => l.id === 'dup-3');
    expect(baselineEntry).toEqual({ id: 'dup-3', dataset_id: 'ds-1' });
  });

  // fix(#392): a layer moved out of a group locally, then
  // duplicated BEFORE Save, must not carry the stale style_config.builder.
  // folderGroupId to the backend. buildDuplicateRenderingInput copies
  // style_config verbatim from the current in-memory layer, so if
  // handleMoveLayerOutOfGroup only cleared the frontend-only parent_group_id
  // (leaving style_config.builder.folderGroupId intact), the duplicate would
  // be persisted with the stale pointer — and the next server resync would
  // silently re-group it via hydrateFolderGroupLayers, which reads
  // style_config, not parent_group_id. This test fails on pre-fix code. (audit CR-01, second facet)
  it('Test 5: duplicating a layer just moved out of a group does not resurrect the stale folderGroupId in the outgoing style_config', () => {
    const groupLayer = { ...makeMockLayer({ id: 'group-1' }), layer_type: 'group:folder' } as unknown as MapLayerResponse;
    const childLayer = {
      ...makeMockLayer({
        id: 'src',
        sort_order: 1,
        // fix(#392): partial StyleConfig fixture (builder-only) — real runtime shape, cast only.
        style_config: { builder: { folderGroupId: 'group-1', folderGroupName: 'Group 1' } } as unknown as StyleConfig,
      }),
      parent_group_id: 'group-1',
    } as unknown as MapLayerResponse;

    const { result, mutate } = renderBuilderLayers(makeMapData([groupLayer, childLayer]));

    act(() => {
      result.current.handleMoveLayerOutOfGroup('src');
    });

    act(() => {
      result.current.handleDuplicateRendering('src');
    });

    expect(mutate).toHaveBeenCalledOnce();
    const [{ data }] = mutate.mock.calls[0];
    const outgoingBuilder = (data.style_config as { builder?: Record<string, unknown> } | null)?.builder;
    expect(outgoingBuilder?.folderGroupId).toBeUndefined();
  });

  // fix(#392): the multi-select
  // "Ungroup" bulk action (handleBulkUngroup, use-bulk-layer-actions.ts) is a
  // separate code path from handleMoveLayerOutOfGroup/handleUngroup and was
  // NOT touched by the fix that landed for Test 5. It only cleared the
  // frontend-only parent_group_id, leaving style_config.builder.folderGroupId
  // intact — so a layer bulk-ungrouped then duplicated before Save still
  // carries the stale group pointer to the backend. This test fails on
  // pre-fix code (outgoingBuilder?.folderGroupId would be 'group-1'). (audit CR-01, third facet)
  it('Test 6: duplicating a layer just bulk-ungrouped does not resurrect the stale folderGroupId in the outgoing style_config', () => {
    // Only the child is supplied — mounting apiLayers with a persisted
    // style_config.builder.folderGroupId auto-synthesizes the "group-1"
    // group:folder container row via hydrateFolderGroupLayers (mirrors how a
    // real map loads). Manually adding a second group:folder row with the
    // same id here would create a duplicate-id fixture bug, since the
    // hydration effect already produces one from the child's persisted
    // style_config.
    const childLayer = {
      ...makeMockLayer({
        id: 'src',
        sort_order: 1,
        // fix(#392): partial StyleConfig fixture (builder-only) — real runtime shape, cast only.
        style_config: { builder: { folderGroupId: 'group-1', folderGroupName: 'Group 1' } } as unknown as StyleConfig,
      }),
      parent_group_id: 'group-1',
    } as unknown as MapLayerResponse;

    const { result, mutate } = renderBuilderLayers(makeMapData([childLayer]));

    // Confirm the hydrated group row exists exactly once before ungrouping.
    const hydrated = result.current.localLayers as GroupedLayer[];
    expect(hydrated.filter((l) => l.id === 'group-1')).toHaveLength(1);

    act(() => {
      result.current.handleBulkUngroup(new Set(['group-1']));
    });

    act(() => {
      result.current.handleDuplicateRendering('src');
    });

    expect(mutate).toHaveBeenCalledOnce();
    const [{ data }] = mutate.mock.calls[0];
    const outgoingBuilder = (data.style_config as { builder?: Record<string, unknown> } | null)?.builder;
    expect(outgoingBuilder?.folderGroupId).toBeUndefined();
  });
});
