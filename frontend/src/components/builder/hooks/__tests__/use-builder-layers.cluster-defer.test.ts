/**
 * Bug-bash regression: render-mode switch to/from CLUSTER must NOT be applied
 * imperatively via swapLayerOnMap.
 *
 * Cluster layers get a per-layer GeoJSON/server-tile source (`source-<id>`) that
 * differs from the shared vector source (`source-data-<table>`) and does not
 * exist yet when switching in. The imperative same-source swapLayerOnMap added
 * the cluster layer to that not-yet-created source ("source ... not found") and
 * then collided with the reactive syncMapComposition reconcile ("layer ...
 * already exists"). The fix defers cluster transitions (entering OR leaving) to
 * the reactive sync — so swapLayerOnMap (and thus map.addLayer) must NOT run for
 * them, while same-source swaps (e.g. heatmap) still apply imperatively.
 *
 * Worker-OOM note (mirrors use-builder-layers.swap-idle-retry.test.ts): mapData
 * MUST be created outside renderHook and passed as a stable reference.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import {
  makeBuilderLayer,
  makeBuilderMap,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import type { MapLayerResponse } from '@/types/api';

type MaplibreMap = import('maplibre-gl').Map;

const LAYER_ID = 'layer-cluster-defer';

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return makeBuilderLayer({
    id: LAYER_ID,
    dataset_id: 'ds-cluster',
    dataset_geometry_type: 'Point',
    dataset_table_name: 'cities',
    dataset_feature_count: 1000,
    layer_type: 'vector_geolens',
    ...overrides,
  });
}

function makeLoadedMapStub(existingLayerIds: string[] = []): MaplibreMap {
  const existing = new Set(existingLayerIds);
  return {
    isStyleLoaded: vi.fn(() => true),
    getLayer: vi.fn((id: string) => (existing.has(id) ? { id } : undefined)),
    getSource: vi.fn(() => ({ tiles: ['/tiles/mock/{z}/{x}/{y}.pbf'] })),
    addSource: vi.fn(),
    removeSource: vi.fn(),
    addLayer: vi.fn((spec: { id: string }) => { existing.add(spec.id); }),
    removeLayer: vi.fn(),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    setFilter: vi.fn(),
    moveLayer: vi.fn(),
    setLayerZoomRange: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    once: vi.fn(),
    getStyle: vi.fn(() => ({ layers: [] })),
    fitBounds: vi.fn(),
    setTransformRequest: vi.fn(),
    resize: vi.fn(),
    loaded: vi.fn(() => true),
  } as unknown as MaplibreMap;
}

function renderBuilderLayersHook(
  mapData: ReturnType<typeof makeBuilderMap>,
  mapRef: React.RefObject<MaplibreMap | null>,
) {
  const addLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3];
  const removeLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4];
  return renderHook(() =>
    useBuilderLayers(mapData, mapRef, 'map-cluster', addLayerMutation, removeLayerMutation),
  );
}

describe('render-mode switch — cluster transitions defer to reactive sync', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('entering cluster does NOT imperatively add a layer (deferred to syncMapComposition)', () => {
    const layer = makeLayer();
    const mapData = makeBuilderMap([layer]);
    const mapStub = makeLoadedMapStub([`layer-${LAYER_ID}`]);
    const mapRef = { current: mapStub } as React.RefObject<MaplibreMap | null>;

    const { result } = renderBuilderLayersHook(mapData, mapRef);

    act(() => {
      result.current.handleRenderModeChange(LAYER_ID, 'cluster');
    });

    // The crash was an imperative addLayer against a not-yet-created cluster
    // source. The reactive sync owns cluster now → no imperative addLayer here.
    expect(mapStub.addLayer).not.toHaveBeenCalled();
  });

  it('leaving cluster (→ points) also defers — no imperative addLayer', () => {
    const layer = makeLayer({
      style_config: { render_mode: 'cluster', builder: { clusterRadius: 48, clusterMaxZoom: 14 } } as MapLayerResponse['style_config'],
    });
    const mapData = makeBuilderMap([layer]);
    const mapStub = makeLoadedMapStub([`layer-${LAYER_ID}`]);
    const mapRef = { current: mapStub } as React.RefObject<MaplibreMap | null>;

    const { result } = renderBuilderLayersHook(mapData, mapRef);

    act(() => {
      result.current.handleRenderModeChange(LAYER_ID, 'points');
    });

    expect(mapStub.addLayer).not.toHaveBeenCalled();
  });

  it('control: a same-source swap (heatmap) STILL applies imperatively (addLayer called)', () => {
    const layer = makeLayer();
    const mapData = makeBuilderMap([layer]);
    const mapStub = makeLoadedMapStub([`layer-${LAYER_ID}`]);
    const mapRef = { current: mapStub } as React.RefObject<MaplibreMap | null>;

    const { result } = renderBuilderLayersHook(mapData, mapRef);

    act(() => {
      result.current.handleRenderModeChange(LAYER_ID, 'heatmap');
    });

    // Heatmap stays on the shared source, so the imperative swap is safe + used.
    expect(mapStub.addLayer).toHaveBeenCalled();
  });
});
