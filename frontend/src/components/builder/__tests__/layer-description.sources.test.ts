// describeLayers gives every source the map draws saved layers from, signed and
// bounded, from the layers and the render context alone.
import type { FilterSpecification, SourceSpecification } from 'maplibre-gl';
import type { MapLayerResponse, PopupConfig, StyleConfig } from '@/types/api';
import { SAVED_LAYERS, savedLayer, toSharedLayer } from '@/test/fixtures/saved-layers';
import { FIXTURE_ORIGIN, FIXTURE_TOKENS, RENDER_CONTEXTS, fixtureToken } from '@/test/fixtures/render-contexts';
import { toViewerSyncInput } from '@/components/viewer/ViewerMap';
import { toSyncInput } from '../map-sync';
import { describeLayers, type RenderContext } from '../layer-description';

type Row = [label: string, layers: MapLayerResponse[], context: RenderContext, expected: Record<string, SourceSpecification>];

const API = `${FIXTURE_ORIGIN}/api`;
const FIXTURE_BOUNDS: [number, number, number, number] = [-74.1, 40.6, -73.8, 40.9];
const CREDIT = 'Swiss Federal Office of Topography';
const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

function signature(layer: MapLayerResponse) {
  return `sig=sig-${layer.dataset_id}&exp=2000000000&scope=scope-${layer.dataset_id}`;
}

function vectorUrl(layer: MapLayerResponse, query = signature(layer)) {
  return `${API}/tiles/data.${layer.dataset_table_name}/{z}/{x}/{y}.pbf${query ? `?${query}` : ''}`;
}

function vectorSource(layer: MapLayerResponse, overrides: Record<string, unknown> = {}): SourceSpecification {
  return { type: 'vector', tiles: [vectorUrl(layer)], minzoom: 0, maxzoom: 14, bounds: FIXTURE_BOUNDS, ...overrides } as SourceSpecification;
}

function rasterUrl(layer: MapLayerResponse) {
  return `${FIXTURE_ORIGIN}/raster-tiles/${layer.dataset_id}/tiles/{z}/{x}/{y}.png?${signature(layer)}`;
}

function onTable(base: MapLayerResponse, id: string, overrides: Partial<MapLayerResponse>): MapLayerResponse {
  return savedLayer({
    ...base,
    id,
    paint: {},
    style_config: null,
    ...overrides,
  });
}

const { polygon, categorical, line, serverCluster, boundedCluster, fallbackCluster, raster, hillshadeDem } = SAVED_LAYERS;
const zoningLabels = onTable(categorical, 'layer-zoning-labels', {
  filter: ['>', ['get', 'pop'], 100] as FilterSpecification,
  popup_config: { enabled: true, expression: null, visible_fields: ['owner'] } satisfies PopupConfig,
});
const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
const roadsGradient = onTable(line, 'layer-roads-gradient', { paint: { 'line-gradient': gradient } });
const gradientIntent = { ...line, style_config: { builder: { lineGradient: { stops: [{ position: 0, color: '#00f' }] } } } as unknown as StyleConfig };
const arrayIntent = { ...line, style_config: { builder: { lineGradient: [{ position: 0, color: '#00f' }] } } as unknown as StyleConfig };
const small3d = { ...polygon, is_3d: true, dataset_feature_count: 100 };
const seam = { ...polygon, dataset_extent_bbox: [178.5, -20, -178.5, -15] };
const noExtent = { ...polygon, dataset_extent_bbox: null };
const versioned = { ...polygon, tile_version: 7 };
const colormap = { ...raster, paint: { _colormap: 'viridis' } };
const shadedWithColormap = { ...hillshadeDem, paint: { ...hillshadeDem.paint, _colormap: 'viridis' } };
const credited = { ...polygon, dataset_attribution: CREDIT };
const creditedRaster = { ...raster, dataset_attribution: CREDIT };
const creditedDem = { ...hillshadeDem, dataset_attribution: CREDIT };
const creditedCluster = { ...boundedCluster, dataset_attribution: CREDIT };

const noTokens = { ...RENDER_CONTEXTS.builder, tokens: new Map() };

