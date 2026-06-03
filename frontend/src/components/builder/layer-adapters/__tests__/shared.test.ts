import { describe, it, expect, vi } from 'vitest';
import { syncLayerFilter, setLayerProperty, syncOwnedLayoutProperties, syncOwnedPaintProperties } from '../shared';
import type { FilterSpecification } from 'maplibre-gl';

function createMockMap(layerExists = true) {
  const setFilterCalls: Array<[string, FilterSpecification | null | undefined]> = [];
  return {
    getLayer: vi.fn().mockReturnValue(layerExists ? { id: 'mock-layer' } : undefined),
    setFilter: vi.fn().mockImplementation((id: string, filter: FilterSpecification | null | undefined) => {
      setFilterCalls.push([id, filter]);
    }),
    _setFilterCalls: setFilterCalls,
  };
}

describe('syncLayerFilter', () => {
  it('Test 1: calls setFilter with the provided filter expression when non-empty', () => {
    const map = createMockMap();
    const filter: FilterSpecification = ['==', ['get', 'foo'], 1];
    syncLayerFilter(map as unknown as import('maplibre-gl').Map, 'L', filter);
    expect(map.setFilter).toHaveBeenCalledTimes(1);
    expect(map.setFilter).toHaveBeenCalledWith('L', filter);
  });

  it('Test 2: calls setFilter with null when filter is null', () => {
    const map = createMockMap();
    syncLayerFilter(map as unknown as import('maplibre-gl').Map, 'L', null);
    expect(map.setFilter).toHaveBeenCalledTimes(1);
    expect(map.setFilter).toHaveBeenCalledWith('L', null);
  });

  it('Test 3: calls setFilter with null when filter is undefined', () => {
    const map = createMockMap();
    syncLayerFilter(map as unknown as import('maplibre-gl').Map, 'L', undefined);
    expect(map.setFilter).toHaveBeenCalledTimes(1);
    expect(map.setFilter).toHaveBeenCalledWith('L', null);
  });

  it('Test 4: calls setFilter with null when filter is an empty array', () => {
    const map = createMockMap();
    syncLayerFilter(map as unknown as import('maplibre-gl').Map, 'L', []);
    expect(map.setFilter).toHaveBeenCalledTimes(1);
    expect(map.setFilter).toHaveBeenCalledWith('L', null);
  });

  it('Test 5: is a no-op when the layer does not exist (does not throw)', () => {
    const map = createMockMap(false);
    expect(() => {
      syncLayerFilter(map as unknown as import('maplibre-gl').Map, 'missing-layer', ['==', ['get', 'x'], 1]);
    }).not.toThrow();
    expect(map.setFilter).not.toHaveBeenCalled();
  });
});

// --- setLayerProperty ---

function createMockMapForSetLayerProperty() {
  return {
    setPaintProperty: vi.fn(),
    setLayoutProperty: vi.fn(),
  };
}

describe('setLayerProperty', () => {
  it('Test 1: calls setPaintProperty exactly once with the given args (default kind=paint)', () => {
    const map = createMockMapForSetLayerProperty();
    setLayerProperty(map as unknown as import('maplibre-gl').Map, 'L', 'fill-color', '#ff0000');
    expect(map.setPaintProperty).toHaveBeenCalledTimes(1);
    expect(map.setPaintProperty).toHaveBeenCalledWith('L', 'fill-color', '#ff0000');
    expect(map.setLayoutProperty).not.toHaveBeenCalled();
  });

  it('Test 2: calls setLayoutProperty when kind is layout', () => {
    const map = createMockMapForSetLayerProperty();
    setLayerProperty(map as unknown as import('maplibre-gl').Map, 'L', 'visibility', 'visible', 'layout');
    expect(map.setLayoutProperty).toHaveBeenCalledTimes(1);
    expect(map.setLayoutProperty).toHaveBeenCalledWith('L', 'visibility', 'visible');
    expect(map.setPaintProperty).not.toHaveBeenCalled();
  });

  it('Test 3: catches and does NOT re-throw when setPaintProperty throws', () => {
    const map = createMockMapForSetLayerProperty();
    map.setPaintProperty.mockImplementation(() => { throw new Error('boom'); });
    expect(() => {
      setLayerProperty(map as unknown as import('maplibre-gl').Map, 'L', 'fill-opacity', 0.5);
    }).not.toThrow();
  });

  it('Test 4: default kind is paint — omitting the 5th arg routes to setPaintProperty', () => {
    const map = createMockMapForSetLayerProperty();
    setLayerProperty(map as unknown as import('maplibre-gl').Map, 'L', 'line-width', 2);
    expect(map.setPaintProperty).toHaveBeenCalledWith('L', 'line-width', 2);
    expect(map.setLayoutProperty).not.toHaveBeenCalled();
  });
});

function createMockMapForReconciler() {
  const paintState = new Map<string, unknown>();
  const layoutState = new Map<string, unknown>();
  return {
    getLayer: vi.fn().mockReturnValue({ id: 'L' }),
    getPaintProperty: vi.fn((_layerId: string, prop: string) => paintState.get(prop)),
    setPaintProperty: vi.fn((_layerId: string, prop: string, value: unknown) => {
      paintState.set(prop, value);
    }),
    getLayoutProperty: vi.fn((_layerId: string, prop: string) => layoutState.get(prop)),
    setLayoutProperty: vi.fn((_layerId: string, prop: string, value: unknown) => {
      layoutState.set(prop, value);
    }),
    paintState,
    layoutState,
  };
}

