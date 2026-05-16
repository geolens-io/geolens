import { describe, it, expect, vi } from 'vitest';
import { syncLayerFilter } from '../shared';
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
