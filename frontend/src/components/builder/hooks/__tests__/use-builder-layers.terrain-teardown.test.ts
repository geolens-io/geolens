/**
 * Phase 999.17 Fix 2 (D-05 + Plan-Check Advisory A2) — terrain delete-teardown.
 *
 * When the DEM layer that backs active 3D terrain is deleted, terrain_config is
 * left dangling (it points at a dataset that no longer has a backing DEM layer).
 * D-05: auto-clear terrain_config + surface a NON-BLOCKING toast on that delete.
 *
 * Advisory A2 (critical): the teardown MUST key on DATASET IDENTITY, not "a DEM
 * layer was deleted." Only clear terrain_config (and toast) when the deleted
 * layer's dataset_id matches terrain_config.source_dataset_id. In a multi-DEM
 * map, deleting a DIFFERENT DEM layer must NOT clear terrain_config and must NOT
 * toast.
 *
 * Harness mirrors use-builder-layers.delete.test.ts (selective vi.mock on
 * @/api/maps + injected mutation spies) and adds a sonner spy so we can assert
 * the toast fires (or doesn't).
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

const toastSuccess = vi.fn();
const toastInfo = vi.fn();
const toastError = vi.fn();
vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    info: (...args: unknown[]) => toastInfo(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

const bulkDeleteSpy = vi.fn();
vi.mock('@/api/maps', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/maps')>();
  return {
    ...actual,
    removeLayerFromMapApi: vi.fn(),
    bulkDeleteLayersApi: (...args: unknown[]) => bulkDeleteSpy(...args),
  };
});

afterEach(() => {
  vi.clearAllMocks();
  cleanup();
});

const MAP_ID = 'map-1';

function makeDemLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return makeBuilderLayer({
    dataset_record_type: 'raster_dataset',
    is_dem: true,
    style_config: { render_mode: 'terrain' } as MapLayerResponse['style_config'],
    ...overrides,
  });
}

function makeMapWithTerrain(
  layers: MapLayerResponse[],
  sourceDatasetId: string,
): MapResponse {
  return {
    ...makeBuilderMap(layers),
    terrain_config: {
      enabled: true,
      source_dataset_id: sourceDatasetId,
      exaggeration: 1.5,
    },
  } as MapResponse;
}

function makeMapRef() {
  const mapInstance = {
    isStyleLoaded: () => true,
    getLayer: vi.fn().mockReturnValue({ id: 'mock' }),
    removeLayer: vi.fn(),
  };
  return { current: mapInstance } as unknown as React.RefObject<import('maplibre-gl').Map | null>;
}

function renderBuilderLayers(mapData: MapResponse, opts?: { removeFails?: boolean }) {
  const addLayerMutation = {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
  } as unknown as Parameters<typeof useBuilderLayers>[3];
  // Default removeLayerMutation: synchronously invoke onSuccess (success path).
  // When removeFails is set, synchronously invoke onError (rollback path) — used
  // by the HI-01 failure-rollback tests.
  const removeLayerMutation = {
    mutate: vi.fn((_vars, mutOpts) => {
      if (opts?.removeFails) { mutOpts?.onError?.(new Error('delete failed')); }
      else { mutOpts?.onSuccess?.(); }
    }),
    mutateAsync: vi.fn(),
  } as unknown as Parameters<typeof useBuilderLayers>[4];

  // fix(#392): 6th positional param bridging into useBuilderSave's Save-diff baseline.
  const saveBaselineSyncRef = { current: () => {} } as unknown as Parameters<typeof useBuilderLayers>[5];
  return renderHook(() =>
    useBuilderLayers(mapData, makeMapRef(), MAP_ID, addLayerMutation, removeLayerMutation, saveBaselineSyncRef),
  );
}

async function waitForInit() {
  await act(async () => {});
}

// ---------------------------------------------------------------------------
// handleRemove (single-layer delete) — D-05 + A2
// ---------------------------------------------------------------------------
describe('useBuilderLayers — terrain teardown on handleRemove (D-05/A2)', () => {
  it('clears terrain_config + non-blocking toast when the terrain-source DEM is deleted', async () => {
    const demTerrain = makeDemLayer({ id: 'dem-a', dataset_id: 'dem-ds-a', sort_order: 0 });
    const { result } = renderBuilderLayers(makeMapWithTerrain([demTerrain], 'dem-ds-a'));
    await waitForInit();

    expect(result.current.localTerrainConfig?.enabled).toBe(true);

    act(() => {
      result.current.handleRemove('dem-a');
    });

    expect(result.current.localTerrainConfig?.enabled).toBe(false);
    expect(result.current.localTerrainConfig?.source_dataset_id).toBeNull();
    // Two distinct success toasts fire: the generic "layer removed" (handleRemove
    // success path) AND the terrain-disabled teardown toast. Assert the
    // terrain-specific one fired (by resolved message) rather than a total count.
    const terrainToastFired = toastSuccess.mock.calls.some(
      ([msg]) => typeof msg === 'string' && /terrain/i.test(msg),
    );
    expect(terrainToastFired).toBe(true);
    expect(toastError).not.toHaveBeenCalled();
  });

  it('A2 negative: deleting a DIFFERENT DEM layer preserves terrain_config (no toast)', async () => {
    const demTerrain = makeDemLayer({ id: 'dem-a', dataset_id: 'dem-ds-a', sort_order: 0 });
    const otherDem = makeDemLayer({
      id: 'dem-b',
      dataset_id: 'dem-ds-b',
      style_config: { render_mode: 'hillshade' } as MapLayerResponse['style_config'],
      sort_order: 1,
    });
    const { result } = renderBuilderLayers(
      makeMapWithTerrain([demTerrain, otherDem], 'dem-ds-a'),
    );
    await waitForInit();

    act(() => {
      result.current.handleRemove('dem-b');
    });

    // terrain_config still points at dem-ds-a (its backing layer is untouched).
    expect(result.current.localTerrainConfig?.enabled).toBe(true);
    expect(result.current.localTerrainConfig?.source_dataset_id).toBe('dem-ds-a');
    // Only the generic "layer removed" toast — NOT the terrain-disabled toast.
    expect(toastSuccess).toHaveBeenCalledTimes(1);
    expect(toastSuccess).not.toHaveBeenCalledWith(
      expect.stringContaining('terrain'),
    );
  });

  it('preserves terrain_config when another DEM layer on the SAME dataset remains', async () => {
    const demTerrain = makeDemLayer({ id: 'dem-a', dataset_id: 'dem-ds-a', sort_order: 0 });
    const siblingSameDataset = makeDemLayer({
      id: 'dem-a2',
      dataset_id: 'dem-ds-a',
      style_config: { render_mode: 'hillshade' } as MapLayerResponse['style_config'],
      sort_order: 1,
    });
    const { result } = renderBuilderLayers(
      makeMapWithTerrain([demTerrain, siblingSameDataset], 'dem-ds-a'),
    );
    await waitForInit();

    act(() => {
      result.current.handleRemove('dem-a');
    });

    // The dataset still has a backing DEM layer (dem-a2) — terrain stays.
    expect(result.current.localTerrainConfig?.enabled).toBe(true);
    expect(result.current.localTerrainConfig?.source_dataset_id).toBe('dem-ds-a');
  });

  it('does not clear terrain_config when a non-DEM vector layer is deleted', async () => {
    const demTerrain = makeDemLayer({ id: 'dem-a', dataset_id: 'dem-ds-a', sort_order: 0 });
    const vector = makeBuilderLayer({ id: 'vec-1', dataset_id: 'vec-ds', sort_order: 1 });
    const { result } = renderBuilderLayers(
      makeMapWithTerrain([demTerrain, vector], 'dem-ds-a'),
    );
    await waitForInit();

    act(() => {
      result.current.handleRemove('vec-1');
    });

    expect(result.current.localTerrainConfig?.enabled).toBe(true);
    expect(result.current.localTerrainConfig?.source_dataset_id).toBe('dem-ds-a');
  });

  // HI-01 (999.17 gap-closure): when the optimistic terrain clear is followed by a
  // FAILED delete, both localLayers AND terrain_config must be restored — a failed
  // delete must not leave the DEM restored but terrain silently disabled.
  it('HI-01: restores localLayers AND terrain_config when the delete mutation fails', async () => {
    const demTerrain = makeDemLayer({ id: 'dem-a', dataset_id: 'dem-ds-a', sort_order: 0 });
    const { result } = renderBuilderLayers(
      makeMapWithTerrain([demTerrain], 'dem-ds-a'),
      { removeFails: true },
    );
    await waitForInit();

    expect(result.current.localTerrainConfig?.enabled).toBe(true);

    act(() => {
      result.current.handleRemove('dem-a');
    });

    // The DEM layer is restored in the stack.
    expect(result.current.localLayers.some((l) => l.id === 'dem-a')).toBe(true);
    // terrain_config is restored to its prior enabled state (NOT left cleared).
    expect(result.current.localTerrainConfig?.enabled).toBe(true);
    expect(result.current.localTerrainConfig?.source_dataset_id).toBe('dem-ds-a');
    expect(toastError).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleBulkDelete — D-05 + A2
// ---------------------------------------------------------------------------
describe('useBuilderLayers — terrain teardown on handleBulkDelete (D-05/A2)', () => {
  it('clears terrain_config + toast when the terrain-source DEM is in the bulk-delete set', async () => {
    bulkDeleteSpy.mockResolvedValue({ deleted: ['dem-a'], failed: [] });
    const demTerrain = makeDemLayer({ id: 'dem-a', dataset_id: 'dem-ds-a', sort_order: 0 });
    const vector = makeBuilderLayer({ id: 'vec-1', dataset_id: 'vec-ds', sort_order: 1 });
    const { result } = renderBuilderLayers(
      makeMapWithTerrain([demTerrain, vector], 'dem-ds-a'),
    );
    await waitForInit();

    await act(async () => {
      await result.current.handleBulkDelete(new Set(['dem-a']));
    });

    expect(result.current.localTerrainConfig?.enabled).toBe(false);
    expect(result.current.localTerrainConfig?.source_dataset_id).toBeNull();
  });

  it('A2 negative: bulk-deleting a DIFFERENT DEM preserves terrain_config', async () => {
    bulkDeleteSpy.mockResolvedValue({ deleted: ['dem-b'], failed: [] });
    const demTerrain = makeDemLayer({ id: 'dem-a', dataset_id: 'dem-ds-a', sort_order: 0 });
    const otherDem = makeDemLayer({
      id: 'dem-b',
      dataset_id: 'dem-ds-b',
      style_config: { render_mode: 'hillshade' } as MapLayerResponse['style_config'],
      sort_order: 1,
    });
    const { result } = renderBuilderLayers(
      makeMapWithTerrain([demTerrain, otherDem], 'dem-ds-a'),
    );
    await waitForInit();

    await act(async () => {
      await result.current.handleBulkDelete(new Set(['dem-b']));
    });

    expect(result.current.localTerrainConfig?.enabled).toBe(true);
    expect(result.current.localTerrainConfig?.source_dataset_id).toBe('dem-ds-a');
  });

  it('preserves terrain_config when a same-dataset DEM survives the bulk delete', async () => {
    bulkDeleteSpy.mockResolvedValue({ deleted: ['dem-a'], failed: [] });
    const demTerrain = makeDemLayer({ id: 'dem-a', dataset_id: 'dem-ds-a', sort_order: 0 });
    const siblingSameDataset = makeDemLayer({
      id: 'dem-a2',
      dataset_id: 'dem-ds-a',
      style_config: { render_mode: 'hillshade' } as MapLayerResponse['style_config'],
      sort_order: 1,
    });
    const { result } = renderBuilderLayers(
      makeMapWithTerrain([demTerrain, siblingSameDataset], 'dem-ds-a'),
    );
    await waitForInit();

    await act(async () => {
      await result.current.handleBulkDelete(new Set(['dem-a']));
    });

    expect(result.current.localTerrainConfig?.enabled).toBe(true);
    expect(result.current.localTerrainConfig?.source_dataset_id).toBe('dem-ds-a');
  });

  // HI-01: FULL bulk-delete failure — nothing was actually deleted, so both
  // localLayers and terrain_config must be restored to their prior state.
  it('HI-01: restores localLayers AND terrain_config on a FULL bulk-delete failure', async () => {
    bulkDeleteSpy.mockResolvedValue({
      deleted: [],
      failed: [{ id: 'dem-a', reason: 'server error' }],
    });
    const demTerrain = makeDemLayer({ id: 'dem-a', dataset_id: 'dem-ds-a', sort_order: 0 });
    const { result } = renderBuilderLayers(
      makeMapWithTerrain([demTerrain], 'dem-ds-a'),
    );
    await waitForInit();

    await act(async () => {
      await result.current.handleBulkDelete(new Set(['dem-a']));
    });

    expect(result.current.localLayers.some((l) => l.id === 'dem-a')).toBe(true);
    expect(result.current.localTerrainConfig?.enabled).toBe(true);
    expect(result.current.localTerrainConfig?.source_dataset_id).toBe('dem-ds-a');
  });

  // HI-01: PARTIAL failure where the terrain-source DEM is among the FAILURES —
  // it is restored to the stack, so terrain is still backed and terrain_config
  // must be restored rather than left silently disabled.
  it('HI-01: restores terrain_config when the terrain-source DEM is among the partial failures', async () => {
    // dem-a (terrain source) fails; vec-1 deletes successfully.
    bulkDeleteSpy.mockResolvedValue({
      deleted: ['vec-1'],
      failed: [{ id: 'dem-a', reason: 'server error' }],
    });
    const demTerrain = makeDemLayer({ id: 'dem-a', dataset_id: 'dem-ds-a', sort_order: 0 });
    const vector = makeBuilderLayer({ id: 'vec-1', dataset_id: 'vec-ds', sort_order: 1 });
    const { result } = renderBuilderLayers(
      makeMapWithTerrain([demTerrain, vector], 'dem-ds-a'),
    );
    await waitForInit();

    await act(async () => {
      await result.current.handleBulkDelete(new Set(['dem-a', 'vec-1']));
    });

    // The terrain-source DEM is restored, so terrain stays backed → config restored.
    expect(result.current.localLayers.some((l) => l.id === 'dem-a')).toBe(true);
    expect(result.current.localTerrainConfig?.enabled).toBe(true);
    expect(result.current.localTerrainConfig?.source_dataset_id).toBe('dem-ds-a');
  });
});
