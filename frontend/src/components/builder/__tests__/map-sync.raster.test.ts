import { describe, it, expect, vi, beforeEach } from 'vitest';
import { syncLayersToMap } from '@/components/builder/map-sync';
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

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef);

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

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef);

    const addLayerCall = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(addLayerCall.paint['raster-opacity']).toBe(0.6);
  });

  it('hidden raster layer sets visibility none', () => {
    const layer = makeLayer({
      id: 'r3',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      visible: false,
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeRasterToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef);

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-r3', 'visibility', 'none');
  });

  it('vector layer adds vector source and fill layer for Polygon', () => {
    const layer = makeLayer({
      id: 'v1',
      layer_type: 'vector_geolens',
      dataset_geometry_type: 'Polygon',
    });
    const tokenMap = new Map<string, TileToken>([['ds-1', makeVectorToken()]]);

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef);

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

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef);

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

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef);

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

    syncLayersToMap(map, [], new Map(), undefined, managedSourcesRef);

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

    syncLayersToMap(map, [layer], tokenMap, undefined, managedSourcesRef);

    expect(map.addSource).not.toHaveBeenCalled();
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-r4', 'raster-opacity', 0.7);
  });
});
