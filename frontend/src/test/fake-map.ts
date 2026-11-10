import { vi } from 'vitest';
import type { Map as MaplibreMap } from 'maplibre-gl';

interface FakeMapOptions {
  /** Style layers the map already draws, by id, with the source each reads. */
  styleLayers?: Record<string, { source: string; sourceLayer?: string }>;
  /** The view as [west, south, east, north]. */
  bounds?: [number, number, number, number];
}

/**
 * A MapLibre map stand-in for table and panel tests: it records added layers
 * and fits, reports its view, and keeps event handlers so a test can fire them.
 */
export function makeFakeMap({ styleLayers = {}, bounds = [-76, 38, -73, 41] }: FakeMapOptions = {}) {
  const handlers = new Map<string, Set<() => void>>();
  const added = new Set<string>();
  const sources = new Set(Object.values(styleLayers).map((layer) => layer.source));
  const map = {
    getLayer: vi.fn((id: string) => (styleLayers[id] ? { id, ...styleLayers[id] } : added.has(id) ? { id } : undefined)),
    getSource: vi.fn((id: string) => (sources.has(id) ? {} : undefined)),
    addLayer: vi.fn((def: { id: string }) => { added.add(def.id); }),
    removeLayer: vi.fn((id: string) => { added.delete(id); }),
    addSource: vi.fn((id: string) => { sources.add(id); }),
    removeSource: vi.fn((id: string) => { sources.delete(id); }),
    fitBounds: vi.fn(),
    resize: vi.fn(),
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({ version: 8, sources: {}, layers: [] })),
    getContainer: vi.fn(() => document.createElement('div')),
    getBounds: vi.fn(() => ({
      getWest: () => bounds[0],
      getSouth: () => bounds[1],
      getEast: () => bounds[2],
      getNorth: () => bounds[3],
    })),
    on: vi.fn((event: string, handler: () => void) => {
      if (!handlers.has(event)) handlers.set(event, new Set());
      handlers.get(event)!.add(handler);
    }),
    off: vi.fn((event: string, handler: () => void) => { handlers.get(event)?.delete(handler); }),
    once: vi.fn(),
    fire: (event: string) => {
      for (const handler of [...(handlers.get(event) ?? [])]) handler();
    },
  };
  return map as unknown as MaplibreMap & typeof map;
}
