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
  it('returns [layerId, layerId-arrow, layerId-label] for all render modes', () => {
    // line-adapter.getLayerIds always returns every id — the arrow and label
    // layer guards in syncVisibility are safe when a companion does not exist
    // on the map.
    const ids = lineAdapter.getLayerIds('line-abc');
    expect(ids).toEqual(['line-abc', 'line-abc-arrow', 'line-abc-label']);
  });
});

// Phase 1136-02: LINE_OWNED_LAYOUT_PROPERTIES export + syncPaint layout reconciliation
describe('line adapter — LINE_OWNED_LAYOUT_PROPERTIES export (Phase 1136-02 EDITOR-LINE-01)', () => {
  it('LINE_OWNED_LAYOUT_PROPERTIES is exported and equals [line-cap, line-join]', async () => {
    const { LINE_OWNED_LAYOUT_PROPERTIES } = await import('../line-adapter');
    expect(LINE_OWNED_LAYOUT_PROPERTIES).toEqual(['line-cap', 'line-join']);
  });
});

describe('line adapter — syncPaint reconciles line-cap and line-join via syncOwnedLayoutProperties', () => {
  it('calls setLayoutProperty for line-cap and line-join from input.layout', () => {
    const map = createMockMap({ layerExists: true });
    lineAdapter.syncPaint(
      map as unknown as import('maplibre-gl').Map,
      makeInput({ layout: { 'line-cap': 'square', 'line-join': 'bevel' } }),
    );

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-line-1', 'line-cap', 'square');
    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-line-1', 'line-join', 'bevel');
  });

  it('a stored square cap and bevel join, removed from the layout, return to round', () => {
    const map = createMockMap({ layerExists: true });
    map.getLayoutProperty.mockImplementation((_id: string, prop: string) =>
      prop === 'line-cap' ? 'square' : prop === 'line-join' ? 'bevel' : undefined,
    );

    lineAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput({ layout: {} }));

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-line-1', 'line-cap', 'round');
    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-line-1', 'line-join', 'round');
  });

  // line-cap and line-join are always 'round' or an explicit stored value, never
  // undefined: MapLibre resolves an undefined value to its own spec default
  // ('butt'/'miter'), not geolens's round default.
  it('resolves line-cap and line-join to round, never undefined, butt, or miter, when layout is empty', () => {
    const map = createMockMap({ layerExists: true });

    lineAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput({ layout: {} }));

    const values = map.setLayoutProperty.mock.calls
      .filter(([, prop]) => prop === 'line-cap' || prop === 'line-join')
      .map(([, , value]) => value);
    expect(values).toEqual(['round', 'round']);
  });

  it('makes no call when line-cap and line-join already hold round', () => {
    const map = createMockMap({ layerExists: true });
    // Post-addLayers state: the map already has both at 'round'.
    map.getLayoutProperty.mockImplementation((_id: string, prop: string) =>
      (prop === 'line-cap' || prop === 'line-join') ? 'round' : undefined,
    );

    lineAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput({ layout: {} }));

    const calls = map.setLayoutProperty.mock.calls.filter(([, prop]) => prop === 'line-cap' || prop === 'line-join');
    expect(calls).toHaveLength(0);
  });
});

// fix(#1625): the master slider rides on maplibre-gl v6's `line-layer-opacity`;
// the per-feature `line-opacity` is written unmultiplied.
describe('line adapter — master opacity drives line-layer-opacity (#1625)', () => {
  function paintWrites(map: ReturnType<typeof createMockMap>, prop: string) {
    return map.setPaintProperty.mock.calls
      .filter(([id, name]) => id === 'layer-line-1' && name === prop)
      .map(([, , value]) => value);
  }

  it('addLayers: numeric line-opacity 0.6 + master 0.5 -> line-opacity 0.6 and line-layer-opacity 0.5', () => {
    const map = createMockMap({ layerExists: true });
    lineAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput({
      opacity: 0.5,
      paint: { 'line-color': '#ff0000', 'line-width': 2, 'line-opacity': 0.6 },
    }));

    expect(paintWrites(map, 'line-opacity').at(-1)).toBe(0.6);
    expect(paintWrites(map, 'line-opacity')).not.toContain(0.3);
    expect(paintWrites(map, 'line-layer-opacity')).toEqual([0.5]);
  });

  it('syncPaint after addLayer: a new master value lands on line-layer-opacity and leaves line-opacity unmultiplied', () => {
    const map = createMockMap({ layerExists: true });
    lineAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput({
      opacity: 0.25,
      paint: { 'line-color': '#ff0000', 'line-width': 2, 'line-opacity': 0.6 },
    }));

    expect(paintWrites(map, 'line-layer-opacity')).toEqual([0.25]);
    expect(paintWrites(map, 'line-opacity').at(-1)).toBe(0.6);
  });
});
