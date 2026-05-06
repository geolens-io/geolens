import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  getAdapter,
  resolveAdapterType,
  circleAdapter,
  symbolAdapter,
  lineAdapter,
  fillAdapter,
  rasterAdapter,
  hillshadeAdapter,
  heatmapAdapter,
} from '@/components/builder/layer-adapters';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';

vi.mock('@/lib/tile-utils', () => ({
  buildSignedTileUrl: vi.fn(() => '/tiles/mock/{z}/{x}/{y}.pbf'),
}));

// Mock window.location.origin for raster tile URL construction
Object.defineProperty(window, 'location', {
  value: { origin: 'http://localhost:8080' },
  writable: true,
});

function createMockMap() {
  return {
    getSource: vi.fn(() => null),
    addSource: vi.fn(),
    addLayer: vi.fn(),
    getLayer: vi.fn(() => null),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getPaintProperty: vi.fn(),
    getLayoutProperty: vi.fn(),
    getFilter: vi.fn().mockReturnValue(null),
    setFilter: vi.fn(),
    removeLayer: vi.fn(),
    removeSource: vi.fn(),
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({ layers: [] })),
    getSprite: vi.fn(() => []),
    addSprite: vi.fn(),
    moveLayer: vi.fn(),
    setLayerZoomRange: vi.fn(),
  } as unknown as import('maplibre-gl').Map;
}

function makeInput(overrides: Partial<AdapterLayerInput> = {}): AdapterLayerInput {
  return {
    id: 'layer-1',
    dataset_table_name: 'test_table',
    dataset_geometry_type: 'Polygon',
    opacity: 1,
    visible: true,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    sourceId: 'source-layer-1',
    layerId: 'layer-layer-1',
    sourceLayer: 'data.test_table',
    tileUrl: '/tiles/{z}/{x}/{y}.pbf',
    tileSize: 256,
    minzoom: 0,
    maxzoom: 18,
    ...overrides,
  };
}

// ──────────────────────────────────────────────────────────────────────────────
describe('getAdapter', () => {
  it('returns circleAdapter for "circle"', () => {
    expect(getAdapter('circle')).toBe(circleAdapter);
  });

  it('returns lineAdapter for "line"', () => {
    expect(getAdapter('line')).toBe(lineAdapter);
  });

  it('returns fillAdapter for "fill"', () => {
    expect(getAdapter('fill')).toBe(fillAdapter);
  });

  it('returns rasterAdapter for "raster"', () => {
    expect(getAdapter('raster')).toBe(rasterAdapter);
  });

  it('returns hillshadeAdapter for "hillshade"', () => {
    expect(getAdapter('hillshade')).toBe(hillshadeAdapter);
  });

  it('returns heatmapAdapter for "heatmap"', () => {
    expect(getAdapter('heatmap')).toBe(heatmapAdapter);
  });

  it('returns symbolAdapter for "symbol"', () => {
    expect(getAdapter('symbol')).toBe(symbolAdapter);
  });

  it('falls back to circleAdapter for unknown type', () => {
    expect(getAdapter('unknown')).toBe(circleAdapter);
  });
});

// ──────────────────────────────────────────────────────────────────────────────
describe('resolveAdapterType', () => {
  it('returns heatmap when render_mode is heatmap (overrides geometry)', () => {
    expect(resolveAdapterType('POINT', { render_mode: 'heatmap' })).toBe('heatmap');
  });

  it('returns heatmap when render_mode is heatmap and geometry is null', () => {
    expect(resolveAdapterType(null, { render_mode: 'heatmap' })).toBe('heatmap');
  });

  it('returns symbol when render_mode is symbol', () => {
    expect(resolveAdapterType('POINT', { render_mode: 'symbol' })).toBe('symbol');
  });

  it('returns circle for POINT geometry without render_mode', () => {
    expect(resolveAdapterType('POINT', null)).toBe('circle');
  });

  it('returns line for LINESTRING geometry', () => {
    expect(resolveAdapterType('LINESTRING', null)).toBe('line');
  });

  it('returns fill for POLYGON geometry', () => {
    expect(resolveAdapterType('POLYGON', null)).toBe('fill');
  });

  it('infers heatmap from paint keys when geometry is null', () => {
    expect(resolveAdapterType(null, null, { 'heatmap-radius': 30, 'heatmap-color': 'red' })).toBe('heatmap');
  });

  it('infers circle from paint keys when geometry is null', () => {
    expect(resolveAdapterType(null, null, { 'circle-color': '#f00', 'circle-radius': 5 })).toBe('circle');
  });

  it('infers line from paint keys when geometry is null', () => {
    expect(resolveAdapterType(null, null, { 'line-color': '#00f', 'line-width': 2 })).toBe('line');
  });

  it('infers fill from paint keys when geometry is null', () => {
    expect(resolveAdapterType(null, null, { 'fill-color': '#0f0' })).toBe('fill');
  });

  it('falls back to fill when geometry is null and paint is empty', () => {
    expect(resolveAdapterType(null, null, {})).toBe('fill');
  });

  it('falls back to fill when geometry is null and paint is undefined', () => {
    expect(resolveAdapterType(null, null, undefined)).toBe('fill');
  });

  it('geometry type takes priority over paint inference', () => {
    expect(resolveAdapterType('MULTIPOLYGON', null, { 'circle-color': '#f00' })).toBe('fill');
  });
});

