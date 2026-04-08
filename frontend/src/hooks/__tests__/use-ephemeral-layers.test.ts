import { act } from 'react';
import { renderHook } from '@/test/test-utils';
import { useEphemeralLayers } from '@/hooks/use-ephemeral-layers';

interface MockMap {
  layers: Set<string>;
  sources: Set<string>;
  styleLoaded: boolean;
  fitBoundsCalls: Array<{ bounds: unknown; options: unknown }>;
  getLayer: (id: string) => string | undefined;
  getSource: (id: string) => string | undefined;
  addLayer: (layer: { id: string }) => void;
  addSource: (id: string, _source: unknown) => void;
  removeLayer: (id: string) => void;
  removeSource: (id: string) => void;
  isStyleLoaded: () => boolean;
  once: (event: string, cb: () => void) => void;
  fitBounds: (bounds: unknown, options: unknown) => void;
}

function createMockMap(): MockMap {
  const layers = new Set<string>();
  const sources = new Set<string>();
  const fitBoundsCalls: MockMap['fitBoundsCalls'] = [];

  return {
    layers,
    sources,
    styleLoaded: true,
    fitBoundsCalls,
    getLayer: (id: string) => (layers.has(id) ? id : undefined),
    getSource: (id: string) => (sources.has(id) ? id : undefined),
    addLayer: (layer) => {
      layers.add(layer.id);
    },
    addSource: (id) => {
      sources.add(id);
    },
    removeLayer: (id) => {
      layers.delete(id);
    },
    removeSource: (id) => {
      sources.delete(id);
    },
    isStyleLoaded: () => true,
    once: (_event, cb) => cb(),
    fitBounds: (bounds, options) => {
      fitBoundsCalls.push({ bounds, options });
    },
  };
}

function sampleGeoJSON(): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [0, 0] },
        properties: {},
      },
    ],
  };
}

describe('useEphemeralLayers', () => {
  it('starts with no ephemeral result', () => {
    const map = createMockMap();
    const ref = { current: map as unknown as maplibregl.Map };
    const { result } = renderHook(() => useEphemeralLayers(ref));

    expect(result.current.ephemeralResult).toBeNull();
    expect(map.sources.size).toBe(0);
    expect(map.layers.size).toBe(0);
  });

  it('handleQueryResult adds source, layers, and fits bounds', () => {
    const map = createMockMap();
    const ref = { current: map as unknown as maplibregl.Map };
    const { result } = renderHook(() => useEphemeralLayers(ref));

    act(() => {
      result.current.handleQueryResult(sampleGeoJSON(), [-1, -1, 1, 1]);
    });

    expect(result.current.ephemeralResult).not.toBeNull();
    expect(map.sources.has('ephemeral-result')).toBe(true);
    // All 4 layer types should have been added
    expect(map.layers.has('ephemeral-result-fill')).toBe(true);
    expect(map.layers.has('ephemeral-result-outline')).toBe(true);
    expect(map.layers.has('ephemeral-result-line')).toBe(true);
    expect(map.layers.has('ephemeral-result-circle')).toBe(true);
    // Bounds should have been auto-zoomed
    expect(map.fitBoundsCalls).toHaveLength(1);
    expect(map.fitBoundsCalls[0].bounds).toEqual([[-1, -1], [1, 1]]);
  });

  it('handleDismissEphemeral removes all ephemeral layers and source', () => {
    const map = createMockMap();
    const ref = { current: map as unknown as maplibregl.Map };
    const { result } = renderHook(() => useEphemeralLayers(ref));

    act(() => {
      result.current.handleQueryResult(sampleGeoJSON(), [0, 0, 1, 1]);
    });
    expect(map.layers.size).toBeGreaterThan(0);

    act(() => {
      result.current.handleDismissEphemeral();
    });

    expect(result.current.ephemeralResult).toBeNull();
    expect(map.sources.has('ephemeral-result')).toBe(false);
    expect(map.layers.has('ephemeral-result-fill')).toBe(false);
    expect(map.layers.has('ephemeral-result-outline')).toBe(false);
    expect(map.layers.has('ephemeral-result-line')).toBe(false);
    expect(map.layers.has('ephemeral-result-circle')).toBe(false);
  });

  it('dismissing when map ref is null does not throw', () => {
    const ref = { current: null };
    const { result } = renderHook(() => useEphemeralLayers(ref));

    act(() => {
      result.current.handleQueryResult(sampleGeoJSON(), [0, 0, 1, 1]);
    });
    // Should not throw even though map is null
    expect(() => {
      act(() => {
        result.current.handleDismissEphemeral();
      });
    }).not.toThrow();
    expect(result.current.ephemeralResult).toBeNull();
  });

  it('replacing a query result tears down prior layers before adding new ones', () => {
    const map = createMockMap();
    const ref = { current: map as unknown as maplibregl.Map };
    const { result } = renderHook(() => useEphemeralLayers(ref));

    act(() => {
      result.current.handleQueryResult(sampleGeoJSON(), [0, 0, 1, 1]);
    });
    expect(map.layers.has('ephemeral-result-fill')).toBe(true);

    act(() => {
      result.current.handleQueryResult(sampleGeoJSON(), [2, 2, 3, 3]);
    });
    // Still present (re-added)
    expect(map.layers.has('ephemeral-result-fill')).toBe(true);
    // Second fitBounds call
    expect(map.fitBoundsCalls.length).toBeGreaterThanOrEqual(2);
  });
});
