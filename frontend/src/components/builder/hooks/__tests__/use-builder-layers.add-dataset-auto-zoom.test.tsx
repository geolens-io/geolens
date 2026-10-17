// The add-dataset entry intent adds its layer once and zooms a fresh map to it
// after the layer commits, not from handleAddDataset's onSuccess.
import { describe, it, expect, vi } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import {
  makeBuilderLayer,
  makeBuilderMap,
  makeMapLibreMock,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import type { MapResponse } from '@/types/api';

type MaplibreMap = import('maplibre-gl').Map;

function renderWithAddDatasetIntent(
  mapData: MapResponse,
  options: {
    startWithMapLoaded?: boolean;
    zoomAfterFit?: number;
    url?: string;
    addDatasetId?: string;
  } = {},
) {
  const { startWithMapLoaded = true, zoomAfterFit, url = '/maps/map-1' } = options;
  const addDatasetId = 'addDatasetId' in options ? options.addDatasetId : 'ds-1';
  const map = makeMapLibreMock({ zoomAfterFit });
  const mapRef = {
    current: startWithMapLoaded ? map : null,
  } as React.RefObject<MaplibreMap | null>;
  // Mirrors MapBuilderPage's OWN pair — mapInstanceRef (read
  // imperatively) and a reactive `mapInstance` state, both flipped together
  // in handleMapRef. `mapInstance` here is a plain mutable binding (not
  // React state) because this hook is rendered directly with renderHook, not
  // through MapBuilderPage; `simulateMapLoad` below re-invokes the hook
  // closure via `hook.rerender()` so the NEW value is what the next render
  // of useBuilderLayers actually receives as its 7th argument.
  let mapInstance: MaplibreMap | null = startWithMapLoaded ? map : null;
  const mutate = vi.fn();
  const addLayerMutation = { mutate } as unknown as Parameters<typeof useBuilderLayers>[3];
  const removeLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4];
  const saveBaselineSyncRef = {
    current: { add: vi.fn(), remove: () => {} },
  } as unknown as Parameters<typeof useBuilderLayers>[5];

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[url]}>
          {children}
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  const hook = renderHook(
    () =>
      useBuilderLayers(
        mapData,
        mapRef,
        'map-1',
        addLayerMutation,
        removeLayerMutation,
        saveBaselineSyncRef,
        mapInstance,
        addDatasetId,
      ),
    { wrapper: Wrapper },
  );

  // Simulates BuilderMap's onLoad -> MapBuilderPage's
  // handleMapRef, which sets mapInstanceRef.current synchronously BEFORE
  // calling setMapInstance — so the ref is always in sync by the time a
  // render sees the new mapInstance value.
  function simulateMapLoad() {
    mapRef.current = map;
    mapInstance = map;
    hook.rerender();
  }

  return {
    hook,
    mutate,
    fitBounds: map.fitBounds as unknown as ReturnType<typeof vi.fn>,
    setZoom: map.setZoom as unknown as ReturnType<typeof vi.fn>,
    simulateMapLoad,
  };
}