describe('syncOwnedPaintProperties', () => {
  it('sets changed owned paint properties', () => {
    const map = createMockMapForReconciler();
    map.paintState.set('line-color', '#111111');

    syncOwnedPaintProperties(
      map as unknown as import('maplibre-gl').Map,
      'L',
      { 'line-color': '#ff0000' },
      { geomType: 'line', ownedProperties: ['line-color'] },
    );

    expect(map.setPaintProperty).toHaveBeenCalledWith('L', 'line-color', '#ff0000');
  });

  it('does not rewrite unchanged owned paint properties', () => {
    const map = createMockMapForReconciler();
    map.paintState.set('circle-radius', 8);

    syncOwnedPaintProperties(
      map as unknown as import('maplibre-gl').Map,
      'L',
      { 'circle-radius': 8 },
      { geomType: 'circle', ownedProperties: ['circle-radius'] },
    );

    expect(map.setPaintProperty).not.toHaveBeenCalled();
  });

  it('clears missing owned paint properties', () => {
    const map = createMockMapForReconciler();
    map.paintState.set('line-gradient', ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0']);

    syncOwnedPaintProperties(
      map as unknown as import('maplibre-gl').Map,
      'L',
      { 'line-color': '#f97316' },
      { geomType: 'line', ownedProperties: ['line-color', 'line-gradient'] },
    );

    expect(map.setPaintProperty).toHaveBeenCalledWith('L', 'line-gradient', undefined);
  });

  it('filters custom metadata and cross-geometry paint properties', () => {
    const map = createMockMapForReconciler();

    syncOwnedPaintProperties(
      map as unknown as import('maplibre-gl').Map,
      'L',
      {
        'line-color': '#ff0000',
        'circle-radius': 8,
        '_outline-width': 4,
      },
      { geomType: 'line', ownedProperties: ['line-color', 'circle-radius', '_outline-width'] },
    );

    expect(map.setPaintProperty).toHaveBeenCalledTimes(1);
    expect(map.setPaintProperty).toHaveBeenCalledWith('L', 'line-color', '#ff0000');
  });

  it('preserves expression value identity when setting paint', () => {
    const map = createMockMapForReconciler();
    const expression = ['interpolate', ['linear'], ['zoom'], 5, 1, 12, 8];

    syncOwnedPaintProperties(
      map as unknown as import('maplibre-gl').Map,
      'L',
      { 'line-width': expression },
      { geomType: 'line', ownedProperties: ['line-width'] },
    );

    expect(map.setPaintProperty).toHaveBeenCalledWith('L', 'line-width', expression);
    expect(map.setPaintProperty.mock.calls[0][2]).toBe(expression);
  });

  it('isolates MapLibre paint errors per property', () => {
    const map = createMockMapForReconciler();
    map.setPaintProperty.mockImplementation((_layerId: string, prop: string, value: unknown) => {
      if (prop === 'line-color') throw new Error('bad color');
      map.paintState.set(prop, value);
    });

    expect(() => syncOwnedPaintProperties(
      map as unknown as import('maplibre-gl').Map,
      'L',
      { 'line-color': '#ff0000', 'line-width': 4 },
      { geomType: 'line', ownedProperties: ['line-color', 'line-width'] },
    )).not.toThrow();

    expect(map.setPaintProperty).toHaveBeenCalledWith('L', 'line-width', 4);
  });

  it('is a no-op when the target layer is missing', () => {
    const map = createMockMapForReconciler();
    map.getLayer.mockReturnValue(undefined);

    syncOwnedPaintProperties(
      map as unknown as import('maplibre-gl').Map,
      'missing',
      { 'line-color': '#ff0000' },
      { geomType: 'line', ownedProperties: ['line-color'] },
    );

    expect(map.setPaintProperty).not.toHaveBeenCalled();
  });
});

describe('syncOwnedLayoutProperties', () => {
  it('sets changed owned layout properties', () => {
    const map = createMockMapForReconciler();

    syncOwnedLayoutProperties(
      map as unknown as import('maplibre-gl').Map,
      'L',
      { 'line-cap': 'square' },
      { ownedProperties: ['line-cap'] },
    );

    expect(map.setLayoutProperty).toHaveBeenCalledWith('L', 'line-cap', 'square');
  });

  it('clears missing owned layout properties', () => {
    const map = createMockMapForReconciler();
    map.layoutState.set('line-cap', 'round');

    syncOwnedLayoutProperties(
      map as unknown as import('maplibre-gl').Map,
      'L',
      {},
      { ownedProperties: ['line-cap'] },
    );

    expect(map.setLayoutProperty).toHaveBeenCalledWith('L', 'line-cap', undefined);
  });

  it('filters builder-only layout metadata', () => {
    const map = createMockMapForReconciler();

    syncOwnedLayoutProperties(
      map as unknown as import('maplibre-gl').Map,
      'L',
      { '_minzoom': 5, visibility: 'none' },
      { ownedProperties: ['_minzoom', 'visibility'] },
    );

    expect(map.setLayoutProperty).toHaveBeenCalledTimes(1);
    expect(map.setLayoutProperty).toHaveBeenCalledWith('L', 'visibility', 'none');
  });
});
