import { beforeEach, describe, expect, it, vi } from 'vitest';
import { syncLayersToMap } from '../map-sync';
import type { SyncLayerInput } from '../map-sync';
import type { TileToken } from '@/api/tiles';
import { buildClusterTileUrl, buildSignedTileUrl } from '@/lib/tile-utils';
import { linkMapLayers } from '@/components/viewer/linked-filters';
import type { SharedLayerResponse } from '@/types/api';

vi.mock('@/lib/tile-utils', () => ({
  getMvtSourceLayerName: (table: string) => `data.${table}`,
  buildSignedTileUrl: vi.fn(() => '/tiles/mock/{z}/{x}/{y}.pbf'),
  buildClusterTileUrl: vi.fn(() => '/tiles/clusters/mock/{z}/{x}/{y}.pbf?cluster_radius=64&cluster_max_zoom=12'),
}));

/** A layer as the fake map holds it: its id, and the type and source MapLibre reports. */
interface FakeLayer { id: string; type?: string; source?: string }

function makeMockMap(initial?: {
  sources?: Record<string, { type: string }>;
  layers?: FakeLayer[];
}) {
  const sources = new Map<string, { type: string; setData?: ReturnType<typeof vi.fn> }>(
    Object.entries(initial?.sources ?? {}).map(([id, source]) => [
      id,
      { ...source, setData: vi.fn() },
    ]),
  );
  const layers = new Map<string, FakeLayer>((initial?.layers ?? []).map((layer) => [layer.id, layer]));

  return {
    getSource: vi.fn((id: string) => sources.get(id) ?? null),
    addSource: vi.fn((id: string, spec: { type: string }) => {
      sources.set(id, { ...spec, setData: vi.fn() });
    }),
    removeSource: vi.fn((id: string) => {
      sources.delete(id);
    }),
    addLayer: vi.fn((layer: FakeLayer) => {
      layers.set(layer.id, { id: layer.id, type: layer.type, source: layer.source });
    }),
    getLayer: vi.fn((id: string) => layers.get(id) ?? null),
    removeLayer: vi.fn((id: string) => {
      layers.delete(id);
    }),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getPaintProperty: vi.fn(),
    getFilter: vi.fn().mockReturnValue(null),
    setFilter: vi.fn(),
    setLayerZoomRange: vi.fn(),
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({ layers: Array.from(layers.values()) })),
    moveLayer: vi.fn(),
  } as unknown as import('maplibre-gl').Map;
}

/**
 * The cluster tile URLs a source was built with. The filter decision also
 * builds one with a stand-in token to measure it, which this leaves out.
 */