// ──────────────────────────────────────────────────────────────────────────────
describe('symbolAdapter', () => {
  let map: ReturnType<typeof createMockMap>;

  beforeEach(() => {
    map = createMockMap();
  });

  it('addLayers creates a symbol layer with icon and text layout', () => {
    const input = makeInput({
      id: 's1',
      layerId: 'layer-s1',
      sourceId: 'source-s1',
      sourceLayer: 'data.test_table',
      dataset_geometry_type: 'POINT',
      style_config: {
        render_mode: 'symbol',
        symbol: {
          iconImage: 'bus',
          iconSize: 1.25,
          iconRotation: 15,
          iconAnchor: 'bottom',
          iconOffset: [0, -1],
        },
      },
      label_config: { column: 'name' },
    });

    symbolAdapter.addLayers(map, input);

    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call).toEqual(expect.objectContaining({
      id: 'layer-s1',
      type: 'symbol',
      source: 'source-s1',
      'source-layer': 'data.test_table',
    }));
    expect(call.layout).toEqual(expect.objectContaining({
      'icon-image': 'geolens:bus',
      'icon-size': 1.25,
      'icon-rotate': 15,
      'icon-anchor': 'bottom',
      'icon-offset': [0, -1],
      'text-field': ['get', 'name'],
    }));
    expect(map.addSprite).toHaveBeenCalledWith('geolens', '/maps/sprites/geolens');
  });

  it('does not re-add the GeoLens sprite when already registered', () => {
    (map.getSprite as ReturnType<typeof vi.fn>).mockReturnValue([{ id: 'geolens', url: '/maps/sprites/geolens' }]);
    const input = makeInput({
      id: 's1b',
      layerId: 'layer-s1b',
      style_config: { render_mode: 'symbol', symbol: { iconImage: 'bus' } },
    });

    symbolAdapter.addLayers(map, input);

    expect(map.addSprite).not.toHaveBeenCalled();
  });

  it('uses a match expression for category-based icon mapping', () => {
    const input = makeInput({
      id: 's2',
      layerId: 'layer-s2',
      style_config: {
        render_mode: 'symbol',
        symbol: {
          iconImage: 'marker',
          categoryColumn: 'kind',
          categories: [
            { value: 'bus', icon: 'bus' },
            { value: 'rail', icon: 'train' },
          ],
        },
      },
    });

    symbolAdapter.addLayers(map, input);

    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.layout['icon-image']).toEqual([
      'match',
      ['get', 'kind'],
      'bus',
      'geolens:bus',
      'rail',
      'geolens:train',
      'geolens:marker',
    ]);
  });

  it('syncPaint updates symbol layout and paint on an existing layer', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-s3' });
    const input = makeInput({
      id: 's3',
      layerId: 'layer-s3',
      opacity: 0.4,
      style_config: { render_mode: 'symbol', symbol: { iconImage: 'park' } },
    });

    symbolAdapter.syncPaint(map, input);

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-s3', 'icon-image', 'geolens:park');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-s3', 'icon-opacity', 0.4);
  });
});

