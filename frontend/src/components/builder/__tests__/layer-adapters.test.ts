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
    expect(map.addSprite).toHaveBeenCalledWith(
      'geolens',
      new URL('/api/maps/sprites/geolens', window.location.origin).toString(),
    );
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

  it('addLayers ignores stale fill and line paint on circle layers', () => {
    const input = makeInput({
      id: 'c2b',
      layerId: 'layer-c2b',
      paint: {
        'fill-color': '#ff0000',
        'line-color': '#00ff00',
        'line-width': 2,
        'fill-opacity': 0.4,
      },
    });

    circleAdapter.addLayers(map, input);

    const call = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.paint).toHaveProperty('circle-radius', 5);
    expect(call.paint).not.toHaveProperty('fill-color');
    expect(call.paint).not.toHaveProperty('line-color');
    expect(call.paint).not.toHaveProperty('line-width');
    expect(call.paint).not.toHaveProperty('fill-opacity');
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

  it('syncPaint does not send stale fill and line paint to circle layers', () => {
    (map.getLayer as ReturnType<typeof vi.fn>).mockReturnValue({ id: 'layer-c4b' });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);
    const input = makeInput({
      id: 'c4b',
      layerId: 'layer-c4b',
      paint: {
        'circle-radius': 7,
        'fill-color': '#ff0000',
        'line-color': '#00ff00',
        'line-width': 2,
        'fill-opacity': 0.4,
      },
    });

    circleAdapter.syncPaint(map, input);

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-c4b', 'circle-radius', 7);
    const invalidProps = new Set(['fill-color', 'line-color', 'line-width', 'fill-opacity']);
    expect((map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls
      .some(([, prop]) => invalidProps.has(prop))).toBe(false);
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
describe('clusterAdapter', () => {
  let map: ReturnType<typeof createMockMap>;

  beforeEach(() => {
    map = createMockMap();
  });

  it('addLayers creates cluster circle, count, and unclustered point layers over a GeoJSON source', () => {
    const input = makeInput({
      id: 'cluster-1',
      layerId: 'layer-cluster-1',
      sourceId: 'source-cluster-1',
      sourceLayer: 'data.points',
      sourceType: 'geojson',
      dataset_geometry_type: 'POINT',
      opacity: 0.7,
      paint: { 'circle-color': '#2255aa', 'circle-radius': 6 },
      filter: ['==', 'status', 'open'],
      style_config: {
        render_mode: 'cluster',
        builder: {
          clusterColor: '#fb923c',
          clusterTextColor: '#111827',
        },
      },
    });

    clusterAdapter.addLayers(map, input);

    expect(map.addLayer).toHaveBeenCalledTimes(3);
    const [clusterCircle, clusterCount, unclustered] = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls
      .map((call) => call[0]);
    expect(clusterCircle).toEqual(expect.objectContaining({
      id: 'layer-cluster-1-cluster',
      type: 'circle',
      source: 'source-cluster-1',
      filter: ['all', ['has', 'point_count'], ['==', 'status', 'open']],
    }));
    expect(clusterCircle).not.toHaveProperty('source-layer');
    expect(clusterCircle.paint).toEqual(expect.objectContaining({
      'circle-color': '#fb923c',
      'circle-opacity': 0.7,
    }));
    expect(clusterCount).toEqual(expect.objectContaining({
      id: 'layer-cluster-1-cluster-count',
      type: 'symbol',
      source: 'source-cluster-1',
      filter: ['all', ['has', 'point_count'], ['==', 'status', 'open']],
    }));
    expect(clusterCount.paint).toEqual(expect.objectContaining({
      'text-color': '#111827',
      'text-opacity': 0.7,
    }));
    expect(unclustered).toEqual(expect.objectContaining({
      id: 'layer-cluster-1',
      type: 'circle',
      source: 'source-cluster-1',
      filter: ['all', ['!', ['has', 'point_count']], ['==', 'status', 'open']],
    }));
    expect(unclustered).not.toHaveProperty('source-layer');
    expect(unclustered.paint).toEqual(expect.objectContaining({
      'circle-color': '#2255aa',
      'circle-radius': 6,
    }));
  });

  it('addLayers includes source-layer for server-side cluster vector sources', () => {
    const input = makeInput({
      id: 'cluster-vector',
      layerId: 'layer-cluster-vector',
      sourceId: 'source-cluster-vector',
      sourceLayer: 'data.large_points',
      sourceType: 'vector',
      dataset_geometry_type: 'POINT',
      style_config: { render_mode: 'cluster' },
    });

    clusterAdapter.addLayers(map, input);

    const [clusterCircle, clusterCount, unclustered] = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls
      .map((call) => call[0]);
    expect(clusterCircle).toHaveProperty('source-layer', 'data.large_points');
    expect(clusterCount).toHaveProperty('source-layer', 'data.large_points');
    expect(unclustered).toHaveProperty('source-layer', 'data.large_points');
  });

  it('syncPaint updates cluster companions and the unclustered point layer', () => {
    const input = makeInput({
      id: 'cluster-sync',
      layerId: 'layer-cluster-sync',
      sourceId: 'source-cluster-sync',
      sourceType: 'geojson',
      dataset_geometry_type: 'POINT',
      paint: { 'circle-color': '#2255aa', 'circle-radius': 6 },
      style_config: { render_mode: 'cluster', builder: { clusterColor: '#fb923c' } },
    });
    clusterAdapter.addLayers(map, input);
    (map.setPaintProperty as ReturnType<typeof vi.fn>).mockClear();
    (map.setFilter as ReturnType<typeof vi.fn>).mockClear();

    clusterAdapter.syncPaint(map, {
      ...input,
      opacity: 0.4,
      filter: ['==', 'status', 'planned'],
      style_config: {
        render_mode: 'cluster',
        builder: {
          clusterColor: '#22c55e',
          clusterTextColor: '#0f172a',
        },
      },
    });

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-cluster-sync-cluster', 'circle-color', '#22c55e');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-cluster-sync-cluster', 'circle-opacity', 0.4);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-cluster-sync-cluster-count', 'text-color', '#0f172a');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-cluster-sync-cluster-count', 'text-opacity', 0.4);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-cluster-sync', 'circle-radius', 6);
    expect(map.setFilter).toHaveBeenCalledWith('layer-cluster-sync-cluster', ['all', ['has', 'point_count'], ['==', 'status', 'planned']]);
    expect(map.setFilter).toHaveBeenCalledWith('layer-cluster-sync-cluster-count', ['all', ['has', 'point_count'], ['==', 'status', 'planned']]);
    expect(map.setFilter).toHaveBeenCalledWith('layer-cluster-sync', ['all', ['!', ['has', 'point_count']], ['==', 'status', 'planned']]);
  });

  it('syncVisibility toggles all cluster companion layers', () => {
    const input = makeInput({
      id: 'cluster-visible',
      layerId: 'layer-cluster-visible',
      sourceId: 'source-cluster-visible',
      sourceType: 'geojson',
      dataset_geometry_type: 'POINT',
      style_config: { render_mode: 'cluster' },
    });
    clusterAdapter.addLayers(map, input);
    (map.setLayoutProperty as ReturnType<typeof vi.fn>).mockClear();

    clusterAdapter.syncVisibility(map, { ...input, visible: false });

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-cluster-visible-cluster', 'visibility', 'none');
    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-cluster-visible-cluster-count', 'visibility', 'none');
    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-cluster-visible', 'visibility', 'none');
  });

  it('getLayerIds includes cluster companions and parent unclustered identity', () => {
    expect(clusterAdapter.getLayerIds('layer-c1')).toEqual([
      'layer-c1-cluster',
      'layer-c1-cluster-count',
      'layer-c1',
    ]);
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
    expect(opacityCalls.every(([, , value]) => JSON.stringify(value) === JSON.stringify(opacityExpression))).toBe(true);
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

  it('addLayers ignores stale line, circle, and extrusion paint on fill layers', () => {
    const input = makeInput({
      id: 'f3b',
      layerId: 'layer-f3b',
      sourceId: 'source-f3b',
      sourceLayer: 'data.test_table',
      paint: {
        'fill-color': '#ff0000',
        'line-color': '#00ff00',
        'circle-radius': 8,
        'fill-extrusion-height': 30,
      },
    });

    fillAdapter.addLayers(map, input);

    const fillPaint = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0].paint;
    expect(fillPaint).toHaveProperty('fill-color', '#ff0000');
    expect(fillPaint).not.toHaveProperty('line-color');
    expect(fillPaint).not.toHaveProperty('circle-radius');
    expect(fillPaint).not.toHaveProperty('fill-extrusion-height');
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

  it('fill-extrusion honors builder height scale, minzoom, and opacity', () => {
    const input = makeInput({
      id: 'fe4-scaled',
      layerId: 'layer-fe4-scaled',
      sourceId: 'source-fe4-scaled',
      sourceLayer: 'data.test_table',
      opacity: 0.7,
      paint: {},
      style_config: {
        builder: {
          heightColumn: 'height',
          heightScale: 1.8,
          extrusionMinZoom: 12.5,
          extrusionOpacity: 0.96,
        },
      },
    } as Partial<AdapterLayerInput> & { style_config: { builder: { heightColumn: string; heightScale: number; extrusionMinZoom: number; extrusionOpacity: number } } });
    fillAdapter.addLayers(map, input);
    const calls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    const extrusionCall = calls.find((c: unknown[]) => (c[0] as { type: string }).type === 'fill-extrusion');
    expect(extrusionCall).toBeDefined();
    const extrusion = extrusionCall![0] as { minzoom: number; paint: Record<string, unknown> };
    expect(extrusion.minzoom).toBe(12.5);
    expect(extrusion.paint['fill-extrusion-height']).toEqual(
      ['*', ['coalesce', ['to-number', ['get', 'height'], 0], 0], 1.8],
    );
    expect(extrusion.paint['fill-extrusion-opacity']).toBe(0.96);
  });

  it('normalizes snake_case builder style keys from saved API payloads', () => {
    const input = makeInput({
      id: 'fe4-snake',
      layerId: 'layer-fe4-snake',
      sourceId: 'source-fe4-snake',
      sourceLayer: 'data.test_table',
      opacity: 0.7,
      paint: {},
      style_config: {
        builder: {
          height_column: 'height',
          height_scale: 1.8,
          extrusion_min_zoom: 12.5,
          extrusion_opacity: 0.96,
          outline_color: '#07111f',
          outline_width: 0.28,
        },
      },
    } as unknown as Partial<AdapterLayerInput>);
    fillAdapter.addLayers(map, input);
    const calls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    const outlineCall = calls.find((c: unknown[]) => (c[0] as { type: string }).type === 'line');
    const extrusionCall = calls.find((c: unknown[]) => (c[0] as { type: string }).type === 'fill-extrusion');
    expect(outlineCall).toBeDefined();
    expect(extrusionCall).toBeDefined();

    const outlinePaint = (outlineCall![0] as { paint: Record<string, unknown> }).paint;
    expect(outlinePaint['line-color']).toBe('#07111f');
    expect(outlinePaint['line-width']).toBe(0.28);

    const extrusion = extrusionCall![0] as { minzoom: number; paint: Record<string, unknown> };
    expect(extrusion.minzoom).toBe(12.5);
    expect(extrusion.paint['fill-extrusion-height']).toEqual(
      ['*', ['coalesce', ['to-number', ['get', 'height'], 0], 0], 1.8],
    );
    expect(extrusion.paint['fill-extrusion-opacity']).toBe(0.96);
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
});
