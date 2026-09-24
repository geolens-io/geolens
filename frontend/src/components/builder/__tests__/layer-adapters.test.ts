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
  clusterAdapter,
} from '@/components/builder/layer-adapters';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';

vi.mock('@/lib/tile-utils', () => ({
  buildSignedTileUrl: vi.fn(() => '/tiles/mock/{z}/{x}/{y}.pbf'),
  buildClusterTileUrl: vi.fn(() => '/tiles/clusters/mock/{z}/{x}/{y}.pbf'),
}));

// Mock window.location.origin for raster tile URL construction
Object.defineProperty(window, 'location', {
  value: { origin: 'http://localhost:8080' },
  writable: true,
});

function createMockMap() {
  const layerIds = new Set<string>();
  return {
    getSource: vi.fn(() => null),
    addSource: vi.fn(),
    addLayer: vi.fn((layer: { id: string }) => {
      layerIds.add(layer.id);
    }),
    getLayer: vi.fn((id: string) => layerIds.has(id) ? { id } : null),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getPaintProperty: vi.fn(),
    getLayoutProperty: vi.fn(),
    getFilter: vi.fn().mockReturnValue(null),
    setFilter: vi.fn(),
    removeLayer: vi.fn((id: string) => {
      layerIds.delete(id);
    }),
    removeSource: vi.fn(),
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({ layers: [] })),
    getSprite: vi.fn(() => []),
    addSprite: vi.fn(),
    hasImage: vi.fn(() => false),
    addImage: vi.fn(),
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

  it('returns clusterAdapter for "cluster"', () => {
    expect(getAdapter('cluster')).toBe(clusterAdapter);
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

  it('returns cluster when render_mode is cluster', () => {
    expect(resolveAdapterType('POINT', { render_mode: 'cluster' })).toBe('cluster');
  });

  it('returns symbol when render_mode is symbol', () => {
    expect(resolveAdapterType('POINT', { render_mode: 'symbol' })).toBe('symbol');
  });

  it('returns line when render_mode is arrow', () => {
    expect(resolveAdapterType('LINESTRING', { render_mode: 'arrow' })).toBe('line');
    expect(resolveAdapterType(null, { render_mode: 'arrow' })).toBe('line');
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

  // fix(#430 codex r23): generic sentinels route to the mixed adapter so
  // point/line features of a mixed-family sketch are no longer dropped on maps.
  it('returns mixed for the GEOMETRY sentinel', () => {
    expect(resolveAdapterType('GEOMETRY', null)).toBe('mixed');
    expect(resolveAdapterType('geometry', null)).toBe('mixed');
  });

  it('returns mixed for GEOMETRYCOLLECTION', () => {
    expect(resolveAdapterType('GEOMETRYCOLLECTION', null)).toBe('mixed');
  });

  it('render_mode still overrides the generic sentinel', () => {
    expect(resolveAdapterType('GEOMETRY', { render_mode: 'heatmap' })).toBe('heatmap');
  });

  it('unknown exotic geometry types keep the historic fill fallback', () => {
    expect(resolveAdapterType('CURVE', null)).toBe('fill');
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

  it('addLayers prefers paint line-dasharray over legacy layout', () => {
    const input = makeInput({
      id: 'l1b',
      layerId: 'layer-l1b',
      sourceId: 'source-l1b',
      sourceLayer: 'data.test_table',
      dataset_geometry_type: 'LINESTRING',
      paint: { 'line-dasharray': [4, 2] },
      layout: { 'line-dasharray': [2, 4] },
    });
    lineAdapter.addLayers(map, input);
    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.paint['line-dasharray']).toEqual([4, 2]);
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

  it('getLayerIds includes the arrow companion cleanup id', () => {
    expect(lineAdapter.getLayerIds('layer-l1')).toEqual(['layer-l1', 'layer-l1-arrow']);
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
    // Identity (===) — engine-foundation guarantee that saved gradient expressions are
    // not deep-cloned mid-pipeline (see REVIEW.md WR-05 + the dedicated identity test below).
    const gradientCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls
      .filter(([, prop]) => prop === 'line-gradient');
    expect(gradientCalls.length).toBeGreaterThan(0);
    for (const [layerArg, , value] of gradientCalls) {
      expect(layerArg).toBe('layer-l5');
      expect(value).toBe(gradient);
    }
  });

  it('addLayers ignores stale fill and circle paint on line layers', () => {
    const input = makeInput({
      id: 'l5-stale',
      layerId: 'layer-l5-stale',
      dataset_geometry_type: 'LINESTRING',
      paint: {
        'line-color': '#ff0000',
        'fill-color': '#00ff00',
        'circle-radius': 8,
      },
    });

    lineAdapter.addLayers(map, input);

    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.paint).toHaveProperty('line-color', '#ff0000');
    expect(call.paint).not.toHaveProperty('fill-color');
    expect(call.paint).not.toHaveProperty('circle-radius');
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
    // Identity (===) — see comment on the previous test. line-gradient specifically uses
    // identity because Phase 256 builder UI relies on in-place stop mutation; the other
    // expression paints (line-width, line-opacity) keep structural equality below.
    const gradientCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls
      .filter(([, prop]) => prop === 'line-gradient');
    expect(gradientCalls.length).toBeGreaterThan(0);
    for (const [, , value] of gradientCalls) {
      expect(value).toBe(gradient);
    }
    // Structural equality (JSON.stringify) for non-line-gradient expression paints. Future
    // tightening to identity is OK but not required — the engine-foundation guarantee in
    // CONTEXT.md targets line-gradient specifically. See REVIEW.md WR-05 for context.
    const opacityCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls
      .filter(([, prop]) => prop === 'line-opacity');
    expect(opacityCalls.length).toBeGreaterThan(0);
    // fix(#1625): the LAST write wins — the per-feature expression lands on
    // line-opacity UNMULTIPLIED (shape preserved, never flattened to a number)
    // and the master slider (0.4) rides on line-layer-opacity. Before #1625 the
    // last write was ['*', expr, 0.4] (fix(#394) ST-03).
    const lastOpacityValue = opacityCalls[opacityCalls.length - 1][2];
    expect(JSON.stringify(lastOpacityValue)).toBe(JSON.stringify(opacityExpression));
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l5b', 'line-layer-opacity', 0.4);
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
    // Identity (===) — engine-foundation guarantee for Phase 256. See REVIEW.md WR-05.
    const gradientCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls
      .filter(([, prop]) => prop === 'line-gradient');
    expect(gradientCalls.length).toBeGreaterThan(0);
    for (const [, , value] of gradientCalls) {
      expect(value).toBe(gradient);
    }
  });

  it('syncPaint clears stale line-gradient when switching back to solid color', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-solid' });
    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockImplementation((_layerId, prop) =>
      prop === 'line-gradient' ? gradient : undefined,
    );
    const input = makeInput({
      id: 'solid',
      layerId: 'layer-solid',
      dataset_geometry_type: 'LINESTRING',
      paint: { 'line-color': '#f97316', 'line-width': 2 },
    });

    lineAdapter.syncPaint(map, input);

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-solid', 'line-gradient', undefined);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-solid', 'line-color', '#f97316');
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
    // Identity (===) — engine-foundation guarantee for Phase 256. See REVIEW.md WR-05.
    const gradientCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls
      .filter(([, prop]) => prop === 'line-gradient');
    expect(gradientCalls.length).toBeGreaterThan(0);
    for (const [, , value] of gradientCalls) {
      expect(value).toBe(gradient);
    }
    // Structural equality is acceptable for non-line-gradient expression paints. Tightening
    // to identity is a future cleanup but not required by the engine-foundation guarantee.
    const opacityCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls
      .filter(([, prop]) => prop === 'line-opacity');
    expect(opacityCalls.length).toBeGreaterThan(0);
    // fix(#1625): per-feature expression stays unmultiplied on line-opacity;
    // the master slider (0.4) goes to line-layer-opacity (was ['*', expr, 0.4]).
    const lastOpacityValue = opacityCalls[opacityCalls.length - 1][2];
    expect(JSON.stringify(lastOpacityValue)).toBe(JSON.stringify(opacityExpression));
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l7', 'line-layer-opacity', 0.4);
  });

  it('addLayers does not pass flattened line-gradient string to MapLibre addLayer when expressions present', () => {
    // Regression for REVIEW.md WR-02: simplifyPaint flattens line-gradient arrays to a scalar
    // fallback (e.g. value[4] color stop for interpolate). MapLibre's line-gradient REQUIRES
    // a ['line-progress'] expression — a constant string fails addLayer validation and the
    // try/catch silently swallows the error. The fix drops line-gradient from addLayer.paint
    // when the input has an array-valued gradient; replayExpressions installs the real
    // expression after addLayer succeeds.
    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    const widthExpression = ['interpolate', ['linear'], ['zoom'], 5, 1, 12, 8];
    const input = makeInput({
      id: 'l5c',
      layerId: 'layer-l5c',
      sourceId: 'source-l5c',
      sourceLayer: 'data.test_table',
      dataset_geometry_type: 'LINESTRING',
      paint: {
        // Force hasExpressions=true via line-width array so simplifyPaint runs.
        'line-color': '#ff0000',
        'line-width': widthExpression,
        'line-gradient': gradient,
      },
    });

    lineAdapter.addLayers(map, input);
    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    // line-gradient must be ABSENT from addLayer.paint — passing a flattened string would
    // make MapLibre reject the entire layer.
    expect(call.paint).not.toHaveProperty('line-gradient');
    // The real expression must still be installed via setPaintProperty (via replayExpressions).
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l5c', 'line-gradient', gradient);
  });

  it('preserves expression-valued line-gradient as identity through addLayers + syncPaint', () => {
    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    const input = makeInput({
      id: 'l-id',
      layerId: 'layer-l-id',
      sourceId: 'source-l-id',
      sourceLayer: 'data.test_table',
      dataset_geometry_type: 'LINESTRING',
      paint: { 'line-color': '#ff0000', 'line-width': 3, 'line-gradient': gradient },
    });

    lineAdapter.addLayers(map, input);
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-l-id' });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);
    lineAdapter.syncPaint(map, input);

    const setCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls
      .filter(([, prop]) => prop === 'line-gradient');
    // addLayers -> finalizeLayer -> replayExpressions sets it once.
    // syncPaint -> syncVectorPaint sets it again.
    expect(setCalls.length).toBeGreaterThanOrEqual(2);
    for (const [, , value] of setCalls) {
      // Identity (===), not just equality. Engine-foundation guarantee for Phase 256.
      expect(value).toBe(gradient);
    }
  });

  it('addLayers creates an arrow companion symbol layer for arrow render mode', () => {
    const input = makeInput({
      id: 'l-arrow',
      layerId: 'layer-l-arrow',
      sourceId: 'source-l-arrow',
      sourceLayer: 'data.routes',
      dataset_geometry_type: 'LINESTRING',
      paint: { 'line-color': '#2255aa', 'line-width': 3 },
      filter: ['==', 'status', 'open'],
      style_config: {
        render_mode: 'arrow',
        builder: {
          arrowColor: '#fb923c',
          arrowSize: 18,
          arrowSpacing: 120,
        },
      },
    });

    lineAdapter.addLayers(map, input);

    expect(map.addLayer).toHaveBeenCalledTimes(2);
    const lineCall = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    const arrowCall = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[1][0];
    expect(lineCall).toEqual(expect.objectContaining({
      id: 'layer-l-arrow',
      type: 'line',
    }));
    expect(arrowCall).toEqual(expect.objectContaining({
      id: 'layer-l-arrow-arrow',
      type: 'symbol',
      source: 'source-l-arrow',
      'source-layer': 'data.routes',
      filter: ['==', 'status', 'open'],
    }));
    expect(arrowCall.layout).toEqual(expect.objectContaining({
      'symbol-placement': 'line',
      'symbol-spacing': 120,
      'icon-image': 'geolens-line-arrow',
      'icon-size': 18 / 14,
      'icon-allow-overlap': true,
      'icon-ignore-placement': true,
      'icon-rotation-alignment': 'map',
      visibility: 'visible',
    }));
    expect(arrowCall.paint).toEqual({
      'icon-color': '#fb923c',
      'icon-opacity': 1,
    });
    expect(map.addImage).toHaveBeenCalledWith(
      'geolens-line-arrow',
      expect.objectContaining({ width: 24, height: 24 }),
      { sdf: true, pixelRatio: 1 },
    );
  });

  it('syncPaint updates arrow companion appearance, opacity, visibility, and filter', () => {
    const input = makeInput({
      id: 'l-arrow-sync',
      layerId: 'layer-l-arrow-sync',
      sourceId: 'source-l-arrow-sync',
      sourceLayer: 'data.routes',
      dataset_geometry_type: 'LINESTRING',
      paint: { 'line-color': '#2255aa', 'line-width': 3 },
      style_config: { render_mode: 'arrow', builder: { arrowColor: '#fb923c' } },
    });
    lineAdapter.addLayers(map, input);
    (map.setLayoutProperty as ReturnType<typeof vi.fn>).mockClear();
    (map.setPaintProperty as ReturnType<typeof vi.fn>).mockClear();
    (map.setFilter as ReturnType<typeof vi.fn>).mockClear();

    lineAdapter.syncPaint(map, {
      ...input,
      opacity: 0.45,
      visible: false,
      filter: ['==', 'status', 'planned'],
      style_config: {
        render_mode: 'arrow',
        builder: {
          arrowColor: '#22c55e',
          arrowSize: 22,
          arrowSpacing: 144,
        },
      },
    });

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-l-arrow-sync-arrow', 'symbol-spacing', 144);
    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-l-arrow-sync-arrow', 'icon-size', 22 / 14);
    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-l-arrow-sync-arrow', 'visibility', 'none');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l-arrow-sync-arrow', 'icon-color', '#22c55e');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-l-arrow-sync-arrow', 'icon-opacity', 0.45);
    expect(map.setFilter).toHaveBeenCalledWith('layer-l-arrow-sync-arrow', ['==', 'status', 'planned']);
  });

  it('syncPaint removes stale arrow companion when render mode returns to line', () => {
    const input = makeInput({
      id: 'l-arrow-remove',
      layerId: 'layer-l-arrow-remove',
      sourceId: 'source-l-arrow-remove',
      sourceLayer: 'data.routes',
      dataset_geometry_type: 'LINESTRING',
      style_config: { render_mode: 'arrow', builder: { arrowColor: '#fb923c' } },
    });
    lineAdapter.addLayers(map, input);
    (map.removeLayer as ReturnType<typeof vi.fn>).mockClear();

    lineAdapter.syncPaint(map, { ...input, style_config: null });

    expect(map.removeLayer).toHaveBeenCalledWith('layer-l-arrow-remove-arrow');
  });

  it('syncVisibility toggles line and arrow companion visibility together', () => {
    const input = makeInput({
      id: 'l-arrow-visible',
      layerId: 'layer-l-arrow-visible',
      sourceId: 'source-l-arrow-visible',
      sourceLayer: 'data.routes',
      dataset_geometry_type: 'LINESTRING',
      style_config: { render_mode: 'arrow', builder: { arrowColor: '#fb923c' } },
    });
    lineAdapter.addLayers(map, input);
    (map.setLayoutProperty as ReturnType<typeof vi.fn>).mockClear();

    lineAdapter.syncVisibility(map, { ...input, visible: false });

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-l-arrow-visible', 'visibility', 'none');
    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-l-arrow-visible-arrow', 'visibility', 'none');
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

  it('clamps hillshade exaggeration to MapLibre range before syncing paint', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-h2b', type: 'hillshade' });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);
    (map.getLayoutProperty as ReturnType<typeof vi.fn>).mockReturnValue('visible');
    const input = makeInput({
      id: 'h2b',
      layerId: 'layer-h2b',
      paint: {
        'hillshade-exaggeration': 2.1,
      },
    });

    hillshadeAdapter.syncPaint(map, input);

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-h2b', 'hillshade-exaggeration', 1);
  });

  it('compounds master opacity into hillshade color alpha instead of using raster-opacity', () => {
    const input = makeInput({
      id: 'h3',
      layerId: 'layer-h3',
      sourceId: 'source-h3',
      tileUrl: '/tiles/dem/{z}/{x}/{y}.png',
      opacity: 0.25,
      paint: {
        'hillshade-shadow-color': '#1f2937',
        'hillshade-highlight-color': 'rgba(255,255,255,0.8)',
        'hillshade-accent-color': '#64748b80',
      },
    });

    hillshadeAdapter.addLayers(map, input);

    expect(map.addLayer).toHaveBeenCalledWith(expect.objectContaining({
      id: 'layer-h3',
      type: 'hillshade',
      paint: expect.objectContaining({
        'hillshade-shadow-color': 'rgba(31, 41, 55, 0.25)',
        'hillshade-highlight-color': 'rgba(255, 255, 255, 0.2)',
        'hillshade-accent-color': 'rgba(100, 116, 139, 0.1255)',
      }),
    }));
  });

  it('syncPaint reapplies hillshade color alpha when only master opacity changes', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-h4', type: 'hillshade' });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);
    (map.getLayoutProperty as ReturnType<typeof vi.fn>).mockReturnValue('visible');
    const input = makeInput({
      id: 'h4',
      layerId: 'layer-h4',
      opacity: 0.4,
      paint: {
        'hillshade-shadow-color': '#1f2937',
        'hillshade-highlight-color': 'rgba(255,255,255,0.75)',
        'hillshade-accent-color': 'rgba(100,116,139,0.3333)',
      },
    });

    hillshadeAdapter.syncPaint(map, input);

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-h4', 'hillshade-shadow-color', 'rgba(31, 41, 55, 0.4)');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-h4', 'hillshade-highlight-color', 'rgba(255, 255, 255, 0.3)');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-h4', 'hillshade-accent-color', 'rgba(100, 116, 139, 0.1333)');
    expect(map.setPaintProperty).not.toHaveBeenCalledWith('layer-h4', 'raster-opacity', expect.anything());
  });

  // fix(#452): the hypso color-relief companion must follow the DEM layer's
  // visibility on visibility-only diffs (the viewer legend's live eye toggle
  // only calls syncVisibility — the full sync path that recreates the
  // companion never runs there).
  it('syncVisibility toggles the color-relief companion with the hillshade layer', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) =>
      id === 'layer-h5' || id === 'layer-h5-colorrelief' ? { id } : undefined,
    );
    const input = makeInput({ id: 'h5', layerId: 'layer-h5', visible: false });

    hillshadeAdapter.syncVisibility(map, input);

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-h5', 'visibility', 'none');
    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-h5-colorrelief', 'visibility', 'none');
  });

  it('syncVisibility no-ops the companion when it does not exist', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) =>
      id === 'layer-h6' ? { id } : undefined,
    );
    const input = makeInput({ id: 'h6', layerId: 'layer-h6', visible: false });

    hillshadeAdapter.syncVisibility(map, input);

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-h6', 'visibility', 'none');
    expect(map.setLayoutProperty).not.toHaveBeenCalledWith('layer-h6-colorrelief', 'visibility', expect.anything());
  });

  it('getLayerIds declares the color-relief companion', () => {
    expect(hillshadeAdapter.getLayerIds('layer-h1')).toEqual(['layer-h1', 'layer-h1-colorrelief']);
  });
});
