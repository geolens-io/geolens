/**
 * Focused tests for handleDuplicateRendering — B-004b / audit LM-02.
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
import type { MapLayerResponse, MapResponse } from '@/types/api';
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
    const groupRow = makeMockLayer({ id: 'group-1', sort_order: 1, layer_type: 'group:folder' });
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
});
