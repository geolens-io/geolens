import { describe, expect, it, vi } from 'vitest';
import { act, render } from '@/test/test-utils';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { MeasurementPlugin } from '../MeasurementPlugin';

type Handler = (e: unknown) => void;
type Collection = { features: GeoJSON.Feature[] };

/** A map stub whose style swap drops every source and layer, as a non-diffing setStyle does. */
function fakeMap() {
  const sources = new Map<string, { data: Collection; setData: (d: Collection) => void }>();
  const layers = new Set<string>();
  const handlers = new Map<string, Set<Handler>>();
  const canvas = document.createElement('canvas');
  const fire = (event: string, e: unknown = {}) => {
    for (const fn of handlers.get(event) ?? []) fn(e);
  };
  const map = {
    getSource: (id: string) => sources.get(id),
    addSource: (id: string, spec: { data: Collection }) => {
      const source = {
        data: spec.data,
        setData(d: Collection) {
          source.data = d;
        },
      };
      sources.set(id, source);
    },
    removeSource: (id: string) => sources.delete(id),
    getLayer: (id: string) => (layers.has(id) ? { id } : undefined),
    addLayer: (layer: { id: string }) => layers.add(layer.id),
    removeLayer: (id: string) => layers.delete(id),
    on: (event: string, fn: Handler) => {
      if (!handlers.has(event)) handlers.set(event, new Set());
      handlers.get(event)!.add(fn);
    },
    off: (event: string, fn: Handler) => handlers.get(event)?.delete(fn),
    doubleClickZoom: { isEnabled: () => true, enable: vi.fn(), disable: vi.fn() },
    getCanvas: () => canvas,
  };
  const swapStyle = () => {
    sources.clear();
    layers.clear();
    fire('style.load');
  };
  return { map, sources, layers, fire, swapStyle };
}

describe('MeasurementPlugin', () => {
  it('redraws the measurement after a basemap switch replaces the style', () => {
    const { map, sources, layers, fire, swapStyle } = fakeMap();
    render(
      <MeasurementPlugin ctx={{ mapInstance: map as unknown as MaplibreMap, layers: [], mapId: 'm' }} />,
    );
    act(() => fire('click', { lngLat: { lng: 0, lat: 0 } }));
    act(() => fire('click', { lngLat: { lng: 0, lat: 1 } }));

    act(() => swapStyle());

    expect(layers.size).toBe(2);
    const [source] = [...sources.values()];
    expect(source?.data.features.map((f) => f.geometry.type)).toEqual(['Point', 'Point', 'LineString']);

    act(() => fire('click', { lngLat: { lng: 1, lat: 1 } }));
    expect(source?.data.features.filter((f) => f.geometry.type === 'Point')).toHaveLength(3);
  });
});
