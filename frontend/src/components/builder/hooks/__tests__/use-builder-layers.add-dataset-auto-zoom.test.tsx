// fix(#1854): a fresh map (no saved view of its own) auto-adds a dataset via
// the ?add_dataset URL param but never zoomed to it, so it landed at the
// world-view default and the newly added layer could be off-screen. The
// ?add_dataset effect now zooms to the new layer once — but only via a
// watcher effect on `localLayers`, not directly from handleAddDataset's
// onSuccessCb: layersRef (which handleZoomToLayer reads) is only synced by
// the useLayoutEffect mirror on commit, so calling handleZoomToLayer
// synchronously inside onSuccess would race a still-stale ref (same hazard
// #554's codex fix documented for the add-layer merge itself). These tests
// exercise the real ?add_dataset flow end to end to prove the zoom actually
// fires, not just that the wiring compiles.
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

function renderWithAddDatasetParam(
  mapData: MapResponse,
  options: { startWithMapLoaded?: boolean } = {},
) {
  const { startWithMapLoaded = true } = options;
  const map = makeMapLibreMock();
  const mapRef = {
    current: startWithMapLoaded ? map : null,
  } as React.RefObject<MaplibreMap | null>;
  // fix(#1863 P2): mirrors MapBuilderPage's OWN pair — mapInstanceRef (read
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
        <MemoryRouter initialEntries={['/builder/map-1?add_dataset=ds-1']}>
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
      ),
    { wrapper: Wrapper },
  );

  // fix(#1863 P2): simulates BuilderMap's onLoad -> MapBuilderPage's
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
    simulateMapLoad,
  };
}

describe('?add_dataset auto-zoom (#1854)', () => {
  it('zooms to the newly added layer once it commits, on a fresh map with no saved view', () => {
    const mapData = makeBuilderMap([], { center_lng: null, center_lat: null });
    const { hook, mutate, fitBounds } = renderWithAddDatasetParam(mapData);

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

    // The layer landed in localLayers (P1-08 optimistic merge)...
    expect(hook.result.current.localLayers.map((l) => l.id)).toContain('new-layer-id');
    // ...and the auto-zoom watcher fired against the COMMITTED layer, so the
    // lookup inside handleZoomToLayer actually found dataset_extent_bbox.
    expect(fitBounds).toHaveBeenCalledTimes(1);
    expect(fitBounds.mock.calls[0][0]).toEqual([
      [-74.5, 40.5],
      [-73.5, 41.5],
    ]);
  });

  // fix(#1863 P2, codex round 1): on a cold builder entry the add-layer POST
  // can resolve — landing the layer in localLayers — before the lazily
  // loaded BuilderMap has finished mounting and firing onLoad. The old
  // watcher effect cleared pendingAutoZoomLayerIdRef as soon as the layer
  // appeared, regardless of map readiness, so handleZoomToLayer's `if
  // (!map) return;` silently swallowed the zoom and nothing ever retried it.
  it('retries the auto-zoom once the map finishes loading, when the layer commits first (cold entry)', () => {
    const mapData = makeBuilderMap([], { center_lng: null, center_lat: null });
    const { hook, mutate, fitBounds, simulateMapLoad } = renderWithAddDatasetParam(mapData, {
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
    const { mutate, fitBounds } = renderWithAddDatasetParam(mapData);

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
});