// ──────────────────────────────────────────────────────────────────────────────
describe('circleAdapter', () => {
  let map: ReturnType<typeof createMockMap>;

  beforeEach(() => {
    map = createMockMap();
  });

  it('addLayers calls addLayer with type circle and correct source-layer', () => {
    const input = makeInput({
      id: 'c1',
      layerId: 'layer-c1',
      sourceId: 'source-c1',
      sourceLayer: 'data.test_table',
      dataset_geometry_type: 'POINT',
    });
    circleAdapter.addLayers(map, input);
    expect(map.addLayer).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'layer-c1',
        type: 'circle',
        'source-layer': 'data.test_table',
      }),
    );
  });

  it('addLayers uses default paint when input.paint is empty', () => {
    const input = makeInput({ id: 'c2', layerId: 'layer-c2', paint: {} });
    circleAdapter.addLayers(map, input);
    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.paint).toHaveProperty('circle-radius', 5);
    expect(call.paint).toHaveProperty('circle-color');
    expect(call.paint).toHaveProperty('circle-stroke-color');
    expect(call.paint).toHaveProperty('circle-stroke-width');
  });

  it('addLayers calls simplifyPaint when paint has expressions', () => {
    const input = makeInput({
      id: 'c3',
      layerId: 'layer-c3',
      paint: {
        'circle-color': ['step', ['get', 'val'], '#ff0000', 100, '#0000ff'],
        'circle-radius': 5,
      },
    });
    circleAdapter.addLayers(map, input);
    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    // After simplifyPaint, step expression at index 2 is used as fallback
    expect(call.paint['circle-color']).toBe('#ff0000');
    // Expressions are then replayed via setPaintProperty
    expect(map.setPaintProperty).toHaveBeenCalledWith(
      'layer-c3',
      'circle-color',
      ['step', ['get', 'val'], '#ff0000', 100, '#0000ff'],
    );
  });

  it('addLayers replays circle radius and opacity expressions without flattening opacity', () => {
    const radiusExpression = ['interpolate', ['linear'], ['zoom'], 4, 3, 12, 10];
    const opacityExpression = ['step', ['zoom'], 0.25, 10, 0.8];
    const input = makeInput({
      id: 'c3b',
      layerId: 'layer-c3b',
      paint: {
        'circle-color': '#ff0000',
        'circle-radius': radiusExpression,
        'circle-opacity': opacityExpression,
      },
      opacity: 0.4,
    });

    circleAdapter.addLayers(map, input);

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-c3b', 'circle-radius', radiusExpression);
    const opacityCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls
      .filter(([, prop]) => prop === 'circle-opacity');
    expect(opacityCalls.length).toBeGreaterThan(0);
    expect(opacityCalls.every(([, , value]) => JSON.stringify(value) === JSON.stringify(opacityExpression))).toBe(true);
  });

  it('getLayerIds returns [layerId] (single layer)', () => {
    expect(circleAdapter.getLayerIds('layer-c1')).toEqual(['layer-c1']);
  });

  it('syncPaint updates paint properties on existing layer', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-c4' });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);
    const input = makeInput({
      id: 'c4',
      layerId: 'layer-c4',
      paint: { 'circle-radius': 8 },
    });
    circleAdapter.syncPaint(map, input);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-c4', 'circle-radius', 8);
  });

  it('syncPaint preserves circle radius and opacity expressions', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-c5' });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);
    const radiusExpression = ['interpolate', ['linear'], ['zoom'], 4, 3, 12, 10];
    const opacityExpression = ['step', ['zoom'], 0.25, 10, 0.8];
    const input = makeInput({
      id: 'c5',
      layerId: 'layer-c5',
      paint: {
        'circle-radius': radiusExpression,
        'circle-opacity': opacityExpression,
      },
      opacity: 0.4,
    });

    circleAdapter.syncPaint(map, input);

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-c5', 'circle-radius', radiusExpression);
    const opacityCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls
      .filter(([, prop]) => prop === 'circle-opacity');
    expect(opacityCalls.length).toBeGreaterThan(0);
    expect(opacityCalls.every(([, , value]) => JSON.stringify(value) === JSON.stringify(opacityExpression))).toBe(true);
  });

  it('syncVisibility sets visibility layout property', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-c6' });
    const inputVisible = makeInput({ id: 'c6', layerId: 'layer-c6', visible: false });
    circleAdapter.syncVisibility(map, inputVisible);
    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-c6', 'visibility', 'none');
  });
});

