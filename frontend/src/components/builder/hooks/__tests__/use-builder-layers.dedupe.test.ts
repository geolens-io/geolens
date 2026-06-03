/**
 * Phase 1050 SF-04: deduped MapLibre source contract for use-builder-layers.
 *
 * - swapLayerOnMap must route through `getSourceIdForLayer` so it reads/writes
 *   the deduped `source-data-${dataset_table_name}` source for non-cluster
 *   vector layers (not the legacy per-layer `source-${layer.id}`).
 * - handleAiRemoveLayer must NOT directly `removeSource` for the per-layer
 *   key — that would silently no-op (the key no longer exists), and worse,
 *   if the dedupe key happened to match it could rip out a source still
 *   referenced by other layers. The desired-set prune in the next
 *   `syncFromState` invocation owns source cleanup (reference-count safe).
 */
import { describe, it, expect, vi } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import {
  makeBuilderLayer,
  makeBuilderMap,
  makeMapLibreMock,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import type { MapLayerResponse, MapResponse } from '@/types/api';

type MaplibreMap = import('maplibre-gl').Map;

function makeMockLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return makeBuilderLayer({
    id: 'layer-a',
    dataset_geometry_type: 'Point',
    dataset_table_name: 'shared_points',
    paint: { 'circle-color': '#2255aa' },
    dataset_feature_count: 100,
    ...overrides,
  });
}

function makeMapData(layers: MapLayerResponse[] = []): MapResponse {
  return makeBuilderMap(layers);
}

function createMockMap(initial?: { sources?: string[]; layers?: string[] }) {
  return makeMapLibreMock(initial);
}

function renderBuilder(mapData: MapResponse, mapRef: React.RefObject<MaplibreMap | null>) {
  const addLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3];
  const removeLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4];
  return renderHook(() =>
    useBuilderLayers(mapData, mapRef, 'map-1', addLayerMutation, removeLayerMutation),
  );
}

describe('use-builder-layers Phase 1050 SF-04 dedupe contract', () => {
  it('handleAiRemoveLayer does NOT call map.removeSource directly — desired-set prune owns it', () => {
    // Two non-cluster vector layers share dataset_table_name 'shared_points'.
    // Removing one MUST NOT call removeSource (the deduped source is still
    // needed by layer-b; the per-layer key never existed). The next
    // syncFromState invocation owns source cleanup via the reference-count-
    // safe desired-set prune.
    const layerA = makeMockLayer({ id: 'a' });
    const layerB = makeMockLayer({ id: 'b' });
    // Seed the map with BOTH the deduped source AND a fictitious legacy
    // per-layer source `source-a`. The dedupe contract requires that
    // handleAiRemoveLayer's cleanup path NOT touch `source-a` either —
    // the old code's `removeSource(\`source-${layerId}\`)` would have
    // matched this seed and torn it down. We assert removeSource is never
    // called so the test fails loudly under the old per-layer code path.
    const map = createMockMap({
      sources: ['source-data-shared_points', 'source-a'],
      layers: ['layer-a', 'layer-b'],
    });
    const mapRef = { current: map } as React.RefObject<MaplibreMap | null>;
    const { result } = renderBuilder(makeMapData([layerA, layerB]), mapRef);

    act(() => {
      result.current.handleAiRemoveLayer('a');
    });

    // Critical: removeSource MUST NOT be invoked at all from this code path
    // — neither for the deduped key (still referenced) nor for the legacy
    // per-layer key (which would have ripped out source-a, a sibling layer's
    // dedupe key in the old per-layer scheme, when invoked with the wrong id).
    expect(map.removeSource).not.toHaveBeenCalled();
    // Per-layer COMPANION layers (label/outline/extrusion/arrow) and the
    // main layer-{id} ARE per-layer — those are still cleaned up imperatively.
    expect(map.removeLayer).toHaveBeenCalledWith('layer-a');
  });

  it('handleAiRemoveLayer marks unsaved-changes so the next sync prunes orphan sources', () => {
    const layerA = makeMockLayer({ id: 'a' });
    const map = createMockMap({ sources: [], layers: ['layer-a'] });
    const mapRef = { current: map } as React.RefObject<MaplibreMap | null>;
    const { result } = renderBuilder(makeMapData([layerA]), mapRef);

    act(() => {
      result.current.handleAiRemoveLayer('a');
    });

    // State was updated; the next syncFromState invocation will see the
    // deduped source has zero consumers and prune it (verified separately in
    // map-sync.dedupe.test.ts > "DOES remove a source when no remaining layer...").
    expect(result.current.localLayers.find((l) => l.id === 'a')).toBeUndefined();
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  // WR-01 (Phase 1050-rev): removeStaleSourcesAndLayers cannot derive
  // companion ids under the dedupe contract — the stripped sourceId yields
  // `data-${dataset_table_name}` instead of the real layer id. Verify both
  // non-AI removal paths (handleRemove single, handleBulkDelete batched)
  // imperatively clean per-layer companions, mirroring handleAiRemoveLayer.
  it('handleRemove imperatively removes per-layer companions (WR-01)', () => {
    const layerA = makeMockLayer({ id: 'a' });
    const map = createMockMap({
      sources: ['source-data-shared_points'],
      // Seed every companion suffix so we can assert they all get removed.
      layers: [
        'layer-a', 'layer-a-outline', 'layer-a-label',
        'layer-a-extrusion', 'layer-a-arrow',
        'layer-a-cluster', 'layer-a-cluster-count',
      ],
    });
    const mapRef = { current: map } as React.RefObject<MaplibreMap | null>;
    const { result } = renderBuilder(makeMapData([layerA]), mapRef);

    act(() => {
      result.current.handleRemove('a');
    });

    // Every companion suffix was torn down imperatively.
    expect(map.removeLayer).toHaveBeenCalledWith('layer-a');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-a-outline');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-a-label');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-a-extrusion');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-a-arrow');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-a-cluster');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-a-cluster-count');
    // Sources untouched here — desired-set prune owns source cleanup.
    expect(map.removeSource).not.toHaveBeenCalled();
  });

  it('handleBulkDelete imperatively removes per-layer companions for every id in the batch (WR-01)', async () => {
    const layerA = makeMockLayer({ id: 'a' });
    const layerB = makeMockLayer({ id: 'b' });
    const map = createMockMap({
      sources: ['source-data-shared_points'],
      layers: [
        'layer-a', 'layer-a-outline', 'layer-a-label',
        'layer-b', 'layer-b-outline',
      ],
    });
    const mapRef = { current: map } as React.RefObject<MaplibreMap | null>;
    const { result } = renderBuilder(makeMapData([layerA, layerB]), mapRef);

    // The bulk-delete API call will fail because we haven't mocked the
    // network layer — but the imperative cleanup runs BEFORE the API call,
    // so the assertions are still valid regardless of API outcome.
    await act(async () => {
      try {
        await result.current.handleBulkDelete(new Set(['a', 'b']));
      } catch {
        // ignore — fetch is unmocked, we only care about pre-API cleanup
      }
    });

    expect(map.removeLayer).toHaveBeenCalledWith('layer-a');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-a-outline');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-a-label');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-b');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-b-outline');
    // No removeSource calls — the desired-set prune in the next syncFromState
    // owns source teardown (and the deduped source may still be referenced
    // by other layers anyway).
    expect(map.removeSource).not.toHaveBeenCalled();
  });
});
