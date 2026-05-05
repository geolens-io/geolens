import { describe, it, expect, vi, beforeEach } from 'vitest';
import { syncLayersToMap, stripCustomProps, CUSTOM_PAINT_PROPS } from '@/components/builder/map-sync';
import type { MapLayerResponse } from '@/types/api';
import type { TileToken, RasterTileToken, VectorTileToken } from '@/api/tiles';

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
    setFilter: vi.fn(),
    removeLayer: vi.fn(),
    removeSource: vi.fn(),
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({ layers: [] })),
    moveLayer: vi.fn(),
    setLayerZoomRange: vi.fn(),
  } as unknown as import('maplibre-gl').Map;
}

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'Test',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'test_table',
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    sort_order: 0,
    filter: null,
    display_name: null,
    layer_type: 'vector_geolens',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    dataset_record_type: undefined,
    label_config: null,
    style_config: null,
    ...overrides,
  };
}

function makeRasterToken(overrides: Partial<RasterTileToken> = {}): RasterTileToken {
  return {
    kind: 'raster',
    tile_url: '/tiles/raster/{z}/{x}/{y}.png',
    bounds: null,
    minzoom: 0,
    maxzoom: 18,
    tile_size: 256,
    format: 'png',
    ...overrides,
  };
}

function makeVectorToken(overrides: Partial<VectorTileToken> = {}): VectorTileToken {
  return {
    kind: 'vector',
    sig: 'abc',
    exp: 9999999999,
    scope: 'test',
    expires_in: 3600,
    ...overrides,
  };
}

describe('CUSTOM_PAINT_PROPS', () => {
  it('contains both prefixed and non-prefixed outline props', () => {
    expect(CUSTOM_PAINT_PROPS.has('_outline-width')).toBe(true);
    expect(CUSTOM_PAINT_PROPS.has('_outline-color')).toBe(true);
    expect(CUSTOM_PAINT_PROPS.has('outline-width')).toBe(true);
    expect(CUSTOM_PAINT_PROPS.has('outline-color')).toBe(true);
  });
});

describe('stripCustomProps', () => {
  it('strips prefixed custom props', () => {
    const paint = {
      'fill-color': '#ff0000',
      '_outline-width': 2,
      '_outline-color': '#000',
      '_fill-disabled': true,
    };
    const result = stripCustomProps(paint);
    expect(result).toEqual({ 'fill-color': '#ff0000' });
  });

  it('strips non-prefixed outline props (legacy data)', () => {
    const paint = {
      'fill-color': '#ff0000',
      'fill-opacity': 0.5,
      'outline-width': 2,
      'outline-color': '#000',
    };
    const result = stripCustomProps(paint);
    expect(result).toEqual({ 'fill-color': '#ff0000', 'fill-opacity': 0.5 });
  });

  it('strips both prefixed and non-prefixed when both present', () => {
    const paint = {
      'line-color': '#00f',
      '_outline-width': 3,
      'outline-width': 2,
      '_outline-color': '#111',
      'outline-color': '#222',
    };
    const result = stripCustomProps(paint);
    expect(result).toEqual({ 'line-color': '#00f' });
  });

  it('returns empty object when all props are custom', () => {
    const paint = {
      '_outline-width': 1,
      'outline-color': '#000',
      '_fill-disabled': false,
    };
    expect(stripCustomProps(paint)).toEqual({});
  });

  it('passes through standard MapLibre paint props untouched', () => {
    const paint = {
      'circle-radius': 5,
      'circle-color': '#f00',
      'circle-stroke-width': 1,
    };
    const result = stripCustomProps(paint);
    expect(result).toEqual(paint);
  });
});

