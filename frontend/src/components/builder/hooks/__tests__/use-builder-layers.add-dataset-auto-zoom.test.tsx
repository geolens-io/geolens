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

function renderWithAddDatasetParam(mapData: MapResponse) {
  const map = makeMapLibreMock();
  const mapRef = { current: map } as React.RefObject<MaplibreMap | null>;
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
      ),
    { wrapper: Wrapper },
  );

  return { hook, mutate, fitBounds: map.fitBounds as unknown as ReturnType<typeof vi.fn> };
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
