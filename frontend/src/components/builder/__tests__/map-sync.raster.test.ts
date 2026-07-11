import { describe, it, expect, vi, beforeEach } from 'vitest';
import { syncLayersToMap, stripCustomProps, CUSTOM_PAINT_PROPS, isHillshadeTerrainBound } from '@/components/builder/map-sync';
import type { SyncLayerInput } from '@/components/builder/map-sync';
import type { MapLayerResponse, MapTerrainConfig } from '@/types/api';
import type { TileToken, RasterTileToken, VectorTileToken } from '@/api/tiles';

vi.mock('@/lib/tile-utils', () => ({
  getMvtSourceLayerName: (table: string) => `data.${table}`,
  buildSignedTileUrl: vi.fn(() => '/tiles/mock/{z}/{x}/{y}.pbf'),
  buildClusterTileUrl: vi.fn(() => '/tiles/clusters/mock/{z}/{x}/{y}.pbf'),
}));

// Mock color-relief-sync so the raster sync tests can assert it is invoked for DEM layers
// without needing a real DemSource. Use vi.hoisted so the mock factory can reference the
// spy despite vi.mock hoisting.
const { mockSyncColorReliefLayer } = vi.hoisted(() => ({
  mockSyncColorReliefLayer: vi.fn(),
}));
vi.mock('@/components/builder/color-relief-sync', () => ({
  syncColorReliefLayer: mockSyncColorReliefLayer,
  buildElevationExpression: vi.fn(() => ['interpolate', ['linear'], ['elevation']]),
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
    mockSyncColorReliefLayer.mockClear();
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

  it('shared raster layers render from embedded tile_url when no token map is available', () => {
    const layer = {
      ...makeLayer({
        id: 'shared-raster',
        layer_type: 'raster_geolens',
        dataset_record_type: 'raster_dataset',
        dataset_geometry_type: null,
      }),
      tile_url: '/raster-tiles/shared-raster/tiles/{z}/{x}/{y}.png',
    } as SyncLayerInput;

    syncLayersToMap(map, [layer], new Map(), undefined, managedSourcesRef, { current: '' });

    expect(map.addSource).toHaveBeenCalledWith('source-shared-raster', {
      type: 'raster',
      tiles: ['http://localhost:8080/raster-tiles/shared-raster/tiles/{z}/{x}/{y}.png'],
      tileSize: 256,
      minzoom: 0,
      maxzoom: 18,
    });
    const addLayerCall = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(addLayerCall.type).toBe('raster');
  });

  it('reorders vector layers above raster layers when the vector is first in stack order', () => {
    const vectorLayer = makeLayer({
      id: 'peaks',
      dataset_id: 'vector-ds',
      dataset_geometry_type: 'Point',
      dataset_table_name: 'peaks_table',
      dataset_record_type: 'vector_dataset',
      layer_type: 'vector_geolens',
    });
    const rasterLayer = makeLayer({
      id: 'aerial',
      dataset_id: 'raster-ds',
      dataset_geometry_type: null,
      dataset_table_name: 'aerial_table',
      dataset_record_type: 'raster_dataset',
      layer_type: 'raster_geolens',
    });
    const tokenMap = new Map<string, TileToken>([
      ['vector-ds', makeVectorToken()],
      ['raster-ds', makeRasterToken()],
    ]);

    syncLayersToMap(
      map,
      [vectorLayer, rasterLayer],
      tokenMap,
      undefined,
      managedSourcesRef,
      { current: '' },
    );

    const movedLayerIds = (map.moveLayer as ReturnType<typeof vi.fn>).mock.calls.map(([id]) => id);
    expect(movedLayerIds.indexOf('layer-aerial')).toBeLessThan(movedLayerIds.indexOf('layer-peaks'));
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

  it('DEM terrain mode does not draw raw elevation tiles as a visual raster layer', () => {
    const layer = makeLayer({
      id: 'dem-terrain',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      is_dem: true,
      style_config: { render_mode: 'terrain' } as unknown as MapLayerResponse['style_config'],
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.addSource).not.toHaveBeenCalled();
    expect(map.addLayer).not.toHaveBeenCalled();
    expect(managedSourcesRef.current).toEqual(new Set());
  });

  it('DEM terrain mode cleans up a stale raster or hillshade visual layer from a previous mode', () => {
    const layer = makeLayer({
      id: 'dem-terrain',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      is_dem: true,
      style_config: { render_mode: 'terrain' } as unknown as MapLayerResponse['style_config'],
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken()]]);
    managedSourcesRef.current = new Set(['source-dem-terrain']);
    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => (
      id === 'layer-dem-terrain' ? { id } : null
    ));
    (map.getSource as ReturnType<typeof vi.fn>).mockImplementation((id: string) => (
      id === 'source-dem-terrain' ? { type: 'raster' } : null
    ));

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.addSource).not.toHaveBeenCalled();
    expect(map.addLayer).not.toHaveBeenCalled();
    expect(map.removeLayer).toHaveBeenCalledWith('layer-dem-terrain');
    expect(map.removeSource).toHaveBeenCalledWith('source-dem-terrain');
    expect(managedSourcesRef.current).toEqual(new Set());
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

    // Phase 1050 SF-04: non-cluster vector layers share a deduped source
    // keyed by dataset_table_name (`test_table` from the factory).
    expect(map.addSource).toHaveBeenCalledWith(
      'source-data-test_table',
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
      if (id === 'source-r4') {
        return {
          type: 'raster',
          serialize: () => ({
            tiles: ['http://localhost:8080/tiles/raster/{z}/{x}/{y}.png'],
            tileSize: 256,
            minzoom: 0,
            maxzoom: 18,
          }),
        };
      }
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
      if (id === 'source-r4b') {
        return {
          type: 'raster',
          serialize: () => ({
            tiles: ['http://localhost:8080/tiles/raster/{z}/{x}/{y}.png'],
            tileSize: 256,
            minzoom: 0,
            maxzoom: 18,
          }),
        };
      }
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

  it('rebuilds an existing raster source when tile zoom metadata changes', () => {
    const layer = makeLayer({
      id: 'r5',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken({ maxzoom: 17 })]]);
    let sourceExists = true;

    (map.getSource as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'source-r5' && sourceExists) {
        return {
          type: 'raster',
          serialize: () => ({
            tiles: ['http://localhost:8080/tiles/raster/{z}/{x}/{y}.png'],
            tileSize: 256,
            minzoom: 0,
            maxzoom: 18,
          }),
        };
      }
      return null;
    });
    (map.removeSource as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'source-r5') sourceExists = false;
    });
    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'layer-r5') return { id, type: 'raster' };
      return null;
    });

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.removeLayer).toHaveBeenCalledWith('layer-r5');
    expect(map.removeSource).toHaveBeenCalledWith('source-r5');
    expect(map.addSource).toHaveBeenCalledWith('source-r5', expect.objectContaining({
      maxzoom: 17,
    }));
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

    // Simulate existing source and label layer. Phase 1050 SF-04: non-cluster
    // vector layers share a deduped source keyed by dataset_table_name (here
    // `test_table` from the `makeLayer` factory), so the source id is
    // `source-data-test_table` (not the legacy per-layer `source-lf1`).
    (map.getSource as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'source-data-test_table') return { type: 'vector' };
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

  // ---------------------------------------------------------------------------
  // EDITOR-DEM-05: syncColorReliefLayer wiring
  // ---------------------------------------------------------------------------

  describe('syncColorReliefLayer wiring', () => {
    beforeEach(() => {
      mockSyncColorReliefLayer.mockClear();
    });

    it('calls syncColorReliefLayer for is_dem=true raster layers', () => {
      const layer = makeLayer({
        id: 'dem-cr-test',
        layer_type: 'raster_geolens',
        dataset_geometry_type: null,
        is_dem: true,
        style_config: { mode: 'categorical', column: '', ramp: '', render_mode: 'hillshade' },
        paint: { '_hypso-enabled': true },
      });
      const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken()]]);

      syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

      expect(mockSyncColorReliefLayer).toHaveBeenCalledOnce();
      const [, calledInput] = mockSyncColorReliefLayer.mock.calls[0] as [unknown, { layerId: string; is_dem: boolean | null | undefined }];
      expect(calledInput.layerId).toBe('layer-dem-cr-test');
      expect(calledInput.is_dem).toBe(true);
    });

    it('does NOT call syncColorReliefLayer for non-DEM raster layers', () => {
      const layer = makeLayer({
        id: 'raster-regular-cr',
        layer_type: 'raster_geolens',
        dataset_geometry_type: null,
        is_dem: false,
      });
      const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken()]]);

      syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

      expect(mockSyncColorReliefLayer).not.toHaveBeenCalled();
    });

    it('does NOT call syncColorReliefLayer for vector layers', () => {
      const layer = makeLayer({
        id: 'vector-cr-test',
        layer_type: 'vector_geolens',
        dataset_geometry_type: 'Polygon',
        is_dem: false,
      });
      const tokenMap = new Map<string, TileToken>([['ds-1', makeVectorToken()]]);

      syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

      expect(mockSyncColorReliefLayer).not.toHaveBeenCalled();
    });
  });

  // Regression test for WR-01: color-relief companion layer is removed when its
  // DEM layer is deleted from the layers list.
  it('WR-01 regression: color-relief companion layer is removed when DEM source becomes stale', () => {
    // Simulate a prior state where source-dem-wr01 and layer-dem-wr01-colorrelief are on the map.
    managedSourcesRef.current = new Set(['source-dem-wr01']);
    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'layer-dem-wr01' || id === 'layer-dem-wr01-colorrelief') return { id };
      return null;
    });
    (map.getSource as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'source-dem-wr01') return { type: 'raster-dem' };
      return null;
    });

    // Sync with no layers — source-dem-wr01 is now stale.
    syncLayersToMap(map, [], new Map(), undefined, managedSourcesRef, { current: '' });

    // The main hillshade layer should be removed.
    expect(map.removeLayer).toHaveBeenCalledWith('layer-dem-wr01');
    // The color-relief companion layer (no own source) MUST also be removed.
    expect(map.removeLayer).toHaveBeenCalledWith('layer-dem-wr01-colorrelief');
    // The source should be removed too.
    expect(map.removeSource).toHaveBeenCalledWith('source-dem-wr01');
  });

  it('removes color-relief before replacing a DEM hillshade source', () => {
    const layer = makeLayer({
      id: 'dem-source-swap',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      is_dem: true,
      style_config: null,
    });
    const sourceId = 'source-dem-source-swap';
    const baseLayerId = 'layer-dem-source-swap';
    const colorReliefId = `${baseLayerId}-colorrelief`;
    const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken()]]);

    (map.getLayer as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === baseLayerId) return { id, type: 'hillshade' };
      if (id === colorReliefId) return { id, type: 'color-relief' };
      return null;
    });
    (map.getSource as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === sourceId) {
        return {
          type: 'raster-dem',
          tiles: ['http://localhost:8080/tiles/old-dem/{z}/{x}/{y}.png'],
          tileSize: 256,
          minzoom: 0,
          maxzoom: 18,
        };
      }
      return null;
    });

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.removeLayer).toHaveBeenCalledWith(colorReliefId);
    expect(map.removeLayer).toHaveBeenCalledWith(baseLayerId);
    expect(map.removeSource).toHaveBeenCalledWith(sourceId);
    const colorReliefRemoveOrder = (map.removeLayer as ReturnType<typeof vi.fn>).mock.invocationCallOrder[
      (map.removeLayer as ReturnType<typeof vi.fn>).mock.calls.findIndex(([id]) => id === colorReliefId)
    ];
    const sourceRemoveOrder = (map.removeSource as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0];
    expect(colorReliefRemoveOrder).toBeLessThan(sourceRemoveOrder);
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