describe('syncLayersToMap', () => {
  let map: ReturnType<typeof createMockMap>;
  let managedSourcesRef: { current: Set<string> };

  beforeEach(() => {
    map = createMockMap();
    managedSourcesRef = { current: new Set() };
  });

  it('raster layer adds raster source and raster layer type', () => {
    const layer = makeLayer({
      id: 'r1',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.addSource).toHaveBeenCalledWith('source-r1', {
      type: 'raster',
      tiles: ['http://localhost:8080/tiles/raster/{z}/{x}/{y}.png'],
      tileSize: 256,
      minzoom: 0,
      maxzoom: 18,
    });

    const addLayerCall = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(addLayerCall.type).toBe('raster');
    expect(addLayerCall.paint['raster-opacity']).toBe(1);
  });

  it('raster layer respects opacity', () => {
    const layer = makeLayer({
      id: 'r2',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      opacity: 0.6,
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    const addLayerCall = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(addLayerCall.paint['raster-opacity']).toBe(0.6);
  });

  it('raster layer applies supported paint on add', () => {
    const layer = makeLayer({
      id: 'r2b',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      opacity: 0.75,
      paint: {
        'raster-brightness-min': 0.1,
        'raster-brightness-max': 0.95,
        'raster-contrast': 0.35,
        'raster-saturation': -0.25,
        'raster-hue-rotate': 90,
        'raster-resampling': 'nearest',
        'raster-fade-duration': 150,
      },
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    const addLayerCall = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(addLayerCall.paint).toEqual({
      'raster-brightness-min': 0.1,
      'raster-brightness-max': 0.95,
      'raster-contrast': 0.35,
      'raster-saturation': -0.25,
      'raster-hue-rotate': 90,
      'raster-resampling': 'nearest',
      'raster-fade-duration': 150,
      'raster-opacity': 0.75,
    });
  });

  it('DEM hillshade layer uses raster-dem source and hillshade layer output', () => {
    const layer = makeLayer({
      id: 'dem1',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      is_dem: true,
      style_config: { mode: 'categorical', column: '', ramp: '', render_mode: 'hillshade' },
      paint: {
        'hillshade-illumination-direction': 275,
        'hillshade-illumination-anchor': 'map',
        'hillshade-exaggeration': 0.7,
      },
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.addSource).toHaveBeenCalledWith('source-dem1', expect.objectContaining({
      type: 'raster-dem',
      encoding: 'mapbox',
    }));
    const addLayerCall = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(addLayerCall.type).toBe('hillshade');
    expect(addLayerCall.paint).toEqual(expect.objectContaining({
      'hillshade-illumination-direction': 275,
      'hillshade-illumination-anchor': 'map',
      'hillshade-exaggeration': 0.7,
    }));
  });

  it('hidden raster layer sets visibility none', () => {
    const layer = makeLayer({
      id: 'r3',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      visible: false,
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-r3', 'visibility', 'none');
  });

  it('vector layer adds vector source and fill layer for Polygon', () => {
    const layer = makeLayer({
      id: 'v1',
      layer_type: 'vector_geolens',
      dataset_geometry_type: 'Polygon',
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeVectorToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.addSource).toHaveBeenCalledWith(
      'source-v1',
      expect.objectContaining({ type: 'vector' }),
    );
    // fill layer is added first, then outline layer
    const addLayerCalls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    expect(addLayerCalls[0][0].type).toBe('fill');
  });

  it('vector layer adds circle layer for POINT', () => {
    const layer = makeLayer({
      id: 'v2',
      layer_type: 'vector_geolens',
      dataset_geometry_type: 'POINT',
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeVectorToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    const addLayerCalls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    expect(addLayerCalls[0][0].type).toBe('circle');
  });

  it('vector layer adds line layer for LINESTRING', () => {
    const layer = makeLayer({
      id: 'v3',
      layer_type: 'vector_geolens',
      dataset_geometry_type: 'LINESTRING',
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeVectorToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    const addLayerCalls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    expect(addLayerCalls[0][0].type).toBe('line');
  });

  it('stale sources are removed', () => {
    managedSourcesRef.current = new Set(['source-old']);
    // Mock getLayer to return truthy for old layers so removeLayer works
    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'layer-old' || id === 'layer-old-outline' || id === 'layer-old-label') {
        return { id };
      }
      return null;
    });
    (map.getSource as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'source-old') return { type: 'vector' };
      return null;
    });

    syncLayersToMap(map, [], new Map(), undefined, managedSourcesRef, { current: '' });

    expect(map.removeLayer).toHaveBeenCalledWith('layer-old');
    expect(map.removeSource).toHaveBeenCalledWith('source-old');
  });

  it('existing raster source syncs opacity without re-adding', () => {
    const layer = makeLayer({
      id: 'r4',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      opacity: 0.7,
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken()]]);

    // Source already exists
    (map.getSource as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'source-r4') return { type: 'raster' };
      return null;
    });
    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'layer-r4') return { id };
      return null;
    });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(1);
    (map.getLayoutProperty as ReturnType<typeof vi.fn>).mockReturnValue('visible');

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.addSource).not.toHaveBeenCalled();
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4', 'raster-opacity', 0.7);
  });

  it('existing raster source syncs raster paint without re-adding', () => {
    const layer = makeLayer({
      id: 'r4b',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      opacity: 0.8,
      paint: {
        'raster-brightness-min': 0.15,
        'raster-brightness-max': 0.9,
        'raster-contrast': 0.45,
        'raster-saturation': -0.3,
        'raster-hue-rotate': 75,
        'raster-resampling': 'nearest',
        'raster-fade-duration': 125,
      },
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken()]]);

    (map.getSource as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'source-r4b') return { type: 'raster' };
      return null;
    });
    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'layer-r4b') return { id };
      return null;
    });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);
    (map.getLayoutProperty as ReturnType<typeof vi.fn>).mockReturnValue('visible');

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.addSource).not.toHaveBeenCalled();
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4b', 'raster-brightness-min', 0.15);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4b', 'raster-brightness-max', 0.9);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4b', 'raster-contrast', 0.45);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4b', 'raster-saturation', -0.3);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4b', 'raster-hue-rotate', 75);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4b', 'raster-resampling', 'nearest');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4b', 'raster-fade-duration', 125);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4b', 'raster-opacity', 0.8);
  });

  it('vector point layer with opacity 1.0 still sets circle-opacity paint property', () => {
    const layer = makeLayer({
      id: 'op1',
      dataset_geometry_type: 'Point',
      opacity: 1,
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeVectorToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-op1', 'circle-opacity', 1);
  });

  it('fill layer with opacity 1.0 sets fill-opacity and outline line-opacity', () => {
    const layer = makeLayer({
      id: 'op2',
      dataset_geometry_type: 'Polygon',
      opacity: 1,
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeVectorToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    // fill-opacity = 0.3 (default) * 1 = 0.3
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-op2', 'fill-opacity', 0.3);
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-op2-outline', 'line-opacity', 1);
  });

  it('existing label layer syncs filter during paint update', () => {
    const layer = makeLayer({
      id: 'lf1',
      dataset_geometry_type: 'Polygon',
      label_config: { column: 'name' },
      filter: ['==', 'type', 'park'],
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeVectorToken()]]);

    // Simulate existing source and label layer
    (map.getSource as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'source-lf1') return { type: 'vector' };
      return null;
    });
    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'layer-lf1' || id === 'layer-lf1-outline' || id === 'layer-lf1-label') return { id };
      return null;
    });
    (map.getPaintProperty as ReturnType<typeof vi.fn>).mockReturnValue(undefined);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    // Label layer filter should be synced
    expect(map.setFilter).toHaveBeenCalledWith('layer-lf1-label', ['==', 'type', 'park']);
  });

  it('addLayer failure does not throw or prevent subsequent layers', () => {
    (map.addLayer as ReturnType<typeof vi.fn>).mockImplementation(() => {
      throw new Error('unknown property "outline-width"');
    });
    const layer = makeLayer({
      id: 'fail1',
      dataset_geometry_type: 'Polygon',
      paint: { 'outline-width': 2 },
    });
    const layer2 = makeLayer({
      id: 'ok1',
      dataset_geometry_type: 'Point',
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeVectorToken()]]);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    // Should not throw
    expect(() => {
      syncLayersToMap(map, [layer, layer2], tokenMap, undefined, managedSourcesRef, { current: '' });
    }).not.toThrow();

    // Both layers attempted
    expect(map.addSource).toHaveBeenCalledTimes(2);
    warnSpy.mockRestore();
  });

  it('polygon layer with non-prefixed outline-width strips it from fill paint', () => {
    const layer = makeLayer({
      id: 'legacy1',
      dataset_geometry_type: 'Polygon',
      paint: {
        'fill-color': '#ff0000',
        'outline-width': 3,
        'outline-color': '#000000',
      },
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeVectorToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    const addLayerCalls = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls;
    // Fill layer paint should NOT contain outline-width or outline-color
    const fillPaint = addLayerCalls[0][0].paint;
    expect(fillPaint).not.toHaveProperty('outline-width');
    expect(fillPaint).not.toHaveProperty('outline-color');
    expect(fillPaint).toHaveProperty('fill-color', '#ff0000');

    // Outline layer should pick up the non-prefixed values as line-color/line-width
    const outlinePaint = addLayerCalls[1][0].paint;
    expect(outlinePaint['line-color']).toBe('#000000');
    expect(outlinePaint['line-width']).toBe(3);
  });
});
