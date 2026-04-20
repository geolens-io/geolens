import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  getAdapter,
  circleAdapter,
  lineAdapter,
  fillAdapter,
  rasterAdapter,
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

  it('falls back to circleAdapter for unknown type', () => {
    expect(getAdapter('unknown')).toBe(circleAdapter);
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

  it('addLayers reads _outline-color and _outline-width from paint for outline', () => {
    const input = makeInput({
      id: 'f2',
      layerId: 'layer-f2',
      sourceId: 'source-f2',
      sourceLayer: 'data.test_table',
      paint: {
        'fill-color': '#ff0000',
        '_outline-color': '#00ff00',
        '_outline-width': 3,
      },
    });
    fillAdapter.addLayers(map, input);
    const calls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    const outlinePaint = calls[1][0].paint;
    expect(outlinePaint['line-color']).toBe('#00ff00');
    expect(outlinePaint['line-width']).toBe(3);
  });

  it('addLayers sets fill-outline-color:transparent when _stroke-disabled is true', () => {
    const input = makeInput({
      id: 'f3',
      layerId: 'layer-f3',
      sourceId: 'source-f3',
      sourceLayer: 'data.test_table',
      paint: { '_stroke-disabled': true },
    });
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
      paint: {
        'fill-color': '#aabbcc',
        '_outline-color': '#112233',
        '_outline-width': 4,
      },
    });
    fillAdapter.syncPaint(map, input);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-f5-outline', 'line-color', '#112233');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-f5-outline', 'line-width', 4);
  });

  // fill-extrusion companion layer tests
  it('addLayers adds fill-extrusion companion layer when _height_column is present (3 addLayer calls)', () => {
    const input = makeInput({
      id: 'fe1',
      layerId: 'layer-fe1',
      sourceId: 'source-fe1',
      sourceLayer: 'data.test_table',
      paint: { 'fill-color': '#3b82f6', '_height_column': 'bldg_ht' },
    });
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
      paint: { '_height_column': 'bldg_ht' },
    });
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
      paint: { '_height_column': 'height' },
    });
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

  it('getLayerIds returns [layerId, outlineId, extrusionId] (three layers)', () => {
    const ids = fillAdapter.getLayerIds('layer-fe1');
    expect(ids).toHaveLength(3);
    expect(ids[0]).toBe('layer-fe1');
    expect(ids[1]).toBe('layer-fe1-outline');
    expect(ids[2]).toBe('layer-fe1-extrusion');
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

  it('syncPaint syncs raster-opacity only (no filter)', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-r4' });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(1);
    (map.getLayoutProperty as ReturnType<typeof vi.fn>).mockReturnValue('visible');
    const input = makeInput({ id: 'r4', layerId: 'layer-r4', opacity: 0.5 });
    rasterAdapter.syncPaint(map, input);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4', 'raster-opacity', 0.5);
    expect(map.setFilter).not.toHaveBeenCalled();
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