const sourceBuilds = () => vi.mocked(buildClusterTileUrl).mock.calls.filter(([, token]) => token === VECTOR_TOKEN);

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
  expires_in: 3600, tile_url_template: '',
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
  beforeEach(() => {
    vi.mocked(buildClusterTileUrl).mockClear();
  });

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

    expect(buildClusterTileUrl).toHaveBeenCalledWith('points', VECTOR_TOKEN, `${window.location.origin}/api`, undefined, {
      clusterRadius: 64,
      clusterMaxZoom: 12,
    }, []);
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

  // Server-cluster sources forward the data-driven / popup columns
  // as cols= so UNCLUSTERED features (past cluster max zoom) keep the
  // attributes their categorical paint and popups reference.
  it('sends the layer filter to the server-cluster tile URL as CQL2', () => {
    const map = makeMockMap();
    const layer = makeLayer({
      feature_count: 20_000,
      filter: ['==', ['get', 'kind'], 'a'] as SyncLayerInput['filter'],
    });

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    expect(buildClusterTileUrl).toHaveBeenLastCalledWith(
      'points',
      VECTOR_TOKEN,
      expect.any(String),
      undefined,
      expect.objectContaining({ filter: JSON.stringify({ op: '=', args: [{ property: 'kind' }, 'a'] }) }),
      ['kind'],
    );
  });

  it('keeps the saved filter and a dashboard pick of a value and no value in the server-cluster filter', () => {
    const map = makeMockMap();
    const saved = ['any', ['==', ['get', 'zone'], 'A'], ['==', ['get', 'zone'], 'B']];
    const [linked] = linkMapLayers(
      [{ id: 'cluster-1', filter: saved, column_info: [{ name: 'zone', type: 'text' }, { name: 'kind', type: 'text' }] } as SharedLayerResponse],
      [{
        widgetId: 'w1',
        layerId: 'cluster-1',
        selection: { column: 'kind', label: 'park, (no value)', values: ['park', null] },
        cql2: { op: 'in', args: [] },
      }],
    );
    const layer = makeLayer({ feature_count: 20_000, filter: linked.filter as SyncLayerInput['filter'] });

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    const property = (name: string) => ({ property: name });
    expect(JSON.parse(sourceBuilds()[0][4]!.filter!)).toEqual({
      op: 'and',
      args: [
        { op: 'or', args: [{ op: '=', args: [property('zone'), 'A'] }, { op: '=', args: [property('zone'), 'B'] }] },
        { op: 'or', args: [{ op: 'in', args: [property('kind'), ['park']] }, { op: 'isNull', args: [property('kind')] }] },
      ],
    });
  });

  it('leaves a nested filter off the server-cluster URL when a nested property is outside the tile allowlist', () => {
    const map = makeMockMap();
    const layer = makeLayer({
      feature_count: 20_000,
      filter: ['all', ['==', ['get', 'pop'], 5], ['any', ['has', 'other'], ['has', 'pop']]] as unknown as SyncLayerInput['filter'],
      dataset_tile_columns: ['pop'],
    });

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    expect(sourceBuilds()[0][4]?.filter).toBeUndefined();
  });

  describe.each([
    ['absent allowlist', undefined, true],
    ['null allowlist', null, true],
    ['included property', ['pop'], true],
    ['excluded property', ['other'], false],
    ['empty allowlist', [], false],
  ] as const)('server filter with %s', (_label, tileColumns, exposed) => {
    it.each([
      ['known integer mismatch', [{ name: 'pop', type: 'integer' }], '5', false],
      ['unlisted column mismatch', [{ name: 'other', type: 'integer' }], '5', true],
      ['valid integer', [{ name: 'pop', type: 'integer' }], 5, true],
    ] as const)('%s', (_case, columns, value, compatible) => {
      const map = makeMockMap();
      const metadata = { dataset_tile_columns: tileColumns == null ? tileColumns : [...tileColumns] };
      const layer = makeLayer({
        feature_count: 20_000,
        filter: ['==', ['get', 'pop'], value] as SyncLayerInput['filter'],
        dataset_column_info: [...columns],
        ...metadata,
      });

      syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

      expect(sourceBuilds()).toHaveLength(1);
      expect(sourceBuilds()[0][4]?.filter).toBe(
        exposed && compatible ? JSON.stringify({ op: '=', args: [{ property: 'pop' }, value] }) : undefined,
      );
      expect(map.addSource).toHaveBeenCalledWith('source-cluster-1', expect.objectContaining({
        type: 'vector',
        tiles: ['/tiles/clusters/mock/{z}/{x}/{y}.pbf?cluster_radius=64&cluster_max_zoom=12'],
      }));
    });
  });

  describe.each(['get', 'to-number'] as const)('numeric cluster filter through %s', (accessor) => {
    it.each([
      ['smallint minimum', 'smallint', -32768, true],
      ['smallint maximum', 'smallint', 32767, true],
      ['below smallint minimum', 'smallint', -32769, false],
      ['above smallint maximum', 'smallint', 32768, false],
      ['integer minimum', 'integer', -2147483648, true],
      ['integer maximum', 'integer', 2147483647, true],
      ['below integer minimum', 'integer', -2147483649, false],
      ['above integer maximum', 'integer', 2147483648, false],
      ['bigint safe minimum', 'bigint', -9007199254740991, true],
      ['bigint safe maximum', 'bigint', 9007199254740991, true],
      ['below bigint safe minimum', 'bigint', -9007199254740992, false],
      ['above bigint safe maximum', 'bigint', 9007199254740992, false],
      ['bigint PostgreSQL minimum', 'bigint', Number(-9223372036854775808n), false],
      ['bigint PostgreSQL maximum', 'bigint', Number(9223372036854775807n), false],
      ['below bigint PostgreSQL minimum', 'bigint', Number(-9223372036854775809n), false],
      ['above bigint PostgreSQL maximum', 'bigint', Number(9223372036854775808n), false],
      ['real minimum', 'real', -3.4028234663852886e38, true],
      ['real maximum', 'real', 3.4028234663852886e38, true],
      ['negative real overflow', 'real', -1e100, false],
      ['positive real overflow', 'real', 1e100, false],
      ['unbounded numeric', 'numeric', 1e100, true],
      ['unbounded double precision', 'double precision', 1e100, true],
      ['unlisted numeric type', undefined, 1e100, true],
    ] as const)('%s', (_label, type, value, compatible) => {
      const map = makeMockMap();
      const layer = makeLayer({
        feature_count: 20_000,
        filter: ['==', accessor === 'get' ? ['get', 'pop'] : ['to-number', ['get', 'pop'], 0], value] as SyncLayerInput['filter'],
        dataset_column_info: type ? [{ name: 'pop', type }] : [],
        dataset_tile_columns: ['pop'],
      });

      syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

      expect(sourceBuilds()).toHaveLength(1);
      expect(sourceBuilds()[0][4]?.filter).toBe(
        compatible ? JSON.stringify({ op: '=', args: [{ property: 'pop' }, value] }) : undefined,
      );
      expect(map.addSource).toHaveBeenCalledWith('source-cluster-1', expect.objectContaining({
        type: 'vector',
        tiles: ['/tiles/clusters/mock/{z}/{x}/{y}.pbf?cluster_radius=64&cluster_max_zoom=12'],
      }));
    });
  });

  describe.each(['in', 'not-in'] as const)('numeric cluster %s list', (operator) => {
    it.each([
      ['all members in range', [5, 32767], true],
      ['one member out of range', [5, 32768], false],
    ] as const)('%s', (_label, values, compatible) => {
      const map = makeMockMap();
      const membership = ['in', ['get', 'pop'], ['literal', [...values]]];
      const layer = makeLayer({
        feature_count: 20_000,
        filter: (operator === 'in' ? membership : ['!', membership]) as unknown as SyncLayerInput['filter'],
        dataset_column_info: [{ name: 'pop', type: 'smallint' }],
        dataset_tile_columns: ['pop'],
      });

      syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

      expect(sourceBuilds()).toHaveLength(1);
      const filter = sourceBuilds()[0][4]?.filter;
      if (compatible) expect(filter).toBeDefined();
      else expect(filter).toBeUndefined();
      expect(map.addSource).toHaveBeenCalledWith('source-cluster-1', expect.objectContaining({
        type: 'vector',
        tiles: ['/tiles/clusters/mock/{z}/{x}/{y}.pbf?cluster_radius=64&cluster_max_zoom=12'],
      }));
    });
  });

  it.each([
    ['text', 5, false],
    ['integer', '5', false],
    ['integer', 5.5, false],
    ['numeric', '5', false],
    ['boolean', 'true', false],
    ['text', '5', true],
    ['integer', 5, true],
    ['numeric', 5.5, true],
    ['boolean', true, true],
    ['uuid', '6f1c3a52-2b8e-4f0e-9a51-3d6a8f9c0b11', true],
    ['timestamp without time zone', '2024-01-01 12:00:00', true],
    ['timestamp with time zone', '2024-01-01T12:00:00+00:00', true],
  ] as const)('checks a %s literal %j before sending the server filter', (type, value, compatible) => {
    const map = makeMockMap();
    const layer = makeLayer({
      feature_count: 20_000,
      filter: ['==', ['get', 'value'], value] as SyncLayerInput['filter'],
      dataset_column_info: [{ name: 'value', type }],
    });

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    expect(sourceBuilds()).toHaveLength(1);
    const filter = sourceBuilds()[0][4]?.filter;
    if (compatible) expect(filter).toBeDefined();
    else expect(filter).toBeUndefined();
  });

  describe.each([
    ['absent allowlist', undefined, true],
    ['null allowlist', null, true],
    ['included property', ['score'], true],
    ['excluded property', ['other'], false],
    ['empty allowlist', [], false],
  ] as const)('to-number server filter with %s', (_label, tileColumns, exposed) => {
    it.each([
      ['text', false],
      ['integer', true],
      [undefined, true],
    ] as const)('checks to-number against column type %s', (type, compatible) => {
      const map = makeMockMap();
      const metadata = { dataset_tile_columns: tileColumns == null ? tileColumns : [...tileColumns] };
      const layer = makeLayer({
        feature_count: 20_000,
        filter: ['>=', ['to-number', ['get', 'score'], 0], 5] as SyncLayerInput['filter'],
        dataset_column_info: type ? [{ name: 'score', type }] : [],
        ...metadata,
      });

      syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

      expect(sourceBuilds()).toHaveLength(1);
      expect(sourceBuilds()[0][4]?.filter).toBe(
        exposed && compatible ? JSON.stringify({ op: '>=', args: [{ property: 'score' }, 5] }) : undefined,
      );
    });
  });

  it('keeps the layer filter on loose points when the server filter is omitted', () => {
    const map = makeMockMap();
    const layer = makeLayer({
      feature_count: 20_000,
      filter: ['==', ['get', 'pop'], '5'] as SyncLayerInput['filter'],
      dataset_column_info: [{ name: 'pop', type: 'integer' }],
    });

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    expect(sourceBuilds()).toHaveLength(1);
    expect(sourceBuilds()[0][4]?.filter).toBeUndefined();
    expect(map.setFilter).toHaveBeenCalledWith(
      'layer-cluster-1',
      ['all', ['!', ['has', 'point_count']], layer.filter],
    );
  });

  it.each([
    ['existence', ['has', 'pop']],
    ['null comparison', ['==', ['get', 'pop'], null]],
    ['membership', ['in', ['get', 'pop'], ['literal', [5, 6]]]],
    ['negative membership', ['!', ['in', ['get', 'pop'], ['literal', [5, 6]]]]],
    ['any combination', ['any', ['==', ['get', 'pop'], 5], ['has', 'pop']]],
  ])('sends a valid %s filter on an exposed known column', (_label, filter) => {
    const map = makeMockMap();
    const layer = makeLayer({
      feature_count: 20_000,
      filter: filter as unknown as SyncLayerInput['filter'],
      dataset_column_info: [{ name: 'pop', type: 'INTEGER' }],
      dataset_tile_columns: ['pop'],
    });

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    expect(sourceBuilds()).toHaveLength(1);
    expect(sourceBuilds()[0][4]?.filter).toBeDefined();
  });

  it.each(['in', 'not-in'] as const)('omits the whole server filter for a mismatched %s list entry', (operator) => {
    const map = makeMockMap();
    const membership = ['in', ['get', 'pop'], ['literal', [5, '6']]];
    const layer = makeLayer({
      feature_count: 20_000,
      filter: ['all', ['has', 'kind'], operator === 'in' ? membership : ['!', membership]] as unknown as SyncLayerInput['filter'],
      dataset_column_info: [{ name: 'pop', type: 'integer' }],
    });

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    expect(sourceBuilds()).toHaveLength(1);
    expect(sourceBuilds()[0][4]?.filter).toBeUndefined();
  });

  it.each([
    ['has', 'pop'],
    ['==', ['get', 'pop'], null],
    ['all', ['has', 'kind'], ['==', ['get', 'pop'], 5]],
  ])('omits server filters reading an excluded property: %j', (...filter) => {
    const map = makeMockMap();
    const metadata = { dataset_tile_columns: ['kind'] };
    const layer = makeLayer({ feature_count: 20_000, filter: filter as SyncLayerInput['filter'], ...metadata });

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    expect(sourceBuilds()).toHaveLength(1);
    expect(sourceBuilds()[0][4]?.filter).toBeUndefined();
  });

  it('types temporal literals in the server-cluster filter from the layer column types', () => {
    const map = makeMockMap();
    const layer = makeLayer({
      feature_count: 20_000,
      filter: ['>=', ['get', 'seen'], '2004-01-01'] as SyncLayerInput['filter'],
      dataset_column_info: [{ name: 'seen', type: 'date' }],
    });

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    expect(sourceBuilds()).toHaveLength(1);
    const options = sourceBuilds()[0][4];
    expect(JSON.parse(options?.filter ?? 'null')).toEqual({
      op: '>=',
      args: [{ property: 'seen' }, { date: '2004-01-01' }],
    });
  });

  it('leaves a filter off the server-cluster URL when it exceeds the route limits', () => {
    const map = makeMockMap();
    const many = Array.from({ length: 150 }, (_, i) => `a-value-that-is-long-${i}-xxxxxxxxxxxx`);
    const layer = makeLayer({
      feature_count: 20_000,
      filter: ['in', ['get', 'kind'], ...many] as unknown as SyncLayerInput['filter'],
    });

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    expect(sourceBuilds()).toHaveLength(1);
    expect(sourceBuilds()[0][4]?.filter).toBeUndefined();
  });

  it('drops points with a missing value for a less-than comparison, as the layer filter does', () => {
    const map = makeMockMap();
    const layer = makeLayer({
      feature_count: 20_000,
      filter: ['<', ['get', 'score'], 5] as SyncLayerInput['filter'],
    });

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    // The layer's sanitized filter gives a missing value a high fallback, so it fails `<`.
    expect(sourceBuilds()).toHaveLength(1);
    expect(JSON.parse(sourceBuilds()[0][4]?.filter ?? 'null')).toEqual({
      op: '<',
      args: [{ property: 'score' }, 5],
    });
  });

  it('forwards data-driven columns to the server-cluster tile URL', () => {
    const map = makeMockMap();
    const layer = makeLayer({
      feature_count: 20_000,
      paint: {
        'circle-color': ['match', ['get', 'fall'], 'Fell', '#f59e0b', '#94a3b8'],
        'circle-radius': ['step', ['to-number', ['get', 'mass_kg'], 0], 3, 1, 5],
      },
      style_config: {
        render_mode: 'cluster',
        mode: 'categorical',
        column: 'fall',
      } as SyncLayerInput['style_config'],
    });

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' });

    expect(buildClusterTileUrl).toHaveBeenCalledWith(
      'points',
      VECTOR_TOKEN,
      `${window.location.origin}/api`,
      undefined,
      expect.any(Object),
      expect.arrayContaining(['fall', 'mass_kg']),
    );
  });

  it('replaces an existing vector source when bounded cluster data arrives', () => {
    const map = makeMockMap({
      sources: { 'source-cluster-1': { type: 'vector' } },
      layers: [{ id: 'layer-cluster-1', type: 'circle', source: 'source-cluster-1' }],
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

  it('filters the clustered source itself and rebuilds it when the layer filter changes', () => {
    const map = makeMockMap();
    const open = ['==', ['get', 'status'], 'open'];
    const layer = makeLayer({ filter: open as SyncLayerInput['filter'] });
    const geojsonData = new Map<string, GeoJSON.FeatureCollection>([[layer.id, featureCollection]]);
    const sync = (next: SyncLayerInput, known: string[]) => syncLayersToMap(
      map, [next], tokenMap(next), undefined, { current: new Set(known) }, { current: '' }, geojsonData,
    );

    sync(layer, []);
    expect(map.addSource).toHaveBeenLastCalledWith('source-cluster-1', expect.objectContaining({ cluster: true, filter: open }));

    (map.removeSource as ReturnType<typeof vi.fn>).mockClear();
    const closed = ['==', ['get', 'status'], 'closed'];
    sync(makeLayer({ filter: closed as SyncLayerInput['filter'] }), ['source-cluster-1']);
    expect(map.removeSource).toHaveBeenCalledWith('source-cluster-1');
    expect(map.addSource).toHaveBeenLastCalledWith('source-cluster-1', expect.objectContaining({ filter: closed }));

    (map.removeSource as ReturnType<typeof vi.fn>).mockClear();
    sync(makeLayer({ filter: [] as unknown as SyncLayerInput['filter'] }), ['source-cluster-1']);
    expect(map.removeSource).toHaveBeenCalledWith('source-cluster-1');
    expect(map.addSource).toHaveBeenLastCalledWith(
      'source-cluster-1',
      expect.not.objectContaining({ filter: expect.anything() }),
    );
  });

  it('removes another layer drawing from the clustered source before rebuilding it', () => {
    const map = makeMockMap();
    const layer = makeLayer({ filter: ['==', ['get', 'status'], 'open'] as SyncLayerInput['filter'] });
    const geojsonData = new Map<string, GeoJSON.FeatureCollection>([[layer.id, featureCollection]]);
    const sync = (next: SyncLayerInput, known: string[]) => syncLayersToMap(
      map, [next], tokenMap(next), undefined, { current: new Set(known) }, { current: '' }, geojsonData,
    );
    sync(layer, []);
    // A feature highlight paints from the layer's own source.
    map.addLayer({ id: 'feature-highlight-line', type: 'line', source: 'source-cluster-1' });
    // MapLibre refuses to remove a source a layer still uses.
    const removeSource = vi.mocked(map.removeSource).getMockImplementation()!;
    vi.mocked(map.removeSource).mockImplementation((id: string) => {
      const inUse = map.getStyle().layers.some((l) => 'source' in l && l.source === id);
      if (inUse) throw new Error(`Source "${id}" cannot be removed while a layer uses it`);
      return removeSource(id);
    });

    const closed = ['==', ['get', 'status'], 'closed'];
    sync(makeLayer({ filter: closed as SyncLayerInput['filter'] }), ['source-cluster-1']);

    expect(map.getLayer('feature-highlight-line')).toBeNull();
    expect(map.addSource).toHaveBeenLastCalledWith('source-cluster-1', expect.objectContaining({ filter: closed }));
  });

  it('hands the clustered source an expression filter when the layer filter is a legacy one', () => {
    const map = makeMockMap();
    const layer = makeLayer({ filter: ['==', 'status', 'open'] as SyncLayerInput['filter'] });
    const geojsonData = new Map<string, GeoJSON.FeatureCollection>([[layer.id, featureCollection]]);

    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' }, geojsonData);

    expect(map.addSource).toHaveBeenLastCalledWith(
      'source-cluster-1',
      expect.objectContaining({ filter: ['==', ['get', 'status'], 'open'] }),
    );
  });

  it('keeps zoom-dependent filters off the clustered source and matches nothing for a legacy filter that converts to false', () => {
    const sourceFor = (filter: unknown) => {
      const map = makeMockMap();
      const layer = makeLayer({ filter: filter as SyncLayerInput['filter'] });
      const geojsonData = new Map<string, GeoJSON.FeatureCollection>([[layer.id, featureCollection]]);
      syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' }, geojsonData);
      return (map.addSource as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[1] as Record<string, unknown>;
    };

    expect(sourceFor(['>=', ['zoom'], 8])).not.toHaveProperty('filter');
    expect(sourceFor(['==', ['global-state', 'k'], 1])).not.toHaveProperty('filter');
    expect(sourceFor(['is-supported-script', ['get', 'name']])).not.toHaveProperty('filter');
    expect(sourceFor(['within', { type: 'Polygon', coordinates: [] }])).not.toHaveProperty('filter');
    expect(sourceFor(['in', ['get', 'kind'], ['literal', ['zoom', 'other']]])).toHaveProperty('filter');
    expect(sourceFor(['==', ['geometry-type'], 'Point'])).not.toHaveProperty('filter');
    expect(sourceFor(['==', '$type', 'Point'])).not.toHaveProperty('filter');
    expect(sourceFor(['match', ['get', 'kind'], ['zoom', 'other'], true, false])).toHaveProperty('filter');
    expect(sourceFor(['==', ['number-format', 1, { 'max-fraction-digits': ['zoom'] }], '1'])).not.toHaveProperty('filter');
    expect(sourceFor(['in', 'x'])).toHaveProperty('filter', ['==', 0, 1]);
  });

  it('keeps a bounded cluster source when its tile token rotates', () => {
    vi.mocked(buildSignedTileUrl).mockImplementation(
      (table: string, token: { sig: string } | null) => `/tiles/${table}/{z}/{x}/{y}.pbf?sig=${token?.sig ?? ''}`,
    );
    const map = makeMockMap();
    const layer = makeLayer();
    const geojsonData = new Map<string, GeoJSON.FeatureCollection>([[layer.id, featureCollection]]);
    syncLayersToMap(map, [layer], tokenMap(layer), undefined, { current: new Set() }, { current: '' }, geojsonData);

    const rotated = new Map<string, TileToken>([[layer.dataset_id, { ...VECTOR_TOKEN, sig: 'rotated' }]]);
    syncLayersToMap(map, [layer], rotated, undefined, { current: new Set(['source-cluster-1']) }, { current: '' }, geojsonData);

    vi.mocked(buildSignedTileUrl).mockImplementation(() => '/tiles/mock/{z}/{x}/{y}.pbf');
    expect(map.removeSource).not.toHaveBeenCalled();
    expect(map.addSource).toHaveBeenCalledTimes(1);
  });

  it('removes stale cluster companion layers before removing the source', () => {
    const map = makeMockMap({
      sources: { 'source-old': { type: 'geojson' } },
      layers: [
        { id: 'layer-old', type: 'circle', source: 'source-old' },
        { id: 'layer-old-cluster', type: 'circle', source: 'source-old' },
        { id: 'layer-old-cluster-count', type: 'symbol', source: 'source-old' },
      ],
    });

    syncLayersToMap(map, [], new Map(), undefined, { current: new Set(['source-old']) }, { current: '' });

    expect(map.removeLayer).toHaveBeenCalledWith('layer-old-cluster-count');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-old-cluster');
    expect(map.removeLayer).toHaveBeenCalledWith('layer-old');
    expect(map.removeSource).toHaveBeenCalledWith('source-old');
  });
});
