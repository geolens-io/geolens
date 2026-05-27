import { describe, it, expect, vi } from 'vitest';
import { lineAdapter } from '../line-adapter';
import type { AdapterLayerInput } from '../types';

/**
 * Line adapter regression pins (1134-01 MAP-18).
 *
 * - BUG-01 pin: addLayers honors visible=false at add-time (BUG-01 PASS comment at audit line 47).
 * - syncPaint calls syncLayerFilter (via setFilter spy).
 * - syncVisibility uses syncSingleLayerVisibility helper.
 * - getLayerIds shape: [layerId, arrowLayerId] — includes arrow id for ALL modes
 *   (arrow layer sync is guard-wrapped, so the id is always in the list even when
 *   the arrow layer does not exist on the map yet).
 */

function createMockMap(opts: { layerExists?: boolean; hasImage?: boolean } = {}) {
  const { layerExists = false, hasImage = false } = opts;
  return {
    addLayer: vi.fn(),
    getLayer: vi.fn().mockReturnValue(layerExists ? { id: 'mock-layer' } : undefined),
    removeLayer: vi.fn(),
    setFilter: vi.fn(),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getLayoutProperty: vi.fn().mockReturnValue(undefined),
    getPaintProperty: vi.fn().mockReturnValue(undefined),
    hasImage: vi.fn().mockReturnValue(hasImage),
    addImage: vi.fn(),
  };
}

function makeInput(overrides: Partial<AdapterLayerInput> = {}): AdapterLayerInput {
  return {
    id: 'layer-line-1',
    dataset_table_name: 'ds_line',
    dataset_geometry_type: 'LINESTRING',
    opacity: 1,
    visible: true,
    paint: { 'line-color': '#ff0000', 'line-width': 2 },
    layout: {},
    filter: null,
    label_config: null,
    style_config: null,
    sourceId: 'source-line-1',
    layerId: 'layer-line-1',
    sourceLayer: 'ds_line',
    sourceType: 'vector',
    tileUrl: '/tiles/{z}/{x}/{y}',
    ...overrides,
  };
}

describe('line adapter — addLayers honors visible=false at add-time (BUG-01 PASS pin)', () => {
  it('addLayer called with layout.visibility === "none" when visible=false', () => {
    const map = createMockMap({ layerExists: false });
    lineAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    expect(map.addLayer).toHaveBeenCalledTimes(1);
    const call = map.addLayer.mock.calls[0][0] as { id: string; layout?: Record<string, unknown> };
    expect(call.id).toBe('layer-line-1');
    expect(call.layout?.visibility).toBe('none');
  });
});

describe('line adapter — syncPaint calls syncLayerFilter', () => {
  it('setFilter is called on the canvas when a filter is provided via syncPaint', () => {
    const map = createMockMap({ layerExists: true });
    const filter = ['==', ['get', 'highway'], 'primary'] as unknown as import('maplibre-gl').FilterSpecification;
    lineAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput({ filter }));

    expect(map.setFilter).toHaveBeenCalledWith('layer-line-1', filter);
  });
});

describe('line adapter — syncVisibility uses syncSingleLayerVisibility helper', () => {
  it('setLayoutProperty called with visibility=none when visible=false', () => {
    const map = createMockMap({ layerExists: true });
    lineAdapter.syncVisibility(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-line-1', 'visibility', 'none');
  });
});

describe('line adapter — getLayerIds canonical shape (arrowLayerId guard PASS)', () => {
  it('returns [layerId, layerId-arrow] for all render modes', () => {
    // line-adapter.getLayerIds always returns both IDs — the arrow layer guard
    // in syncVisibility is safe when the arrow layer does not exist on the map.
    const ids = lineAdapter.getLayerIds('line-abc');
    expect(ids).toEqual(['line-abc', 'line-abc-arrow']);
  });
});