// ---------------------------------------------------------------------------
// POLISH-02: isHillshadeTerrainBound predicate + syncRasterLayer skip guard
// ---------------------------------------------------------------------------

describe('POLISH-02 isHillshadeTerrainBound predicate', () => {
  const demLayer = { dataset_id: 'dem-ds-1', is_dem: true as boolean | null };
  const otherLayer = { dataset_id: 'other-ds-1', is_dem: true as boolean | null };

  function makeTerrainConfig(overrides: Partial<MapTerrainConfig> = {}): MapTerrainConfig {
    return {
      enabled: true,
      source_dataset_id: 'dem-ds-1',
      exaggeration: 1,
      ...overrides,
    };
  }

  it('Test A: returns true when terrain enabled + same dataset + is_dem', () => {
    expect(isHillshadeTerrainBound(demLayer, makeTerrainConfig())).toBe(true);
  });

  it('Test B: returns false when terrain is disabled (Map B scenario)', () => {
    expect(isHillshadeTerrainBound(demLayer, makeTerrainConfig({ enabled: false }))).toBe(false);
  });

  it('Test C: returns false when source_dataset_id !== layer.dataset_id (different DEM)', () => {
    expect(isHillshadeTerrainBound(otherLayer, makeTerrainConfig())).toBe(false);
  });

  it('Test D: returns false when terrainConfig is null', () => {
    expect(isHillshadeTerrainBound(demLayer, null)).toBe(false);
  });

  it('Test D (undefined): returns false when terrainConfig is undefined', () => {
    expect(isHillshadeTerrainBound(demLayer, undefined)).toBe(false);
  });

  it('returns false when is_dem is false even if terrain matches', () => {
    expect(isHillshadeTerrainBound({ dataset_id: 'dem-ds-1', is_dem: false }, makeTerrainConfig())).toBe(false);
  });
});