// ──────────────────────────────────────────────────────────────────────────────
describe('lineAdapter', () => {
  let map: ReturnType<typeof createMockMap>;

  beforeEach(() => {
    map = createMockMap();
  });

  it('addLayers extracts line-dasharray from layout into paint', () => {
    const input = makeInput({
      id: 'l1',
      layerId: 'layer-l1',
      sourceId: 'source-l1',
      sourceLayer: 'data.test_table',
      dataset_geometry_type: 'LINESTRING',
      paint: {},
      layout: { 'line-dasharray': [2, 4] },
    });
    lineAdapter.addLayers(map, input);
    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    // line-dasharray should be in paint, not layout
    expect(call.paint['line-dasharray']).toEqual([2, 4]);
    expect(call.layout).not.toHaveProperty('line-dasharray');
  });

  it('addLayers sets line-cap:round and line-join:round in layout', () => {
    const input = makeInput({ id: 'l2', layerId: 'layer-l2', dataset_geometry_type: 'LINESTRING' });
    lineAdapter.addLayers(map, input);
    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.layout['line-cap']).toBe('round');
    expect(call.layout['line-join']).toBe('round');
  });

  it('addLayers uses default paint (line-color, line-width) when paint is empty', () => {
    const input = makeInput({ id: 'l3', layerId: 'layer-l3', paint: {} });
    lineAdapter.addLayers(map, input);
    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.paint).toHaveProperty('line-color');
    expect(call.paint).toHaveProperty('line-width', 2);
  });

  it('getLayerIds returns [layerId] (single layer)', () => {
    expect(lineAdapter.getLayerIds('layer-l1')).toEqual(['layer-l1']);
  });

  it('addLayers creates line layer type', () => {
    const input = makeInput({ id: 'l4', layerId: 'layer-l4', dataset_geometry_type: 'LINESTRING' });
    lineAdapter.addLayers(map, input);
    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.type).toBe('line');
  });

  it('addLayers passes line gap, blur, offset, and replays line-gradient expressions', () => {
    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    const input = makeInput({
      id: 'l5',
      layerId: 'layer-l5',
      sourceId: 'source-l5',
      sourceLayer: 'data.test_table',
      dataset_geometry_type: 'LINESTRING',
      paint: {
        'line-color': '#ff0000',
        'line-width': 3,
        'line-gap-width': 4,
        'line-blur': 1.5,
        'line-offset': -2,
        'line-gradient': gradient,
      },
    });

    lineAdapter.addLayers(map, input);

    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.paint).toEqual(expect.objectContaining({
      'line-gap-width': 4,
      'line-blur': 1.5,
      'line-offset': -2,
    }));
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l5', 'line-gradient', gradient);
  });

  it('addLayers replays line width and opacity expressions without flattening saved gradients', () => {
    const widthExpression = ['interpolate', ['linear'], ['zoom'], 5, 1, 12, 8];
    const opacityExpression = ['step', ['zoom'], 0.2, 9, 0.7];
    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    const input = makeInput({
      id: 'l5b',
      layerId: 'layer-l5b',
      sourceId: 'source-l5b',
      sourceLayer: 'data.test_table',
      dataset_geometry_type: 'LINESTRING',
      paint: {
        'line-color': '#ff0000',
        'line-width': widthExpression,
        'line-opacity': opacityExpression,
        'line-gradient': gradient,
      },
      opacity: 0.4,
    });

    lineAdapter.addLayers(map, input);

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l5b', 'line-width', widthExpression);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l5b', 'line-gradient', gradient);
    const opacityCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls
      .filter(([, prop]) => prop === 'line-opacity');
    expect(opacityCalls.length).toBeGreaterThan(0);
    expect(opacityCalls.every(([, , value]) => JSON.stringify(value) === JSON.stringify(opacityExpression))).toBe(true);
  });

  it('syncPaint preserves line gap, blur, offset, and line-gradient paint', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-l6' });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);
    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    const input = makeInput({
      id: 'l6',
      layerId: 'layer-l6',
      dataset_geometry_type: 'LINESTRING',
      paint: {
        'line-gap-width': 5,
        'line-blur': 2,
        'line-offset': 3,
        'line-gradient': gradient,
      },
    });

    lineAdapter.syncPaint(map, input);

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l6', 'line-gap-width', 5);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l6', 'line-blur', 2);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l6', 'line-offset', 3);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l6', 'line-gradient', gradient);
  });

  it('syncPaint preserves line width, line opacity, and saved gradient expressions', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-l7' });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);
    const widthExpression = ['interpolate', ['linear'], ['zoom'], 5, 1, 12, 8];
    const opacityExpression = ['step', ['zoom'], 0.2, 9, 0.7];
    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    const input = makeInput({
      id: 'l7',
      layerId: 'layer-l7',
      dataset_geometry_type: 'LINESTRING',
      paint: {
        'line-width': widthExpression,
        'line-opacity': opacityExpression,
        'line-gradient': gradient,
      },
      opacity: 0.4,
    });

    lineAdapter.syncPaint(map, input);

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l7', 'line-width', widthExpression);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l7', 'line-gradient', gradient);
    const opacityCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls
      .filter(([, prop]) => prop === 'line-opacity');
    expect(opacityCalls.length).toBeGreaterThan(0);
    expect(opacityCalls.every(([, , value]) => JSON.stringify(value) === JSON.stringify(opacityExpression))).toBe(true);
  });
});