const rows: Row[] = [
  ['a polygon layer', [polygon], RENDER_CONTEXTS.builder, { 'source-data-parcels': vectorSource(polygon) }],
  [
    'two layers on one table, sharing a source whose cols= covers both',
    [categorical, zoningLabels],
    RENDER_CONTEXTS.builder,
    { 'source-data-zoning': vectorSource(categorical, { tiles: [vectorUrl(categorical, `${signature(categorical)}&cols=owner%2Cpop%2Czone`)] }) },
  ],
  [
    'a line gradient on either layer of a shared source',
    [line, roadsGradient],
    RENDER_CONTEXTS.builder,
    { 'source-data-roads': vectorSource(line, { lineMetrics: true }) },
  ],
  ['a line layer without a gradient', [line], RENDER_CONTEXTS.builder, { 'source-data-roads': vectorSource(line) }],
  ['the builder line-gradient intent', [gradientIntent], RENDER_CONTEXTS.builder, { 'source-data-roads': vectorSource(line, { lineMetrics: true }) }],
  ['an array-shaped line-gradient intent', [arrayIntent], RENDER_CONTEXTS.builder, { 'source-data-roads': vectorSource(line) }],
  [
    'a server cluster',
    [serverCluster],
    RENDER_CONTEXTS.builder,
    {
      'source-layer-street-trees': vectorSource(serverCluster, {
        tiles: [`${API}/tiles/clusters/data.street_trees/{z}/{x}/{y}.pbf?${signature(serverCluster)}&cluster_radius=48&cluster_max_zoom=14`],
        maxzoom: 22,
      }),
    },
  ],
  [
    'a bounded cluster with its GeoJSON',
    [boundedCluster],
    RENDER_CONTEXTS.builderWithClusterData,
    { 'source-layer-bike-racks': { type: 'geojson', data: EMPTY_FC, cluster: true, clusterRadius: 48, clusterMaxZoom: 14 } },
  ],
  ['a bounded cluster before its GeoJSON loads', [boundedCluster], RENDER_CONTEXTS.builder, { 'source-layer-bike-racks': vectorSource(boundedCluster) }],
  ['a cluster without a feature count', [fallbackCluster], RENDER_CONTEXTS.builder, { 'source-data-survey_points': vectorSource(fallbackCluster) }],
  [
    'a small 3D layer with GeoJSON at hand',
    [small3d],
    { ...RENDER_CONTEXTS.builder, boundedGeoJson: new Map([[small3d.id, EMPTY_FC]]) },
    { 'source-data-parcels': vectorSource(small3d) },
  ],
  [
    'a raster layer',
    [raster],
    RENDER_CONTEXTS.builder,
    { 'source-layer-orthophoto': { type: 'raster', tiles: [rasterUrl(raster)], tileSize: 256, minzoom: 0, maxzoom: 19, bounds: FIXTURE_BOUNDS } },
  ],
  [
    'a raster layer with a colormap',
    [colormap],
    RENDER_CONTEXTS.builder,
    {
      'source-layer-orthophoto': {
        type: 'raster',
        tiles: [`${rasterUrl(raster)}&colormap_name=viridis`],
        tileSize: 256,
        minzoom: 0,
        maxzoom: 19,
        bounds: FIXTURE_BOUNDS,
      },
    },
  ],
  [
    'a hillshade DEM, which takes no colormap',
    [shadedWithColormap],
    RENDER_CONTEXTS.builder,
    {
      'source-layer-relief': {
        type: 'raster-dem',
        tiles: [rasterUrl(hillshadeDem)],
        tileSize: 256,
        minzoom: 0,
        maxzoom: 19,
        bounds: FIXTURE_BOUNDS,
        encoding: 'mapbox',
      },
    },
  ],
  ['an antimeridian extent', [seam], RENDER_CONTEXTS.builder, { 'source-data-parcels': vectorSource(seam, { bounds: [-180, -20, 180, -15] }) }],
  ['a layer without an extent', [noExtent], RENDER_CONTEXTS.builder, { 'source-data-parcels': { type: 'vector', tiles: [vectorUrl(noExtent)], minzoom: 0, maxzoom: 14 } }],
  ['a credited vector layer', [credited], RENDER_CONTEXTS.builder, { 'source-data-parcels': vectorSource(credited, { attribution: CREDIT }) }],
  [
    'a credited raster layer',
    [creditedRaster],
    RENDER_CONTEXTS.builder,
    {
      'source-layer-orthophoto': {
        type: 'raster',
        tiles: [rasterUrl(raster)],
        tileSize: 256,
        minzoom: 0,
        maxzoom: 19,
        bounds: FIXTURE_BOUNDS,
        attribution: CREDIT,
      },
    },
  ],
  [
    'a credited hillshade DEM',
    [creditedDem],
    RENDER_CONTEXTS.builder,
    {
      'source-layer-relief': {
        type: 'raster-dem',
        tiles: [rasterUrl(hillshadeDem)],
        tileSize: 256,
        minzoom: 0,
        maxzoom: 19,
        bounds: FIXTURE_BOUNDS,
        attribution: CREDIT,
        encoding: 'mapbox',
      },
    },
  ],
  [
    'a credited bounded cluster',
    [creditedCluster],
    RENDER_CONTEXTS.builderWithClusterData,
    {
      'source-layer-bike-racks': {
        type: 'geojson',
        data: EMPTY_FC,
        cluster: true,
        clusterRadius: 48,
        clusterMaxZoom: 14,
        attribution: CREDIT,
      },
    },
  ],
  ['a vector layer without a token', [polygon], noTokens, { 'source-data-parcels': vectorSource(polygon, { tiles: [vectorUrl(polygon, '')] }) }],
  ['a raster layer without a token or a saved tile URL', [raster], noTokens, {}],
  ['a tile version', [versioned], RENDER_CONTEXTS.builder, { 'source-data-parcels': vectorSource(versioned, { tiles: [vectorUrl(versioned, `${signature(versioned)}&_v=7`)] }) }],
  [
    'a tile base URL',
    [polygon],
    { ...RENDER_CONTEXTS.builder, tileBaseUrl: 'https://tiles.example.test/' },
    {
      'source-data-parcels': vectorSource(polygon, {
        tiles: [`https://tiles.example.test/tiles/data.parcels/{z}/{x}/{y}.pbf?${signature(polygon)}`],
      }),
    },
  ],
  [
    'a tenant prefix, which names MVT layers and not tile paths',
    [polygon],
    { ...RENDER_CONTEXTS.builder, sourceLayerPrefix: 'data_t_1234' },
    { 'source-data-parcels': vectorSource(polygon) },
  ],
];

