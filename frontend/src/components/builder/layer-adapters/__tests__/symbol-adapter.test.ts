import { describe, it, expect, vi } from 'vitest';
import { symbolAdapter } from '../symbol-adapter';
import type { AdapterLayerInput } from '../types';

/**
 * Symbol adapter regression tests.
 *
 * Task 2 (1134-01): Migrate raw `map.setFilter` calls in syncPaint to the
 * shared `syncLayerFilter` helper, matching the v1026 owned-property contract
 * used by fill/line/circle/heatmap adapters.
 *
 * BUG-01 pin: addLayers must honor `visible: false` at add-time by passing
 * `layout.visibility === 'none'` in the symbolLayout() call (already present
 * via `visibility: input.visible ? 'visible' : 'none'` in symbolLayout).
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
    // sprite helpers
    getSprite: vi.fn().mockReturnValue([{ id: 'geolens' }]),
    addSprite: vi.fn(),
  };
}

function makeInput(overrides: Partial<AdapterLayerInput> = {}): AdapterLayerInput {
  return {
    id: 'layer-sym-1',
    dataset_table_name: 'ds_sym',
    dataset_geometry_type: 'POINT',
    opacity: 1,
    visible: true,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    style_config: { render_mode: 'symbol' },
    sourceId: 'source-sym-1',
    layerId: 'layer-sym-1',
    sourceLayer: 'ds_sym',
    sourceType: 'vector',
    tileUrl: '/tiles/{z}/{x}/{y}',
    ...overrides,
  };
}

describe('symbol-adapter — BUG-01 initial visibility', () => {
  it('Test 1: addLayers with visible=true — layout.visibility is "visible"', () => {
    const map = createMockMap({ layerExists: false });
    symbolAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput({ visible: true }));

    expect(map.addLayer).toHaveBeenCalledTimes(1);
    const call = map.addLayer.mock.calls[0][0] as { layout: Record<string, unknown> };
    expect(call.layout.visibility).toBe('visible');
  });

  it('Test 2: addLayers with visible=false — layout.visibility is "none" (BUG-01 PASS pin)', () => {
    const map = createMockMap({ layerExists: false });
    symbolAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    expect(map.addLayer).toHaveBeenCalledTimes(1);
    const call = map.addLayer.mock.calls[0][0] as { layout: Record<string, unknown> };
    expect(call.layout.visibility).toBe('none');
  });
});

describe('symbol-adapter — syncLayerFilter migration', () => {
  it('Test 3: syncPaint with a filter — setFilter called with the filter (via syncLayerFilter)', () => {
    const map = createMockMap({ layerExists: true });
    const filter = ['==', ['get', 'class'], 'highway'] as unknown as import('maplibre-gl').FilterSpecification;
    symbolAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput({ filter }));

    expect(map.setFilter).toHaveBeenCalledWith('layer-sym-1', filter);
  });

  it('Test 4: syncPaint with filter=null — setFilter called with null (syncLayerFilter passes null through)', () => {
    const map = createMockMap({ layerExists: true });
    symbolAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput({ filter: null }));

    expect(map.setFilter).toHaveBeenCalledWith('layer-sym-1', null);
  });
});

describe('symbol-adapter — syncVisibility', () => {
  it('Test 5: syncVisibility(visible=false) — setLayoutProperty called with "none"', () => {
    const map = createMockMap({ layerExists: true });
    symbolAdapter.syncVisibility(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-sym-1', 'visibility', 'none');
  });
});

describe('symbol-adapter — getLayerIds', () => {
  it('Test 6: getLayerIds returns [layerId]', () => {
    const ids = symbolAdapter.getLayerIds('sym-abc');
    expect(ids).toEqual(['sym-abc']);
  });
});