// ──────────────────────────────────────────────────────────────────────────────
describe('fillAdapter', () => {
  let map: ReturnType<typeof createMockMap>;

  beforeEach(() => {
    map = createMockMap();
  });

  it('addLayers creates both fill layer and outline companion layer (2 addLayer calls, no _height_column)', () => {
    const input = makeInput({ id: 'f1', layerId: 'layer-f1', sourceId: 'source-f1', sourceLayer: 'data.test_table' });
    fillAdapter.addLayers(map, input);
    expect(map.addLayer).toHaveBeenCalledTimes(2);
    const calls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls[0][0].type).toBe('fill');
    expect(calls[1][0].type).toBe('line');
  });

  it('addLayers reads outline color and width from style_config.builder', () => {
    const input = makeInput({
      id: 'f2',
      layerId: 'layer-f2',
      sourceId: 'source-f2',
      sourceLayer: 'data.test_table',
      paint: {
        'fill-color': '#ff0000',
      },
      style_config: { builder: { outlineColor: '#00ff00', outlineWidth: 3 } },
    } as Partial<AdapterLayerInput> & { style_config: { builder: { outlineColor: string; outlineWidth: number } } });
    fillAdapter.addLayers(map, input);
    const calls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    const outlinePaint = calls[1][0].paint;
    expect(outlinePaint['line-color']).toBe('#00ff00');
    expect(outlinePaint['line-width']).toBe(3);
  });

  it('addLayers sets fill-outline-color:transparent when style_config.builder stroke is disabled', () => {
    const input = makeInput({
      id: 'f3',
      layerId: 'layer-f3',
      sourceId: 'source-f3',
      sourceLayer: 'data.test_table',
      paint: {},
      style_config: { builder: { strokeDisabled: true } },
    } as Partial<AdapterLayerInput> & { style_config: { builder: { strokeDisabled: boolean } } });
    fillAdapter.addLayers(map, input);
    const calls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    const fillPaint = calls[0][0].paint;
    expect(fillPaint['fill-outline-color']).toBe('rgba(0,0,0,0)');
  });

  it('getLayerIds returns [layerId, outlineId] (two layers without _height_column)', () => {
    const ids = fillAdapter.getLayerIds('layer-f1');
    expect(ids).toHaveLength(3);
    expect(ids[0]).toBe('layer-f1');
    expect(ids[1]).toBe('layer-f1-outline');
    expect(ids[2]).toBe('layer-f1-extrusion');
  });

  it('syncVisibility sets visibility on both main and outline layers', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'layer-f4' || id === 'layer-f4-outline') return { id };
      return null;
    });
    const input = makeInput({ id: 'f4', layerId: 'layer-f4', visible: false });
    fillAdapter.syncVisibility(map, input);
    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-f4', 'visibility', 'none');
    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-f4-outline', 'visibility', 'none');
  });

  it('syncPaint syncs outline layer line-color and line-width', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'layer-f5' || id === 'layer-f5-outline') return { id };
      return null;
    });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);
    const input = makeInput({
      id: 'f5',
      layerId: 'layer-f5',
      paint: { 'fill-color': '#aabbcc' },
      style_config: { builder: { outlineColor: '#112233', outlineWidth: 4 } },
    } as Partial<AdapterLayerInput> & { style_config: { builder: { outlineColor: string; outlineWidth: number } } });
    fillAdapter.syncPaint(map, input);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-f5-outline', 'line-color', '#112233');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-f5-outline', 'line-width', 4);
  });

  // fill-extrusion companion layer tests
  it('addLayers adds fill-extrusion companion layer when style_config.builder heightColumn is present (3 addLayer calls)', () => {
    const input = makeInput({
      id: 'fe1',
      layerId: 'layer-fe1',
      sourceId: 'source-fe1',
      sourceLayer: 'data.test_table',
      paint: { 'fill-color': '#3b82f6' },
      style_config: { builder: { heightColumn: 'bldg_ht' } },
    } as Partial<AdapterLayerInput> & { style_config: { builder: { heightColumn: string } } });
    fillAdapter.addLayers(map, input);
    expect(map.addLayer).toHaveBeenCalledTimes(3);
    const calls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls[0][0].type).toBe('fill');
    expect(calls[1][0].type).toBe('line');
    expect(calls[2][0].type).toBe('fill-extrusion');
    expect(calls[2][0].id).toBe('layer-fe1-extrusion');
  });

  it('addLayers does NOT add fill-extrusion when _height_column is absent (2 addLayer calls)', () => {
    const input = makeInput({
      id: 'fe2',
      layerId: 'layer-fe2',
      sourceId: 'source-fe2',
      sourceLayer: 'data.test_table',
      paint: { 'fill-color': '#3b82f6' },
    });
    fillAdapter.addLayers(map, input);
    expect(map.addLayer).toHaveBeenCalledTimes(2);
    const calls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.every((c: unknown[]) => (c[0] as { type: string }).type !== 'fill-extrusion')).toBe(true);
  });

  it('fill-extrusion paint uses coalesce+to-number expression for fill-extrusion-height', () => {
    const input = makeInput({
      id: 'fe3',
      layerId: 'layer-fe3',
      sourceId: 'source-fe3',
      sourceLayer: 'data.test_table',
      paint: {},
      style_config: { builder: { heightColumn: 'bldg_ht' } },
    } as Partial<AdapterLayerInput> & { style_config: { builder: { heightColumn: string } } });
    fillAdapter.addLayers(map, input);
    const calls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    const extrusionCall = calls.find((c: unknown[]) => (c[0] as { type: string }).type === 'fill-extrusion');
    expect(extrusionCall).toBeDefined();
    const extrusionPaint = (extrusionCall![0] as { paint: Record<string, unknown> }).paint;
    expect(extrusionPaint['fill-extrusion-height']).toEqual(
      ['coalesce', ['to-number', ['get', 'bldg_ht'], 0], 0],
    );
  });

  it('fill-extrusion layer has minzoom 14', () => {
    const input = makeInput({
      id: 'fe4',
      layerId: 'layer-fe4',
      sourceId: 'source-fe4',
      sourceLayer: 'data.test_table',
      paint: {},
      style_config: { builder: { heightColumn: 'height' } },
    } as Partial<AdapterLayerInput> & { style_config: { builder: { heightColumn: string } } });
    fillAdapter.addLayers(map, input);
    const calls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    const extrusionCall = calls.find((c: unknown[]) => (c[0] as { type: string }).type === 'fill-extrusion');
    expect(extrusionCall).toBeDefined();
    expect((extrusionCall![0] as { minzoom: number }).minzoom).toBe(14);
  });

  it('syncVisibility toggles extrusion layer visibility when it exists', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'layer-fe5' || id === 'layer-fe5-outline' || id === 'layer-fe5-extrusion') return { id };
      return null;
    });
    const input = makeInput({ id: 'fe5', layerId: 'layer-fe5', visible: false });
    fillAdapter.syncVisibility(map, input);
    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-fe5-extrusion', 'visibility', 'none');
  });

  it('_height_column is NOT passed through to MapLibre fill paint (stripped by CUSTOM_PAINT_PROPS)', () => {
    const input = makeInput({
      id: 'fe6',
      layerId: 'layer-fe6',
      sourceId: 'source-fe6',
      sourceLayer: 'data.test_table',
      paint: { 'fill-color': '#ff0000', '_height_column': 'height' },
    });
    fillAdapter.addLayers(map, input);
    const calls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    const fillCall = calls.find((c: unknown[]) => (c[0] as { type: string }).type === 'fill');
    expect(fillCall).toBeDefined();
    const fillPaint = (fillCall![0] as { paint: Record<string, unknown> }).paint;
    expect(fillPaint).not.toHaveProperty('_height_column');
  });

  it('addLayers does not pass private builder keys into MapLibre fill paint', () => {
    const input = makeInput({
      id: 'f-clean',
      layerId: 'layer-f-clean',
      sourceId: 'source-f-clean',
      sourceLayer: 'data.test_table',
      paint: {
        'fill-color': '#ff0000',
        '_stroke-disabled': true,
        '_outline-color': '#00ff00',
        '_outline-width': 2,
        '_height_column': 'height',
      },
    });
    fillAdapter.addLayers(map, input);
    const calls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    const fillPaint = calls.find((c: unknown[]) => (c[0] as { type: string }).type === 'fill')![0].paint;
    expect(Object.keys(fillPaint).some((key) => key.startsWith('_'))).toBe(false);
  });

  it('syncPaint does not pass private builder keys into MapLibre paint setters', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'layer-f-clean' || id === 'layer-f-clean-outline') return { id };
      return null;
    });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);
    const input = makeInput({
      id: 'f-clean',
      layerId: 'layer-f-clean',
      paint: {
        'fill-color': '#aabbcc',
        '_stroke-disabled': true,
        '_outline-color': '#112233',
        '_outline-width': 4,
      },
    });
    fillAdapter.syncPaint(map, input);

    const setPaintCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls;
    expect(setPaintCalls.every(([, prop]) => typeof prop !== 'string' || !prop.startsWith('_'))).toBe(true);
  });

  it('getLayerIds returns [layerId, outlineId, extrusionId] (three layers)', () => {
    const ids = fillAdapter.getLayerIds('layer-fe1');
    expect(ids).toHaveLength(3);
    expect(ids[0]).toBe('layer-fe1');
    expect(ids[1]).toBe('layer-fe1-outline');
    expect(ids[2]).toBe('layer-fe1-extrusion');
  });

});

