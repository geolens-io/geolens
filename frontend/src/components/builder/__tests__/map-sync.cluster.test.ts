import { describe, expect, it, vi } from 'vitest';
import { syncLayersToMap } from '../map-sync';
import type { SyncLayerInput } from '../map-sync';
import type { TileToken } from '@/api/tiles';

vi.mock('@/lib/tile-utils', () => ({
  buildSignedTileUrl: vi.fn(() => '/tiles/mock/{z}/{x}/{y}.pbf'),
  buildClusterTileUrl: vi.fn(() => '/tiles/clusters/mock/{z}/{x}/{y}.pbf?cluster_radius=64&cluster_max_zoom=12'),
}));

function makeMockMap(initial?: {
  sources?: Record<string, { type: string }>;
  layers?: string[];
}) {
  const sources = new Map<string, { type: string; setData?: ReturnType<typeof vi.fn> }>(
    Object.entries(initial?.sources ?? {}).map(([id, source]) => [
      id,
      { ...source, setData: vi.fn() },
    ]),
  );
  const layerIds = new Set<string>(initial?.layers ?? []);

  return {
    getSource: vi.fn((id: string) => sources.get(id) ?? null),
    addSource: vi.fn((id: string, spec: { type: string }) => {
      sources.set(id, { ...spec, setData: vi.fn() });
    }),
    removeSource: vi.fn((id: string) => {
      sources.delete(id);
    }),
    addLayer: vi.fn((layer: { id: string }) => {
      layerIds.add(layer.id);
    }),
    getLayer: vi.fn((id: string) => layerIds.has(id) ? { id } : null),
    removeLayer: vi.fn((id: string) => {
      layerIds.delete(id);
    }),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getPaintProperty: vi.fn(),
    getFilter: vi.fn().mockReturnValue(null),
    setFilter: vi.fn(),
    setLayerZoomRange: vi.fn(),
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({ layers: Array.from(layerIds).map((id) => ({ id })) })),
    moveLayer: vi.fn(),
  } as unknown as import('maplibre-gl').Map;
}

function makeLayer(overrides: Partial<SyncLayerInput> = {}): SyncLayerInput {
  return {
    id: 'cluster-1',
    dataset_id: 'ds-1',
    dataset_table_name: 'points',
    dataset_geometry_type: 'POINT',
    opacity: 1,
    visible: true,
    paint: { 'circle-color': '#2255aa', 'circle-radius': 6 },
    layout: {},
    filter: null,
    label_config: null,
    style_config: { render_mode: 'cluster' } as SyncLayerInput['style_config'],
    is_dem: false,
    is_3d: false,
    feature_count: 100,
    ...overrides,
  };
}

const VECTOR_TOKEN: TileToken = {
  kind: 'vector',
  sig: 'mock',
  exp: 9999999999,
  scope: 'test',
  expires_in: 3600,
};

const featureCollection: GeoJSON.FeatureCollection = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [0, 0] },
      properties: { status: 'open' },
    },
  ],
};

function tokenMap(layer: SyncLayerInput) {
  return new Map<string, TileToken>([[layer.dataset_id, VECTOR_TOKEN]]);
}

