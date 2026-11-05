import { act, renderHook } from '@testing-library/react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { SharedLayerResponse } from '@/types/api';
import { useMapFeatureHighlight } from '@/components/dataset/hooks/use-map-feature-highlight';
import { useFeatureZoom } from '../hooks/use-feature-zoom';

vi.mock('../map-data-table', () => ({ layerHighlightSource: () => ({ source: 'tiles' }) }));

const layer = { id: 'layer-1' } as SharedLayerResponse;
const feature = { id: 7, bbox: [-74, 40, -73.9, 40.1] as [number, number, number, number] };

/** A map that records its style layers and lets the test end a camera flight. */
function fakeMap() {
  const layers = new Set<string>();
  const sources = new Set(['tiles']);
  const moveend = new Set<() => void>();
  const map = {
    isStyleLoaded: () => true,
    getStyle: () => ({}),
    getLayer: (id: string) => (layers.has(id) ? {} : undefined),
    getSource: (id: string) => (sources.has(id) ? {} : undefined),
    addLayer: ({ id }: { id: string }) => layers.add(id),
    removeLayer: (id: string) => layers.delete(id),
    addSource: (id: string) => sources.add(id),
    removeSource: (id: string) => sources.delete(id),
    fitBounds: () => undefined,
    on: () => undefined,
    off: (event: string, listener: () => void) => {
      if (event === 'moveend') moveend.delete(listener);
    },
    once: (event: string, listener: () => void) => {
      if (event === 'moveend') moveend.add(listener);
    },
  } as unknown as MaplibreMap;
  return { map, layers, endFlight: () => [...moveend].forEach((listener) => listener()) };
}

function reduceMotion(reduce: boolean) {
  vi.stubGlobal('matchMedia', () => ({ matches: reduce }));
}

beforeEach(() => {
  vi.useFakeTimers();
  reduceMotion(false);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const lit = (layers: Set<string>) => layers.has('dashboard-feature-highlight-line');

describe('useFeatureZoom', () => {
  it('keeps the highlight until the map comes to rest, then clears it a second later', () => {
    const { map, layers, endFlight } = fakeMap();
    const { result } = renderHook(() => useFeatureZoom(map));
    act(() => result.current(layer, feature));
    expect(lit(layers)).toBe(true);

    act(() => vi.advanceTimersByTime(5000));
    expect(lit(layers)).toBe(true);

    act(() => endFlight());
    act(() => vi.advanceTimersByTime(999));
    expect(lit(layers)).toBe(true);
    act(() => vi.advanceTimersByTime(1));
    expect(lit(layers)).toBe(false);
  });

  it('starts the second at once when the camera jumps', () => {
    reduceMotion(true);
    const { map, layers } = fakeMap();
    const { result } = renderHook(() => useFeatureZoom(map));
    act(() => result.current(layer, feature));
    act(() => vi.advanceTimersByTime(1000));
    expect(lit(layers)).toBe(false);
  });

  it('lets a new selection take over the countdown of the last one', () => {
    reduceMotion(true);
    const { map, layers } = fakeMap();
    const { result } = renderHook(() => useFeatureZoom(map));
    act(() => result.current(layer, feature));
    act(() => vi.advanceTimersByTime(600));
    act(() => result.current(layer, { ...feature, id: 8 }));
    act(() => vi.advanceTimersByTime(600));
    expect(lit(layers)).toBe(true);
    act(() => vi.advanceTimersByTime(400));
    expect(lit(layers)).toBe(false);
  });

  it('leaves a table row highlight on the same map alone when its own flash ends', () => {
    reduceMotion(true);
    const { map, layers } = fakeMap();
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
});
