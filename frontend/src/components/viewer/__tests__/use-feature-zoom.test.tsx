import { act, renderHook } from '@testing-library/react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { SharedLayerResponse } from '@/types/api';
import { useMapFeatureHighlight } from '@/components/dataset/hooks/use-map-feature-highlight';
import { useFeatureZoom } from '../hooks/use-feature-zoom';

const drawn = vi.hoisted(() => ({ source: true }));
vi.mock('../map-data-table', () => ({ layerHighlightSource: () => (drawn.source ? { source: 'tiles' } : null) }));

const layer = { id: 'layer-1' } as SharedLayerResponse;
const feature = { id: 7, bbox: [-74, 40, -73.9, 40.1] as [number, number, number, number] };

/** A map that records its style layers and lets the test end a camera flight. */
function fakeMap() {
  const fitBounds = vi.fn();
  const layers = new Set<string>();
  const sources = new Set(['tiles']);
  const listeners = new Map<string, Set<() => void>>();
  const map = {
    isStyleLoaded: () => true,
    getStyle: () => ({}),
    getLayer: (id: string) => (layers.has(id) ? {} : undefined),
    getSource: (id: string) => (sources.has(id) ? {} : undefined),
    addLayer: ({ id }: { id: string }) => layers.add(id),
    removeLayer: (id: string) => layers.delete(id),
    addSource: (id: string) => sources.add(id),
    removeSource: (id: string) => sources.delete(id),
    fitBounds,
    on: () => undefined,
    off: (event: string, listener: () => void) => listeners.get(event)?.delete(listener),
    once: (event: string, listener: () => void) => {
      listeners.set(event, (listeners.get(event) ?? new Set()).add(listener));
    },
  } as unknown as MaplibreMap;
  const fire = (event: string) => [...(listeners.get(event) ?? [])].forEach((listener) => listener());
  return { map, fitBounds, layers, endFlight: () => fire('moveend'), drawn: () => fire('idle') };
}

function reduceMotion(reduce: boolean) {
  vi.stubGlobal('matchMedia', () => ({ matches: reduce }));
}

beforeEach(() => {
  drawn.source = true;
  vi.useFakeTimers();
  reduceMotion(false);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const lit = (layers: Set<string>) => layers.has('dashboard-feature-highlight-line');

describe('useFeatureZoom', () => {
  it('counts the second from when the destination is drawn, not when the camera stops', () => {
    const { map, layers, endFlight, drawn } = fakeMap();
    const { result } = renderHook(() => useFeatureZoom(map));
    act(() => result.current(layer, feature));
    expect(lit(layers)).toBe(true);

    act(() => vi.advanceTimersByTime(5000));
    expect(lit(layers)).toBe(true);

    act(() => endFlight());
    // Tiles for the destination arrive more than a second after the camera stopped.
    act(() => vi.advanceTimersByTime(1100));
    expect(lit(layers)).toBe(true);

    act(() => drawn());
    act(() => vi.advanceTimersByTime(999));
    expect(lit(layers)).toBe(true);
    act(() => vi.advanceTimersByTime(1));
    expect(lit(layers)).toBe(false);
  });

  it('clears the highlight after the bounded wait when the map never settles', () => {
    const { map, layers } = fakeMap();
    const { result } = renderHook(() => useFeatureZoom(map));
    act(() => result.current(layer, feature));
    act(() => vi.advanceTimersByTime(10_999));
    expect(lit(layers)).toBe(true);
    act(() => vi.advanceTimersByTime(1));
    expect(lit(layers)).toBe(false);
  });

  it('lets a new selection take over the countdown of the last one', () => {
    reduceMotion(true);
    const { map, layers, drawn } = fakeMap();
    const { result } = renderHook(() => useFeatureZoom(map));
    act(() => result.current(layer, feature));
    act(() => drawn());
    act(() => vi.advanceTimersByTime(600));
    act(() => result.current(layer, { ...feature, id: 8 }));
    act(() => drawn());
    act(() => vi.advanceTimersByTime(600));
    expect(lit(layers)).toBe(true);
    act(() => vi.advanceTimersByTime(400));
    expect(lit(layers)).toBe(false);
  });

  it('leaves a table row highlight on the same map alone when its own flash ends', () => {
    reduceMotion(true);
    const { map, layers, drawn } = fakeMap();
    const tableMap = { current: map };
    const { result } = renderHook(() => {
      const zoom = useFeatureZoom(map);
      const table = useMapFeatureHighlight({
        mapRef: tableMap,
        active: true,
        resetKey: 'parcels',
        getFitPadding: () => 0,
      });
      return { zoom, table };
    });
    act(() => result.current.zoom(layer, feature));
    act(() => drawn());
    act(() => {
      void result.current.table.highlightFeature(9, {
        geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
      });
    });
    expect(layers.has('attribute-table-highlight-line')).toBe(true);

    act(() => vi.advanceTimersByTime(1000));
    expect(lit(layers)).toBe(false);
    expect(layers.has('attribute-table-highlight-line')).toBe(true);
  });

  it('still fits the feature when the layer has no map source yet, without a flash', () => {
    drawn.source = false;
    const { map, layers, fitBounds } = fakeMap();
    const { result } = renderHook(() => useFeatureZoom(map));
    act(() => result.current(layer, feature));
    expect(fitBounds).toHaveBeenCalledWith(
      [[-74, 40], [-73.9, 40.1]],
      expect.objectContaining({ padding: 40 }),
    );
    expect(lit(layers)).toBe(false);
  });

  it('clears the earlier feature’s highlight when the next one has no map source yet', () => {
    const { map, layers } = fakeMap();
    const { result } = renderHook(() => useFeatureZoom(map));
    act(() => result.current(layer, feature));
    expect(lit(layers)).toBe(true);

    drawn.source = false;
    act(() => result.current(layer, { ...feature, id: 8 }));
    expect(lit(layers)).toBe(false);
  });
});