// ──────────────────────────────────────────────────────────────────────────────
describe('heatmapAdapter', () => {
  let map: ReturnType<typeof createMockMap>;

  beforeEach(() => {
    map = createMockMap();
  });

  it('addLayers only passes heatmap paint keys to MapLibre', () => {
    const input = makeInput({
      id: 'h1',
      layerId: 'layer-h1',
      sourceId: 'source-h1',
      sourceLayer: 'data.test_table',
      paint: {
        'heatmap-radius': 40,
        '_heatmap-ramp': 'Viridis',
        '_heatmap-weight-column': 'count',
      },
      style_config: { builder: { heatmapRamp: 'Viridis', heatmapWeightColumn: 'count' } },
    } as Partial<AdapterLayerInput> & { style_config: { builder: { heatmapRamp: string; heatmapWeightColumn: string } } });

    heatmapAdapter.addLayers(map, input);
    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.paint).toHaveProperty('heatmap-radius', 40);
    expect(Object.keys(call.paint).some((key) => key.startsWith('_'))).toBe(false);
  });

  it('syncPaint skips private heatmap metadata', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-h2' });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);
    const input = makeInput({
      id: 'h2',
      layerId: 'layer-h2',
      paint: {
        'heatmap-radius': 48,
        '_heatmap-ramp': 'Blues',
        '_heatmap-weight-column': 'density',
      },
    });

    heatmapAdapter.syncPaint(map, input);
    const setPaintCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls;
    expect(setPaintCalls).toContainEqual(['layer-h2', 'heatmap-radius', 48]);
    expect(setPaintCalls.every(([, prop]) => typeof prop !== 'string' || !prop.startsWith('_'))).toBe(true);
  });
});