function viewerInput(layer: MapLayerResponse) {
  return toViewerSyncInput(toSharedLayer(layer), layer.id, new Set([layer.id]));
}

function withoutAttribution(spec: SourceSpecification): SourceSpecification {
  const { attribution: _viewerCreditsInItsControl, ...rest } = spec as SourceSpecification & { attribution?: string };
  return rest as SourceSpecification;
}

describe('describeLayers sources', () => {
  it.each(rows)('describes the sources of %s', (_label, layers, context, expected) => {
    expect(Object.fromEntries(describeLayers(layers.map(toSyncInput), context).sources)).toEqual(expected);
  });

  it('gives the builder and the viewer the same sources apart from the id prefix and attribution', () => {
    const fiji = savedLayer({ id: 'layer-fiji', dataset_id: 'dataset-fiji', dataset_table_name: 'fiji_reefs', dataset_extent_bbox: [178.5, -20, -178.5, -15] });
    const alti = savedLayer({ id: 'layer-alti', dataset_id: 'dataset-alti', dataset_table_name: 'alti3d', dataset_attribution: CREDIT });
    const layers = [...Object.values(SAVED_LAYERS), zoningLabels, roadsGradient, fiji, alti];
    const tokens = new Map([...FIXTURE_TOKENS, ...[fiji, alti].map((layer) => [layer.dataset_id, fixtureToken(layer)] as const)]);
    const builder = describeLayers(layers.map(toSyncInput), { ...RENDER_CONTEXTS.builderWithClusterData, tokens }).sources;
    const viewer = describeLayers(layers.map(viewerInput), { ...RENDER_CONTEXTS.viewerWithClusterData, tokens }).sources;
    expect(builder.get('source-data-alti3d')).toHaveProperty('attribution', CREDIT);
    expect(Object.fromEntries([...viewer].map(([id, spec]) => [id.replace(/^viewer-/, ''), spec])))
      .toEqual(Object.fromEntries([...builder].map(([id, spec]) => [id, withoutAttribution(spec)])));
  });

  it('draws a raster layer without a token from its saved tile URL', () => {
    const { sources } = describeLayers([viewerInput(raster)], { ...RENDER_CONTEXTS.viewer, tokens: new Map() });
    expect(Object.fromEntries(sources)).toEqual({
      'viewer-source-layer-orthophoto': {
        type: 'raster',
        tiles: [`${FIXTURE_ORIGIN}/raster-tiles/${raster.dataset_id}/tiles/{z}/{x}/{y}.png`],
        tileSize: 256,
        minzoom: 0,
        maxzoom: 18,
        bounds: FIXTURE_BOUNDS,
      },
    });
  });
});