describe('syncLayersToMap cluster rendering', () => {
  it('creates a clustered GeoJSON source and stable cluster companion layers when bounded data exists', () => {
    const map = makeMockMap();
    const layer = makeLayer({
      layout: { _minzoom: 5, _maxzoom: 15 },
      style_config: {
        render_mode: 'cluster',
        builder: {
          clusterRadius: 64,
          clusterMaxZoom: 12,
          clusterColor: '#fb923c',
          clusterTextColor: '#111827',
        },
      } as SyncLayerInput['style_config'],
    });
    const geojsonData = new Map<string, GeoJSON.FeatureCollection>([[layer.id, featureCollection]]);

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' }, geojsonData);

    expect(map.addSource).toHaveBeenCalledWith('source-cluster-1', {
      type: 'geojson',
      data: featureCollection,
      cluster: true,
      clusterRadius: 64,
      clusterMaxZoom: 12,
    });
    const layerIds = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls.map((call) => call[0].id);
    expect(layerIds).toEqual([
      'layer-cluster-1-cluster',
      'layer-cluster-1-cluster-count',
      'layer-cluster-1',
    ]);
    expect(map.setLayerZoomRange).toHaveBeenCalledWith('layer-cluster-1-cluster', 5, 15);
    expect(map.setLayerZoomRange).toHaveBeenCalledWith('layer-cluster-1-cluster-count', 5, 15);
    expect(map.setLayerZoomRange).toHaveBeenCalledWith('layer-cluster-1', 5, 15);
  });

  it('falls back to the normal vector circle renderer when cluster data is unavailable', () => {
    const map = makeMockMap();
    const layer = makeLayer();

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    expect(map.addSource).toHaveBeenCalledWith('source-cluster-1', expect.objectContaining({
      type: 'vector',
      tiles: ['/tiles/mock/{z}/{x}/{y}.pbf'],
    }));
    const sourceSpec = (map.addSource as ReturnType<typeof vi.fn>).mock.calls[0][1] as Record<string, unknown>;
    expect(sourceSpec).not.toHaveProperty('cluster');
    const layerIds = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls.map((call) => call[0].id);
    expect(layerIds).toEqual(['layer-cluster-1']);
  });

  it('routes large cluster layers to server-side cluster vector tiles', () => {
    const map = makeMockMap();
    const layer = makeLayer({
      feature_count: 20_000,
      style_config: {
        render_mode: 'cluster',
        builder: {
          clusterRadius: 64,
          clusterMaxZoom: 12,
          clusterColor: '#fb923c',
        },
      } as SyncLayerInput['style_config'],
    });

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    expect(map.addSource).toHaveBeenCalledWith('source-cluster-1', expect.objectContaining({
      type: 'vector',
      tiles: ['/tiles/clusters/mock/{z}/{x}/{y}.pbf?cluster_radius=64&cluster_max_zoom=12'],
    }));
    const layerSpecs = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls.map((call) => call[0]);
    expect(layerSpecs.map((spec) => spec.id)).toEqual([
      'layer-cluster-1-cluster',
      'layer-cluster-1-cluster-count',
      'layer-cluster-1',
    ]);
    expect(layerSpecs.every((spec) => spec['source-layer'] === 'data.points')).toBe(true);
  });

  it('replaces an existing vector source when bounded cluster data arrives', () => {
    const map = makeMockMap({
      sources: { 'source-cluster-1': { type: 'vector' } },
      layers: ['layer-cluster-1'],
    });
    const layer = makeLayer();
    const geojsonData = new Map<string, GeoJSON.FeatureCollection>([[layer.id, featureCollection]]);

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set(['source-cluster-1']) }, { current: '' }, geojsonData);

    expect(map.removeLayer).toHaveBeenCalledWith('layer-cluster-1');
    expect(map.removeSource).toHaveBeenCalledWith('source-cluster-1');
    expect(map.addSource).toHaveBeenCalledWith('source-cluster-1', expect.objectContaining({
      type: 'geojson',
      cluster: true,
    }));
  });

  it('reorders cluster companion layers with data geometry', () => {
    const map = makeMockMap();
    const layer = makeLayer();
    const geojsonData = new Map<string, GeoJSON.FeatureCollection>([[layer.id, featureCollection]]);

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' }, geojsonData);

    expect(map.moveLayer).toHaveBeenCalledWith('layer-cluster-1-cluster');
    expect(map.moveLayer).toHaveBeenCalledWith('layer-cluster-1-cluster-count');
    expect(map.moveLayer).toHaveBeenCalledWith('layer-cluster-1');
  });

  it('rebuilds the clustered source when source-level cluster options change', () => {
    const map = makeMockMap();
    const layer = makeLayer({
      style_config: {
        render_mode: 'cluster',
        builder: { clusterRadius: 48, clusterMaxZoom: 14 },
      } as SyncLayerInput['style_config'],
    });
    const geojsonData = new Map<string, GeoJSON.FeatureCollection>([[layer.id, featureCollection]]);

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' }, geojsonData);
    (map.removeSource as ReturnType<typeof vi.fn>).mockClear();
    (map.removeLayer as ReturnType<typeof vi.fn>).mockClear();
    (map.addSource as ReturnType<typeof vi.fn>).mockClear();

    syncLayersToMap(
      map,
      [
        makeLayer({
          style_config: {
            render_mode: 'cluster',
            builder: { clusterRadius: 80, clusterMaxZoom: 12 },
          } as SyncLayerInput['style_config'],
        }),
      ],
      tokenMap(layer),
      undefined,
      { current: new Set(['source-cluster-1']) },
      { current: '' },
      geojsonData,
    );

    expect(map.removeLayer).toHaveBeenCalledWith('layer-cluster-1-cluster-count');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-cluster-1-cluster');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-cluster-1');
    expect(map.removeSource).toHaveBeenCalledWith('source-cluster-1');
    expect(map.addSource).toHaveBeenCalledWith('source-cluster-1', {
      type: 'geojson',
      data: featureCollection,
      cluster: true,
      clusterRadius: 80,
      clusterMaxZoom: 12,
    });
  });

  it('removes stale cluster companion layers before removing the source', () => {
    const map = makeMockMap({
      sources: { 'source-old': { type: 'geojson' } },
      layers: ['layer-old', 'layer-old-cluster', 'layer-old-cluster-count'],
    });

    syncLayersToMap(map, [], new Map(), undefined, { current: new Set(['source-old']) }, { current: '' });

    expect(map.removeLayer).toHaveBeenCalledWith('layer-old-cluster-count');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-old-cluster');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-old');
    expect(map.removeSource).toHaveBeenCalledWith('source-old');
  });
});