describe('add-dataset entry intent', () => {
  it('adds no layer from an add_dataset query parameter without the intent', () => {
    const mapData = makeBuilderMap([], { center_lng: null, center_lat: null });
    const { mutate } = renderWithAddDatasetIntent(mapData, {
      url: '/maps/map-1?add_dataset=ds-1',
      addDatasetId: undefined,
    });

    expect(mutate).not.toHaveBeenCalled();
  });


  it('zooms to the newly added layer once it commits, on a fresh map with no saved view', () => {
    const mapData = makeBuilderMap([], { center_lng: null, center_lat: null });
    const { hook, mutate, fitBounds } = renderWithAddDatasetIntent(mapData);

    // The effect fires handleAddDataset('ds-1', ...) on mount.
    expect(mutate).toHaveBeenCalledOnce();
    const [{ data }] = mutate.mock.calls[0];
    expect(data).toMatchObject({ dataset_id: 'ds-1' });

    const [, { onSuccess }] = mutate.mock.calls[0];
    const createdLayer = makeBuilderLayer({
      id: 'new-layer-id',
      dataset_id: 'ds-1',
      dataset_extent_bbox: [-74.5, 40.5, -73.5, 41.5],
    });
    act(() => {
      onSuccess(createdLayer);
    });

    // The layer landed in localLayers (optimistic merge)...
    expect(hook.result.current.localLayers.map((l) => l.id)).toContain('new-layer-id');
    // ...and the auto-zoom watcher fired against the COMMITTED layer, so the
    // lookup inside handleZoomToLayer actually found dataset_extent_bbox.
    expect(fitBounds).toHaveBeenCalledTimes(1);
    expect(fitBounds.mock.calls[0][0]).toEqual([
      [-74.5, 40.5],
      [-73.5, 41.5],
    ]);
  });

  // On a cold builder entry the add-layer POST
  // can resolve — landing the layer in localLayers — before the lazily
  // loaded BuilderMap has finished mounting and firing onLoad. The old
  // watcher effect cleared pendingAutoZoomLayerIdRef as soon as the layer
  // appeared, regardless of map readiness, so handleZoomToLayer's `if
  // (!map) return;` silently swallowed the zoom and nothing ever retried it.
  it('retries the auto-zoom once the map finishes loading, when the layer commits first (cold entry)', () => {
    const mapData = makeBuilderMap([], { center_lng: null, center_lat: null });
    const { hook, mutate, fitBounds, simulateMapLoad } = renderWithAddDatasetIntent(mapData, {
      startWithMapLoaded: false,
    });

    expect(mutate).toHaveBeenCalledOnce();
    const [, { onSuccess }] = mutate.mock.calls[0];
    const createdLayer = makeBuilderLayer({
      id: 'new-layer-id',
      dataset_id: 'ds-1',
      dataset_extent_bbox: [-74.5, 40.5, -73.5, 41.5],
    });
    act(() => {
      onSuccess(createdLayer);
    });

    // Layer landed, but the map instance does not exist yet — must NOT fire.
    expect(hook.result.current.localLayers.map((l) => l.id)).toContain('new-layer-id');
    expect(fitBounds).not.toHaveBeenCalled();

    // Map finishes loading afterward (BuilderMap onLoad -> handleMapRef).
    act(() => {
      simulateMapLoad();
    });

    expect(fitBounds).toHaveBeenCalledTimes(1);
    expect(fitBounds.mock.calls[0][0]).toEqual([
      [-74.5, 40.5],
      [-73.5, 41.5],
    ]);
  });

  it('does not auto-zoom a map that already has its own saved view', () => {
    const mapData = makeBuilderMap([], { center_lng: -73.9, center_lat: 40.7, zoom: 12 });
    const { mutate, fitBounds } = renderWithAddDatasetIntent(mapData);

    expect(mutate).toHaveBeenCalledOnce();
    const [, { onSuccess }] = mutate.mock.calls[0];
    const createdLayer = makeBuilderLayer({
      id: 'new-layer-id',
      dataset_id: 'ds-1',
      dataset_extent_bbox: [-74.5, 40.5, -73.5, 41.5],
    });
    act(() => {
      onSuccess(createdLayer);
    });

    expect(fitBounds).not.toHaveBeenCalled();
  });

  // "fresh map" means no PRIOR layers, not just no saved
  // center — a centerless map with an existing layer keeps BuilderMap's
  // own combined-bounds auto-fit, not this single-layer zoom.
  it('does not auto-zoom a centerless map that already has an existing layer', () => {
    const existingLayer = makeBuilderLayer({ id: 'existing-layer-id', dataset_id: 'ds-existing' });
    const mapData = makeBuilderMap([existingLayer], { center_lng: null, center_lat: null });
    const { mutate, fitBounds } = renderWithAddDatasetIntent(mapData);

    expect(mutate).toHaveBeenCalledOnce();
    const [, { onSuccess }] = mutate.mock.calls[0];
    const createdLayer = makeBuilderLayer({
      id: 'new-layer-id',
      dataset_id: 'ds-1',
      dataset_extent_bbox: [-74.5, 40.5, -73.5, 41.5],
    });
    act(() => {
      onSuccess(createdLayer);
    });

    expect(fitBounds).not.toHaveBeenCalled();
  });

  // A cold-entry add (BuilderMap not yet mounted) lands in
  // BuilderMap's own first-render baseline, so its auto-fit never detects
  // the change — this hook must take charge with the COMBINED bounds fit.
  it('runs a combined-bounds fit for a cold-entry add on a centerless map with an existing layer', () => {
    const existingLayer = makeBuilderLayer({
      id: 'existing-layer-id',
      dataset_id: 'ds-existing',
      dataset_extent_bbox: [-80, 35, -75, 40],
    });
    const mapData = makeBuilderMap([existingLayer], { center_lng: null, center_lat: null });
    const { hook, mutate, fitBounds, setZoom, simulateMapLoad } = renderWithAddDatasetIntent(mapData, {
      startWithMapLoaded: false,
    });

    expect(mutate).toHaveBeenCalledOnce();
    const [, { onSuccess }] = mutate.mock.calls[0];
    const createdLayer = makeBuilderLayer({
      id: 'new-layer-id',
      dataset_id: 'ds-1',
      dataset_extent_bbox: [-74.5, 40.5, -73.5, 41.5],
    });
    act(() => {
      onSuccess(createdLayer);
    });

    // Layer landed, but the map instance does not exist yet — must NOT fire.
    expect(hook.result.current.localLayers.map((l) => l.id)).toContain('new-layer-id');
    expect(fitBounds).not.toHaveBeenCalled();

    // Map finishes loading afterward (BuilderMap onLoad -> handleMapRef).
    act(() => {
      simulateMapLoad();
    });

    // The union of BOTH layers' bounds — not just the new layer's — and
    // exactly once (not also a redundant single-layer zoom).
    expect(fitBounds).toHaveBeenCalledTimes(1);
    expect(fitBounds.mock.calls[0][0]).toEqual([
      [-80, 35],
      [-73.5, 41.5],
    ]);
    // The mock reports a normal post-fit zoom (10, the default) — no clamp needed.
    expect(setZoom).not.toHaveBeenCalled();
  });

  // BuilderMap's own auto-fit clamps a wide fit to zoom 2+
  // (complex vector tiles fail to render below it) — the cold-entry
  // combined fit must apply the same clamp.
  it('clamps a wide cold-entry combined fit to zoom 2, mirroring BuilderMap', () => {
    const existingLayer = makeBuilderLayer({
      id: 'existing-layer-id',
      dataset_id: 'ds-existing',
      dataset_extent_bbox: [-160, -70, -20, 10],
    });
    const mapData = makeBuilderMap([existingLayer], { center_lng: null, center_lat: null });
    const { mutate, fitBounds, setZoom, simulateMapLoad } = renderWithAddDatasetIntent(mapData, {
      startWithMapLoaded: false,
      zoomAfterFit: 1,
    });

    const [, { onSuccess }] = mutate.mock.calls[0];
    const createdLayer = makeBuilderLayer({
      id: 'new-layer-id',
      dataset_id: 'ds-1',
      dataset_extent_bbox: [20, 10, 160, 70],
    });
    act(() => {
      onSuccess(createdLayer);
    });
    act(() => {
      simulateMapLoad();
    });

    expect(fitBounds).toHaveBeenCalledTimes(1);
    // Duration: 0 is what makes this fit settle synchronously —
    // without it the mock (like real MapLibre's flyTo) would not have
    // applied zoomAfterFit yet, and the clamp below would read stale zoom.
    expect(fitBounds.mock.calls[0][1]).toMatchObject({ duration: 0 });
    expect(setZoom).toHaveBeenCalledWith(2);
  });
});
