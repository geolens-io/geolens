import { describe, it, expect, vi } from 'vitest';
import { circleAdapter } from '../circle-adapter';
import type { AdapterLayerInput } from '../types';

/**
 * Circle adapter regression pins (1134-01 MAP-18).
 *
 * - BUG-01 pin: addLayers honors visible=false at add-time (fill-adapter pattern).
 * - syncPaint calls syncLayerFilter (via shared helper — verified by asserting setFilter call).
 * - syncVisibility uses syncSingleLayerVisibility helper (setLayoutProperty path).
 * - getLayerIds returns [layerId].
 */

function createMockMap(opts: { layerExists?: boolean } = {}) {
  const { layerExists = true } = opts;
  return {
    addLayer: vi.fn(),
    getLayer: vi.fn().mockReturnValue(layerExists ? { id: 'mock-layer' } : undefined),
    setFilter: vi.fn(),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getLayoutProperty: vi.fn().mockReturnValue(undefined),
    getPaintProperty: vi.fn().mockReturnValue(undefined),
  };
}

function makeInput(overrides: Partial<AdapterLayerInput> = {}): AdapterLayerInput {
  return {
    id: 'layer-circle-1',
    dataset_table_name: 'ds_circle',
    dataset_geometry_type: 'POINT',
    opacity: 1,
    visible: true,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    style_config: null,
    sourceId: 'source-circle-1',
    layerId: 'layer-circle-1',
    sourceLayer: 'ds_circle',
    sourceType: 'vector',
    tileUrl: '/tiles/{z}/{x}/{y}',
    ...overrides,
  };
}

describe('circle adapter — addLayers honors visible=false at add-time (BUG-01 PASS pin)', () => {
  it('addLayer called with layout.visibility === "none" when visible=false', () => {
    const map = createMockMap({ layerExists: false });
    circleAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    expect(map.addLayer).toHaveBeenCalledTimes(1);
    const call = map.addLayer.mock.calls[0][0] as { layout?: { visibility?: string } };
    expect(call.layout?.visibility).toBe('none');
  });
});

describe('circle adapter — syncPaint calls syncLayerFilter', () => {
  it('setFilter is called on the canvas when a filter is provided via syncPaint', () => {
    const map = createMockMap({ layerExists: true });
    const filter = ['==', ['get', 'type'], 'A'] as unknown as import('maplibre-gl').FilterSpecification;
    circleAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput({ filter }));

    expect(map.setFilter).toHaveBeenCalledWith('layer-circle-1', filter);
  });
});

describe('circle adapter — syncVisibility uses syncSingleLayerVisibility helper', () => {
  it('setLayoutProperty called with visibility=none when visible=false', () => {
    const map = createMockMap({ layerExists: true });
    circleAdapter.syncVisibility(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-circle-1', 'visibility', 'none');
  });
});

describe('circle adapter — getLayerIds returns [layerId]', () => {
  it('returns array containing only the base layerId', () => {
    const ids = circleAdapter.getLayerIds('circle-xyz');
    expect(ids).toEqual(['circle-xyz']);
  });
});
