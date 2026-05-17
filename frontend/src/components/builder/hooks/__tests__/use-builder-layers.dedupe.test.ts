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
import type { MapLayerResponse, MapResponse } from '@/types/api';

type MaplibreMap = import('maplibre-gl').Map;

function makeMockLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-a',
    dataset_id: 'ds-1',
    dataset_name: 'Test',
    dataset_geometry_type: 'Point',
    dataset_table_name: 'shared_points',
    visible: true,
    opacity: 1,
    paint: { 'circle-color': '#2255aa' },
    layout: {},
    sort_order: 0,
    filter: null,
    display_name: null,
    layer_type: 'vector_geolens',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: 100,
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

function createMockMap(initial?: { sources?: string[]; layers?: string[] }) {
  const sources = new Set<string>(initial?.sources ?? []);
  const layers = new Set<string>(initial?.layers ?? []);
  return {
    getSource: vi.fn((id: string) =>
      sources.has(id) ? { tiles: ['/tiles/mock/{z}/{x}/{y}.pbf'] } : null,
    ),
    addSource: vi.fn((id: string) => { sources.add(id); }),
    removeSource: vi.fn((id: string) => { sources.delete(id); }),
    getLayer: vi.fn((id: string) => (layers.has(id) ? { id } : null)),
    addLayer: vi.fn((layer: { id: string }) => { layers.add(layer.id); }),
    removeLayer: vi.fn((id: string) => { layers.delete(id); }),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    setFilter: vi.fn(),
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({ layers: [] })),
    moveLayer: vi.fn(),
    setLayerZoomRange: vi.fn(),
    fitBounds: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    setTransformRequest: vi.fn(),
    resize: vi.fn(),
  } as unknown as MaplibreMap;
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
});