// ──────────────────────────────────────────────────────────────────────────────
describe('rasterAdapter', () => {
  let map: ReturnType<typeof createMockMap>;

  beforeEach(() => {
    map = createMockMap();
  });

  it('addLayers calls addSource with type raster and tile URL prefixed with origin', () => {
    const input = makeInput({
      id: 'r1',
      layerId: 'layer-r1',
      sourceId: 'source-r1',
      tileUrl: '/tiles/raster/{z}/{x}/{y}.png',
      tileSize: 256,
      minzoom: 0,
      maxzoom: 18,
    });
    rasterAdapter.addLayers(map, input);
    expect(map.addSource).toHaveBeenCalledWith('source-r1', {
      type: 'raster',
      tiles: ['http://localhost:8080/tiles/raster/{z}/{x}/{y}.png'],
      tileSize: 256,
      minzoom: 0,
      maxzoom: 18,
    });
  });

  it('addLayers adds raster layer type with raster-opacity', () => {
    const input = makeInput({ id: 'r2', layerId: 'layer-r2', sourceId: 'source-r2', opacity: 0.7, tileUrl: '/tiles/r/{z}/{x}/{y}.png' });
    rasterAdapter.addLayers(map, input);
    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.type).toBe('raster');
    expect(call.paint['raster-opacity']).toBe(0.7);
  });

  it('addLayers applies supported raster paint and keeps master opacity authoritative', () => {
    const input = makeInput({
      id: 'r2b',
      layerId: 'layer-r2b',
      sourceId: 'source-r2b',
      opacity: 0.7,
      tileUrl: '/tiles/r/{z}/{x}/{y}.png',
      paint: {
        'raster-brightness-min': 0.15,
        'raster-brightness-max': 0.9,
        'raster-contrast': 0.25,
        'raster-saturation': -0.2,
        'raster-hue-rotate': 45,
        'raster-resampling': 'nearest',
        'raster-fade-duration': 100,
        'raster-opacity': 0.2,
        'fill-color': '#ff0000',
      },
    });

    rasterAdapter.addLayers(map, input);

    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.paint).toEqual({
      'raster-brightness-min': 0.15,
      'raster-brightness-max': 0.9,
      'raster-contrast': 0.25,
      'raster-saturation': -0.2,
      'raster-hue-rotate': 45,
      'raster-resampling': 'nearest',
      'raster-fade-duration': 100,
      'raster-opacity': 0.7,
    });
  });

  it('addLayers does NOT call finalizeLayer or replayExpressions (no filter or expression replay)', () => {
    const input = makeInput({
      id: 'r3',
      layerId: 'layer-r3',
      sourceId: 'source-r3',
      tileUrl: '/tiles/r/{z}/{x}/{y}.png',
      filter: ['==', 'type', 'park'] as unknown as import('maplibre-gl').FilterSpecification,
    });
    rasterAdapter.addLayers(map, input);
    // setFilter should NOT be called — raster adapter does not support filter
    expect(map.setFilter).not.toHaveBeenCalled();
  });

  it('syncPaint syncs raster paint and does not apply filters', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-r4' });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(1);
    (map.getLayoutProperty as ReturnType<typeof vi.fn>).mockReturnValue('visible');
    const input = makeInput({
      id: 'r4',
      layerId: 'layer-r4',
      opacity: 0.5,
      paint: {
        'raster-contrast': 0.4,
        'raster-resampling': 'nearest',
      },
    });
    rasterAdapter.syncPaint(map, input);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4', 'raster-contrast', 0.4);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4', 'raster-resampling', 'nearest');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4', 'raster-opacity', 0.5);
    expect(map.setFilter).not.toHaveBeenCalled();
  });

  it('syncPaint resets removed raster paint to MapLibre defaults', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-r4b' });
    (map.getLayoutProperty as ReturnType<typeof vi.fn>).mockReturnValue('visible');
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockImplementation((_layerId: string, property: string) => {
      if (property === 'raster-brightness-min') return 0.2;
      if (property === 'raster-resampling') return 'nearest';
      if (property === 'raster-fade-duration') return 100;
      if (property === 'raster-opacity') return 1;
      return undefined;
    });

    const input = makeInput({
      id: 'r4b',
      layerId: 'layer-r4b',
      opacity: 1,
      paint: {},
    });
    rasterAdapter.syncPaint(map, input);

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4b', 'raster-brightness-min', 0);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4b', 'raster-resampling', 'linear');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4b', 'raster-fade-duration', 300);
  });

  it('getLayerIds returns [layerId]', () => {
    expect(rasterAdapter.getLayerIds('layer-r1')).toEqual(['layer-r1']);
  });

  it('addLayers sets visibility none when not visible', () => {
    const input = makeInput({
      id: 'r5',
      layerId: 'layer-r5',
      sourceId: 'source-r5',
      tileUrl: '/tiles/r/{z}/{x}/{y}.png',
      visible: false,
    });
    rasterAdapter.addLayers(map, input);
    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-r5', 'visibility', 'none');
  });

  it('addLayers does NOT call setLayoutProperty when visible=true', () => {
    const input = makeInput({
      id: 'r6',
      layerId: 'layer-r6',
      sourceId: 'source-r6',
      tileUrl: '/tiles/r/{z}/{x}/{y}.png',
      visible: true,
    });
    rasterAdapter.addLayers(map, input);
    expect(map.setLayoutProperty).not.toHaveBeenCalled();
  });
});

