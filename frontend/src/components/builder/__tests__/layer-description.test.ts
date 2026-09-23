import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';
import { SAVED_LAYERS, savedLayer, toSharedLayer } from '@/test/fixtures/saved-layers';
import { RENDER_CONTEXTS } from '@/test/fixtures/render-contexts';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';
import { toViewerSyncInput } from '@/components/viewer/ViewerMap';
import { toSyncInput } from '../map-sync';
import { describeLayers, type DescribedLayer, type RenderContext } from '../layer-description';
import type { LayerAdapter } from '../layer-adapters/types';

type SavedLayerKey = keyof typeof SAVED_LAYERS;
type Row = [label: string, layer: MapLayerResponse, context: RenderContext, expected: DescribedLayer | null];

/** What each shared fixture draws as before any bounded GeoJSON loads; null when the map draws nothing. */
const DRAWS_AS = {
  polygon: 'fill',
  strokeOnlyPolygon: 'fill',
  staleMirrorPolygon: 'fill',
  patternedPolygon: 'fill',
  extrusion: 'fill',
  line: 'line',
  dashedLine: 'line',
  arrowLine: 'line',
  point: 'circle',
  ringlessPoint: 'circle',
  categorical: 'fill',
  graduatedColor: 'fill',
  graduatedRadius: 'circle',
  graduatedWidth: 'line',
  heatmapByRamp: 'heatmap',
  reversedHeatmap: 'heatmap',
  heatmapByExpression: 'heatmap',
  boundedCluster: 'circle',
  serverCluster: 'cluster',
  fallbackCluster: 'circle',
  symbolWithLeftoverClassification: 'symbol',
  mixedGeometry: 'mixed',
  raster: 'raster',
  hillshadeDem: 'hillshade',
  terrainDem: null,
  folderRow: null,
} satisfies Record<SavedLayerKey, LayerAdapter['type'] | null>;

const NUMERIC_FILTER = ['>', ['get', 'pop'], 100] as FilterSpecification;
const TEXT_FILTER = ['==', ['get', 'zone'], 'R'] as FilterSpecification;

function described(
  layer: MapLayerResponse,
  drawsAs: LayerAdapter['type'],
  overrides: Partial<DescribedLayer> = {},
): DescribedLayer {
  return { id: `layer-${layer.id}`, drawsAs, filter: null, layout: layer.layout, zoom: null, ...overrides };
}

const fixtureRows: Row[] = (Object.keys(SAVED_LAYERS) as SavedLayerKey[]).map((key) => {
  const layer = SAVED_LAYERS[key];
  const drawsAs = DRAWS_AS[key];
  return [key, layer, RENDER_CONTEXTS.builder, drawsAs && described(layer, drawsAs)];
});

const privateKeys = savedLayer({ layout: { 'fill-sort-key': 1, _minzoom: 4, _maxzoom: 16 } });
const minzoomOnly = savedLayer({ layout: { _minzoom: 6 } });
const maxzoomOnly = savedLayer({ layout: { _maxzoom: 12 } });
const textZoom = savedLayer({ layout: { _minzoom: '6' } });
const numericFilter = savedLayer({ filter: NUMERIC_FILTER });
const textFilter = savedLayer({ filter: TEXT_FILTER });
const emptyFilter = savedLayer({ filter: [] as unknown as FilterSpecification });
const unsetDem = { ...SAVED_LAYERS.hillshadeDem, style_config: null };

const ruleRows: Row[] = [
  [
    'bounded cluster with its GeoJSON',
    SAVED_LAYERS.boundedCluster,
    RENDER_CONTEXTS.builderWithClusterData,
    described(SAVED_LAYERS.boundedCluster, 'cluster'),
  ],
  ['DEM without a render mode', unsetDem, RENDER_CONTEXTS.builder, described(unsetDem, 'hillshade')],
  [
    'viewer layer',
    SAVED_LAYERS.polygon,
    RENDER_CONTEXTS.viewer,
    described(SAVED_LAYERS.polygon, 'fill', { id: `viewer-layer-${SAVED_LAYERS.polygon.id}` }),
  ],
  [
    'private layout keys',
    privateKeys,
    RENDER_CONTEXTS.builder,
    described(privateKeys, 'fill', { layout: { 'fill-sort-key': 1 }, zoom: { minzoom: 4, maxzoom: 16 } }),
  ],
  ['saved minzoom only', minzoomOnly, RENDER_CONTEXTS.builder, described(minzoomOnly, 'fill', { layout: {}, zoom: { minzoom: 6, maxzoom: 22 } })],
  ['saved maxzoom only', maxzoomOnly, RENDER_CONTEXTS.builder, described(maxzoomOnly, 'fill', { layout: {}, zoom: { minzoom: 0, maxzoom: 12 } })],
  ['non-numeric zoom', textZoom, RENDER_CONTEXTS.builder, described(textZoom, 'fill', { layout: {} })],
  [
    'nullable numeric filter',
    numericFilter,
    RENDER_CONTEXTS.builder,
    described(numericFilter, 'fill', { filter: sanitizeNullableNumericFilter(NUMERIC_FILTER) }),
  ],
  ['text filter', textFilter, RENDER_CONTEXTS.builder, described(textFilter, 'fill', { filter: TEXT_FILTER })],
  ['empty filter', emptyFilter, RENDER_CONTEXTS.builder, described(emptyFilter, 'fill')],
];

const rows = [...fixtureRows, ...ruleRows];

function viewerInput(layer: MapLayerResponse) {
  return toViewerSyncInput(toSharedLayer(layer), layer.id, new Set([layer.id]));
}

describe('describeLayers', () => {
  it.each(rows)('describes the %s the same from both response shapes', (_label, layer, context, expected) => {
    expect(describeLayers([toSyncInput(layer)], context).layers[0] ?? null).toEqual(expected);
    expect(describeLayers([viewerInput(layer)], context).layers[0] ?? null).toEqual(expected);
  });

  it('describes every layer the same in the builder and the viewer apart from the id prefix', () => {
    const layers = rows.map(([, layer]) => layer);
    const builder = describeLayers(layers.map(toSyncInput), RENDER_CONTEXTS.builderWithClusterData);
    const viewer = describeLayers(layers.map(viewerInput), RENDER_CONTEXTS.viewerWithClusterData);
    expect(viewer.layers.map((layer) => ({ ...layer, id: layer.id.replace(/^viewer-/, '') }))).toEqual(builder.layers);
  });

  it('lists layers in stack order without the ones the map draws nothing for', () => {
    const { polygon, folderRow, line, terrainDem, raster } = SAVED_LAYERS;
    const description = describeLayers(
      [polygon, folderRow, line, terrainDem, raster].map(toSyncInput),
      RENDER_CONTEXTS.builder,
    );
    expect(description.layers.map((layer) => layer.id)).toEqual([polygon, line, raster].map((layer) => `layer-${layer.id}`));
  });

  it('keeps the saved layout object when it has no private keys', () => {
    const layer = toSyncInput(SAVED_LAYERS.arrowLine);
    expect(describeLayers([layer], RENDER_CONTEXTS.builder).layers[0].layout).toBe(layer.layout);
  });
});