describe('POLISH-02 syncRasterLayer hillshade skip guard', () => {
  let map: ReturnType<typeof createMockMap>;
  let managedSourcesRef: { current: Set<string> };

  function makeDEMLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
    return {
      id: 'dem-layer-1',
      dataset_id: 'dem-ds-1',
      dataset_name: 'Test DEM',
      dataset_geometry_type: null,
      dataset_table_name: 'dem_table',
      dataset_extent_bbox: null,
      dataset_column_info: null,
      dataset_feature_count: null,
      dataset_sample_values: null,
      display_name: null,
      sort_order: 0,
      visible: true,
      opacity: 1,
      paint: {},
      layout: {},
      filter: null,
      label_config: null,
      style_config: { render_mode: 'hillshade' } as MapLayerResponse['style_config'],
      layer_type: 'raster_geolens',
      dataset_record_type: 'raster_dataset',
      is_dem: true,
      dem_vertical_units: null,
      show_in_legend: true,
      ...overrides,
    } as MapLayerResponse;
  }

  beforeEach(() => {
    mockSyncColorReliefLayer.mockClear();
    map = createMockMap();
    managedSourcesRef = { current: new Set() };
  });

  // fix(HT-05): a terrain-bound hillshade DEM always paints its visible overlay
  // on its own per-layer source (`source-dem-layer-1`) alongside the 3D mesh.
  // The old tile-size-mismatch skip guard was dead code (same-dataset binding
  // means the sizes always match) and has been removed.
  it('Test E: a terrain-bound hillshade DEM paints its own per-layer source', () => {
    const layer = makeDEMLayer(); // dataset_id 'dem-ds-1', render_mode 'hillshade'
    const tokenMap = new Map<string, TileToken>([
      ['dem-ds-1', makeRasterToken({ tile_url: '/tiles/dem/{z}/{x}/{y}.png', tile_size: 256 })],
    ]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    // The hillshade consumer runs on its own per-layer source (`source-dem-layer-1`).
    expect((map.addSource as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(0);
    const addSourceIds = (map.addSource as ReturnType<typeof vi.fn>).mock.calls.map(([id]) => id);
    expect(addSourceIds).toContain('source-dem-layer-1');
    const addLayerCall = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(addLayerCall.type).toBe('hillshade');
  });

  it('normalizes legacy DEM image mode to hillshade before rendering', () => {
    const layer = makeDEMLayer({
      style_config: { render_mode: 'image' } as unknown as MapLayerResponse['style_config'],
    });
    const tokenMap = new Map<string, TileToken>([
      ['dem-ds-1', makeRasterToken({ tile_url: '/tiles/dem/{z}/{x}/{y}.png' })],
    ]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    const addLayerCall = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(addLayerCall.type).toBe('hillshade');
    expect(mockSyncColorReliefLayer).toHaveBeenCalledWith(
      map,
      expect.objectContaining({
        style_config: expect.objectContaining({ render_mode: 'hillshade' }),
      }),
    );
  });

  it('normalizes missing DEM render mode to hillshade before rendering', () => {
    const layer = makeDEMLayer({ style_config: null });
    const tokenMap = new Map<string, TileToken>([
      ['dem-ds-1', makeRasterToken({ tile_url: '/tiles/dem/{z}/{x}/{y}.png' })],
    ]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    const addLayerCall = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(addLayerCall.type).toBe('hillshade');
  });

  it('Test F: a hillshade DEM with no terrain binding runs the normal hillshade path', () => {
    const layer = makeDEMLayer();
    const tokenMap = new Map<string, TileToken>([
      ['dem-ds-1', makeRasterToken({ tile_url: '/tiles/dem/{z}/{x}/{y}.png' })],
    ]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    // Normal hillshade path runs: addSource should be called
    expect((map.addSource as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(0);
  });

  // fix(HT-07): raster/hillshade layers now reapply their saved custom zoom
  // range on (re)sync — previously only vector paths called syncLayerZoomRange,
  // so a saved _minzoom/_maxzoom silently stopped applying after reload.
  it('applies the saved custom zoom range to the hillshade layer', () => {
    const layer = makeDEMLayer({ layout: { _minzoom: 8, _maxzoom: 15 } });
    const tokenMap = new Map<string, TileToken>([
      ['dem-ds-1', makeRasterToken({ tile_url: '/tiles/dem/{z}/{x}/{y}.png' })],
    ]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.setLayerZoomRange as ReturnType<typeof vi.fn>).toHaveBeenCalledWith('layer-dem-layer-1', 8, 15);
  });

  // codex(#451): a raster/DEM layer with NO saved custom range must NOT be
  // force-capped — leave maplibre's default (uncapped) so it doesn't blink off
  // at the max zoom stop.
  it('does not touch the zoom range when no custom _minzoom/_maxzoom is saved', () => {
    const layer = makeDEMLayer({ layout: {} });
    const tokenMap = new Map<string, TileToken>([
      ['dem-ds-1', makeRasterToken({ tile_url: '/tiles/dem/{z}/{x}/{y}.png' })],
    ]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef, { current: '' });

    expect(map.setLayerZoomRange as ReturnType<typeof vi.fn>).not.toHaveBeenCalled();
  });
});