describe('hillshadeAdapter', () => {
  let map: ReturnType<typeof createMockMap>;

  beforeEach(() => {
    map = createMockMap();
  });

  it('addLayers creates a raster-dem source and hillshade layer', () => {
    const input = makeInput({
      id: 'h1',
      layerId: 'layer-h1',
      sourceId: 'source-h1',
      tileUrl: '/tiles/dem/{z}/{x}/{y}.png',
      paint: {
        'hillshade-illumination-direction': 280,
        'hillshade-illumination-anchor': 'map',
        'hillshade-exaggeration': 0.7,
        'hillshade-shadow-color': '#111111',
        'hillshade-highlight-color': '#eeeeee',
        'hillshade-accent-color': '#333333',
      },
    });

    hillshadeAdapter.addLayers(map, input);

    expect(map.addSource).toHaveBeenCalledWith('source-h1', {
      type: 'raster-dem',
      tiles: ['http://localhost:8080/tiles/dem/{z}/{x}/{y}.png'],
      tileSize: 256,
      minzoom: 0,
      maxzoom: 18,
      encoding: 'mapbox',
    });
    expect(map.addLayer).toHaveBeenCalledWith(expect.objectContaining({
      id: 'layer-h1',
      type: 'hillshade',
      source: 'source-h1',
      paint: expect.objectContaining({
        'hillshade-illumination-direction': 280,
        'hillshade-illumination-anchor': 'map',
        'hillshade-exaggeration': 0.7,
        'hillshade-shadow-color': '#111111',
        'hillshade-highlight-color': '#eeeeee',
        'hillshade-accent-color': '#333333',
      }),
    }));
  });

  it('syncPaint applies supported hillshade properties', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-h2', type: 'hillshade' });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);
    (map.getLayoutProperty as ReturnType<typeof vi.fn>).mockReturnValue('visible');
    const input = makeInput({
      id: 'h2',
      layerId: 'layer-h2',
      paint: {
        'hillshade-illumination-direction': 200,
        'hillshade-illumination-anchor': 'map',
        'hillshade-exaggeration': 0.65,
      },
    });

    hillshadeAdapter.syncPaint(map, input);

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-h2', 'hillshade-illumination-direction', 200);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-h2', 'hillshade-illumination-anchor', 'map');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-h2', 'hillshade-exaggeration', 0.65);
  });
});
