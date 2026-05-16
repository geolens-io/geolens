import { describe, it, expect, vi } from 'vitest';
import { syncLayerFilter, setLayerProperty } from '../shared';
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
