// describeLayers gives each layer the map layers it draws, and the migrated adapters' own methods write exactly those.
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, StyleConfig } from '@/types/api';
import { SAVED_LAYERS } from '@/test/fixtures/saved-layers';
import { FIXTURE_TOKENS, RENDER_CONTEXTS } from '@/test/fixtures/render-contexts';
import { RecordingMap } from '@/test/recording-map';
import { MAP_COLORS } from '@/lib/map-colors';
import { syncLayersToMap, toSyncInput } from '../map-sync';
import { adapterInputFor, describeLayers, type RenderContext } from '../layer-description';
import { DEFAULT_CIRCLE_PAINT } from '../layer-adapters/builder-defaults';
import { CIRCLE_OWNED_PAINT_PROPERTIES } from '../layer-adapters/circle-adapter';
import {
  CLUSTER_CIRCLE_OWNED_PAINT_PROPERTIES,
  CLUSTER_COUNT_OWNED_LAYOUT_PROPERTIES,
  CLUSTER_COUNT_OWNED_PAINT_PROPERTIES,
} from '../layer-adapters/cluster-adapter';
import { HEATMAP_OWNED_PAINT_PROPERTIES, buildHeatmapColorExpression } from '../layer-adapters/heatmap-adapter';
import { SYMBOL_OWNED_LAYOUT_PROPERTIES, SYMBOL_OWNED_PAINT_PROPERTIES } from '../layer-adapters/symbol-adapter';
import {
  ARROW_OWNED_LAYOUT_PROPERTIES,
  ARROW_OWNED_PAINT_PROPERTIES,
  LINE_OWNED_LAYOUT_PROPERTIES,
  LINE_OWNED_PAINT_PROPERTIES,
} from '../layer-adapters/line-adapter';
import { getAdapter } from '../layer-adapters/registry';
import type { ImageSpec, LayerDrawing, LayerSpec } from '../layer-adapters/types';

type Row = [label: string, layer: MapLayerResponse, context: RenderContext, expected: LayerDrawing];

const {
  point,
  graduatedRadius,
  fallbackCluster,
  boundedCluster,
  serverCluster,
  heatmapByRamp,
  reversedHeatmap,
  heatmapByExpression,
  symbolWithLeftoverClassification: symbol,
  line,
  dashedLine,
  arrowLine,
  graduatedWidth,
} = SAVED_LAYERS;

const FILTER = ['==', ['get', 'kind'], 'school'] as FilterSpecification;
const STEP_COLOR = ['step', ['get', 'val'], '#ff0000', 100, '#0000ff'];
const RADIUS_BY_ZOOM = ['interpolate', ['linear'], ['zoom'], 4, 3, 12, 10];
const OPACITY_BY_ZOOM = ['step', ['zoom'], 0.25, 10, 0.8];
const CLUSTER_RADIUS = ['step', ['get', 'point_count'], 16, 100, 21, 750, 27];
const CLUSTERS = ['has', 'point_count'];
const UNCLUSTERED = ['!', ['has', 'point_count']];
const GEOLENS_SPRITE: ImageSpec = { kind: 'sprite', id: 'geolens', url: '/api/maps/sprites/geolens' };

function tableSource(layer: MapLayerResponse) {
  return { source: `source-data-${layer.dataset_table_name}`, 'source-layer': `data.${layer.dataset_table_name}` };
}

function ownSource(layer: MapLayerResponse, sourceLayer = true) {
  return {
    source: `source-${layer.id}`,
    ...(sourceLayer ? { 'source-layer': `data.${layer.dataset_table_name}` } : {}),
  };
}

function drawing(specs: LayerSpec[], images: ImageSpec[] = []): LayerDrawing {
  return { specs, images };
}

function circle(
  layer: MapLayerResponse,
  paint: Record<string, unknown>,
  overrides: Partial<LayerSpec['layer']> = {},
): LayerSpec {
  return {
    layer: { id: `layer-${layer.id}`, type: 'circle', ...tableSource(layer), layout: { visibility: 'visible' }, paint, ...overrides },
    ownedPaint: CIRCLE_OWNED_PAINT_PROPERTIES,
    ownedLayout: [],
  };
}

function cluster(
  layer: MapLayerResponse,
  parts: {
    source: { source: string; 'source-layer'?: string };
    color: unknown;
    points: Record<string, unknown>;
    opacity?: number;
    visibility?: 'visible' | 'none';
    counts?: 'visible' | 'none';
    textColor?: string;
    textSize?: number;
    filter?: FilterSpecification;
  },
): LayerSpec[] {
  const { source, color, points, opacity = 1, visibility = 'visible', counts = visibility } = parts;
  const id = `layer-${layer.id}`;
  return [
    {
      layer: {
        id: `${id}-cluster`,
        type: 'circle',
        ...source,
        filter: CLUSTERS as FilterSpecification,
        layout: { visibility },
        paint: {
          'circle-color': color,
          'circle-radius': CLUSTER_RADIUS,
          'circle-opacity': opacity,
          'circle-stroke-color': MAP_COLORS.cluster.stroke,
          'circle-stroke-width': 1.5,
          'circle-stroke-opacity': Math.min(opacity + 0.1, 1),
        },
      },
      ownedPaint: CLUSTER_CIRCLE_OWNED_PAINT_PROPERTIES,
      ownedLayout: [],
    },
    {
      layer: {
        id: `${id}-cluster-count`,
        type: 'symbol',
        ...source,
        filter: CLUSTERS as FilterSpecification,
        layout: {
          'text-field': ['get', 'point_count_abbreviated'],
          'text-size': parts.textSize ?? 12,
          'text-font': ['Noto Sans Regular'],
          'text-allow-overlap': true,
          'text-ignore-placement': true,
          visibility: counts,
        },
        paint: {
          'text-color': parts.textColor ?? MAP_COLORS.cluster.text,
          'text-opacity': opacity,
          'text-halo-color': MAP_COLORS.cluster.textHalo,
          'text-halo-width': 1,
        },
      },
      ownedPaint: CLUSTER_COUNT_OWNED_PAINT_PROPERTIES,
      ownedLayout: CLUSTER_COUNT_OWNED_LAYOUT_PROPERTIES,
    },
    {
      layer: {
        id,
        type: 'circle',
        ...source,
        filter: (parts.filter ? ['all', UNCLUSTERED, parts.filter] : UNCLUSTERED) as FilterSpecification,
        layout: { visibility },
        paint: { ...points, 'circle-opacity': opacity },
      },
      ownedPaint: CIRCLE_OWNED_PAINT_PROPERTIES,
      ownedLayout: [],
    },
  ];
}

function heatmap(
  layer: MapLayerResponse,
  paint: Record<string, unknown>,
  overrides: Partial<LayerSpec['layer']> = {},
): LayerSpec {
  return {
    layer: { id: `layer-${layer.id}`, type: 'heatmap', ...tableSource(layer), layout: { visibility: 'visible' }, paint, ...overrides },
    ownedPaint: HEATMAP_OWNED_PAINT_PROPERTIES,
    ownedLayout: [],
  };
}

const ICONS = {
  'icon-image': 'geolens:marker',
  'icon-size': 1,
  'icon-rotate': 0,
  'icon-anchor': 'center',
  'icon-offset': [0, 0],
  'icon-allow-overlap': true,
};

const LABEL_TEXT = {
  'text-field': ['get', 'name'],
  'text-size': 12,
  'text-font': ['Noto Sans Regular'],
  'text-anchor': 'center',
  'text-offset': [0, -1.5],
  'text-allow-overlap': false,
  'text-max-width': 10,
};

const LABEL_PAINT = {
  'text-color': MAP_COLORS.label.color,
  'text-halo-color': MAP_COLORS.label.halo,
  'text-halo-width': 1.5,
  'text-opacity': 1,
};

/** The standalone label companion a point-placed family (circle, cluster,
 *  line) draws — LABEL_TEXT/LABEL_PAINT plus the explicit placement and zoom
 *  range every family shares, since none of them inline it the way symbol
 *  does. `source` matches whatever source that family's own spec(s) use —
 *  the shared per-dataset one by default, or a cluster's own per-layer one. */
function labelCompanionSpec(
  layer: MapLayerResponse,
  source: { source: string; 'source-layer'?: string } = tableSource(layer),
): LayerSpec {
  return {
    layer: {
      id: `layer-${layer.id}-label`,
      type: 'symbol',
      ...source,
      layout: { ...LABEL_TEXT, 'symbol-placement': 'point', visibility: 'visible' },
      paint: LABEL_PAINT,
      minzoom: 0,
      maxzoom: 22,
    },
    ownedPaint: ['text-color', 'text-halo-color', 'text-halo-width', 'text-opacity'],
    ownedLayout: [
      'text-field', 'text-size', 'symbol-placement', 'text-allow-overlap',
      'text-font', 'text-max-width', 'text-anchor', 'text-offset',
      'symbol-avoid-edges', 'visibility',
    ],
  };
}

function symbolSpec(
  layer: MapLayerResponse,
  layout: Record<string, unknown>,
  paint: Record<string, unknown> = { 'icon-opacity': 1 },
  overrides: Partial<LayerSpec['layer']> = {},
): LayerSpec {
  return {
    layer: { id: `layer-${layer.id}`, type: 'symbol', ...tableSource(layer), layout, paint, ...overrides },
    ownedPaint: SYMBOL_OWNED_PAINT_PROPERTIES,
    ownedLayout: SYMBOL_OWNED_LAYOUT_PROPERTIES,
  };
}

function withSymbol(symbolConfig: StyleConfig['symbol'], overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return { ...symbol, style_config: { ...symbol.style_config, symbol: symbolConfig }, ...overrides };
}

function lineSpecRow(
  layer: MapLayerResponse,
  paint: Record<string, unknown>,
  overrides: Partial<LayerSpec['layer']> = {},
): LayerSpec {
  return {
    layer: {
      id: `layer-${layer.id}`,
      type: 'line',
      ...tableSource(layer),
      layout: { 'line-cap': 'round', 'line-join': 'round', visibility: 'visible' },
      paint,
      ...overrides,
    },
    ownedPaint: LINE_OWNED_PAINT_PROPERTIES,
    ownedLayout: LINE_OWNED_LAYOUT_PROPERTIES,
  };
}

const ARROW_IMAGE = { kind: 'image', id: 'geolens-line-arrow', data: expect.any(Function), options: { sdf: true, pixelRatio: 1 } };

function arrowSpecRow(
  layer: MapLayerResponse,
  config: { color: string; size: number; spacing: number },
): LayerSpec {
  return {
    layer: {
      id: `layer-${layer.id}-arrow`,
      type: 'symbol',
      ...tableSource(layer),
      layout: {
        'symbol-placement': 'line',
        'symbol-spacing': config.spacing,
        'icon-image': 'geolens-line-arrow',
        'icon-size': config.size / 14,
        'icon-allow-overlap': true,
        'icon-ignore-placement': true,
        'icon-rotation-alignment': 'map',
        visibility: 'visible',
      },
      paint: { 'icon-color': config.color, 'icon-opacity': 1 },
    },
    ownedPaint: ARROW_OWNED_PAINT_PROPERTIES,
    ownedLayout: ARROW_OWNED_LAYOUT_PROPERTIES,
  };
}

const pointPaint = { 'circle-radius': 5, 'circle-color': '#3b82f6', 'circle-stroke-color': '#1d4ed8', 'circle-stroke-width': 1 };
const treePoints = { 'circle-radius': 4, 'circle-color': '#16a34a' };
const rackPoints = { 'circle-radius': 5, 'circle-color': '#0d9488', 'circle-stroke-color': '#134e4a', 'circle-stroke-width': 1 };
const treeRamp = ['step', ['get', 'point_count'], '#bbf7d0', 100, '#16a34a'];
const heatDefaults = { 'heatmap-radius': 30, 'heatmap-weight': 1, 'heatmap-intensity': 1 };
const styledClusters = {
  ...serverCluster,
  opacity: 0.5,
  style_config: { render_mode: 'cluster', builder: { clusterColor: '#fb923c', clusterTextColor: '#111827', clusterTextSize: 30 } },
} as MapLayerResponse;

const { builder, builderWithClusterData } = RENDER_CONTEXTS;

const rows: Row[] = [
  ['a point layer', point, builder, drawing([circle(point, { ...pointPaint, 'circle-opacity': 1 })])],
  ['a point layer without circle paint', { ...point, paint: {} }, builder, drawing([circle(point, { ...DEFAULT_CIRCLE_PAINT, 'circle-opacity': 1 })])],
  [
    'a point layer with stale fill and line paint',
    { ...point, paint: { 'circle-radius': 7, 'fill-color': '#ff0000', 'line-color': '#00ff00', 'line-width': 2, 'fill-opacity': 0.4 } },
    builder,
    drawing([circle(point, { 'circle-radius': 7, 'circle-opacity': 1 })]),
  ],
  [
    'a data-driven point colour',
    { ...point, paint: { 'circle-color': STEP_COLOR, 'circle-radius': 5 } },
    builder,
    drawing([circle(point, { 'circle-color': STEP_COLOR, 'circle-radius': 5, 'circle-opacity': 1 })]),
  ],
  [
    'a colour expression with no scalar fallback, over the default circle paint',
    { ...point, paint: { 'circle-color': ['get', 'color'] } },
    builder,
    drawing([circle(point, { ...DEFAULT_CIRCLE_PAINT, 'circle-color': ['get', 'color'], 'circle-opacity': 1 })]),
  ],
  [
    'zoom expressions under a master opacity, which multiplies the stored opacity expression',
    { ...point, opacity: 0.4, paint: { 'circle-color': '#ff0000', 'circle-radius': RADIUS_BY_ZOOM, 'circle-opacity': OPACITY_BY_ZOOM } },
    builder,
    drawing([circle(point, { 'circle-color': '#ff0000', 'circle-radius': RADIUS_BY_ZOOM, 'circle-opacity': ['*', OPACITY_BY_ZOOM, 0.4] })]),
  ],
  [
    'a master opacity over a stored circle opacity, with no layer-opacity key',
    { ...point, opacity: 0.5, paint: { 'circle-color': '#ff0000', 'circle-radius': 4, 'circle-opacity': 0.8 } },
    builder,
    drawing([circle(point, { 'circle-color': '#ff0000', 'circle-radius': 4, 'circle-opacity': 0.4 })]),
  ],
  ['a hidden point layer', { ...point, visible: false }, builder, drawing([circle(point, { ...pointPaint, 'circle-opacity': 1 }, { layout: { visibility: 'none' } })])],
  ['a filtered point layer', { ...point, filter: FILTER }, builder, drawing([circle(point, { ...pointPaint, 'circle-opacity': 1 }, { filter: FILTER })])],
  [
    'a stored layout key',
    { ...point, layout: { 'circle-sort-key': 3 } },
    builder,
    drawing([circle(point, { ...pointPaint, 'circle-opacity': 1 }, { layout: { 'circle-sort-key': 3, visibility: 'visible' } })]),
  ],
  [
    'a graduated radius',
    graduatedRadius,
    builder,
    drawing([circle(graduatedRadius, { ...graduatedRadius.paint, 'circle-opacity': 1 })]),
  ],
  [
    'a cluster without a feature count, as circles',
    fallbackCluster,
    builder,
    drawing([circle(fallbackCluster, { ...fallbackCluster.paint, 'circle-opacity': 1 })]),
  ],
  [
    'a bounded cluster before its GeoJSON loads, as circles on its own source',
    boundedCluster,
    builder,
    drawing([circle(boundedCluster, { ...rackPoints, 'circle-opacity': 1 }, ownSource(boundedCluster))]),
  ],
  [
    'a server cluster, whose colour ramp steps on the point count',
    serverCluster,
    builder,
    drawing(cluster(serverCluster, { source: ownSource(serverCluster), color: treeRamp, points: treePoints })),
  ],
  [
    'a bounded cluster with its GeoJSON, which names no source layer',
    boundedCluster,
    builderWithClusterData,
    drawing(cluster(boundedCluster, { source: ownSource(boundedCluster, false), color: '#0d9488', points: rackPoints })),
  ],
  [
    'a filtered cluster, which filters only the unclustered points',
    { ...serverCluster, filter: FILTER },
    builder,
    drawing(cluster(serverCluster, { source: ownSource(serverCluster), color: treeRamp, points: treePoints, filter: FILTER })),
  ],
  [
    'a hidden cluster',
    { ...serverCluster, visible: false },
    builder,
    drawing(cluster(serverCluster, { source: ownSource(serverCluster), color: treeRamp, points: treePoints, visibility: 'none' })),
  ],
  [
    'a cluster with its counts turned off',
    { ...serverCluster, style_config: { ...serverCluster.style_config, builder: { ...serverCluster.style_config?.builder, clusterShowCounts: false } } },
    builder,
    drawing(cluster(serverCluster, { source: ownSource(serverCluster), color: treeRamp, points: treePoints, counts: 'none' })),
  ],
  [
    'a cluster with a flat colour, text colour and size, under a master opacity',
    styledClusters,
    builder,
    drawing(cluster(serverCluster, {
      source: ownSource(serverCluster),
      color: '#fb923c',
      points: treePoints,
      opacity: 0.5,
      textColor: '#111827',
      textSize: 24,
    })),
  ],
  [
    'a heatmap on a builder ramp',
    heatmapByRamp,
    builder,
    drawing([heatmap(heatmapByRamp, {
      ...heatDefaults,
      'heatmap-weight': ['get', 'severity'],
      'heatmap-color': buildHeatmapColorExpression('Blues'),
      'heatmap-opacity': 0.8,
    })]),
  ],
  [
    'a reversed heatmap ramp',
    reversedHeatmap,
    builder,
    drawing([heatmap(reversedHeatmap, { ...heatDefaults, 'heatmap-color': buildHeatmapColorExpression('Viridis', true), 'heatmap-opacity': 0.8 })]),
  ],
  [
    'a stored heatmap colour, which wins over the ramp',
    heatmapByExpression,
    builder,
    drawing([heatmap(heatmapByExpression, { ...heatDefaults, 'heatmap-color': heatmapByExpression.paint['heatmap-color'], 'heatmap-opacity': 0.8 })]),
  ],
  [
    'a stored heatmap opacity under a master opacity',
    { ...heatmapByRamp, opacity: 0.6, paint: { 'heatmap-opacity': 0.5 } },
    builder,
    drawing([heatmap(heatmapByRamp, { ...heatDefaults, 'heatmap-color': buildHeatmapColorExpression('Blues'), 'heatmap-opacity': 0.3 })]),
  ],
  [
    'the default heatmap opacity under a master opacity',
    { ...heatmapByRamp, opacity: 0.5, paint: {} },
    builder,
    drawing([heatmap(heatmapByRamp, { ...heatDefaults, 'heatmap-color': buildHeatmapColorExpression('Blues'), 'heatmap-opacity': 0.4 })]),
  ],
  [
    'private heatmap keys, which stay off the map',
    { ...heatmapByRamp, paint: { 'heatmap-radius': 40, '_heatmap-ramp': 'Viridis', '_heatmap-weight-column': 'count' } },
    builder,
    drawing([heatmap(heatmapByRamp, {
      ...heatDefaults,
      'heatmap-radius': 40,
      'heatmap-color': buildHeatmapColorExpression('Blues'),
      'heatmap-opacity': 0.8,
    })]),
  ],
  [
    'a snake_case reversal flag',
    { ...heatmapByRamp, paint: {}, style_config: { render_mode: 'heatmap', builder: { heatmap_reversed: true } } as unknown as StyleConfig },
    builder,
    drawing([heatmap(heatmapByRamp, { ...heatDefaults, 'heatmap-color': buildHeatmapColorExpression('YlOrRd', true), 'heatmap-opacity': 0.8 })]),
  ],
  [
    'a hidden, filtered heatmap',
    { ...heatmapByRamp, visible: false, filter: FILTER },
    builder,
    drawing([heatmap(heatmapByRamp, {
      ...heatDefaults,
      'heatmap-weight': ['get', 'severity'],
      'heatmap-color': buildHeatmapColorExpression('Blues'),
      'heatmap-opacity': 0.8,
    }, { layout: { visibility: 'none' }, filter: FILTER })]),
  ],
  ['a symbol layer', symbol, builder, drawing([symbolSpec(symbol, { ...ICONS, visibility: 'visible' })], [GEOLENS_SPRITE])],
  [
    'a symbol layer with a label, which draws the text itself',
    { ...symbol, label_config: { column: 'name' } },
    builder,
    drawing([symbolSpec(symbol, { ...ICONS, visibility: 'visible', ...LABEL_TEXT }, { 'icon-opacity': 1, ...LABEL_PAINT })], [GEOLENS_SPRITE]),
  ],
  [
    'a label with overlap turned off, which applies to the icons too',
    { ...symbol, label_config: { column: 'name', allowOverlap: false } },
    builder,
    drawing([symbolSpec(symbol, { ...ICONS, 'icon-allow-overlap': false, visibility: 'visible', ...LABEL_TEXT }, { 'icon-opacity': 1, ...LABEL_PAINT })], [GEOLENS_SPRITE]),
  ],
  [
    'a cleared label column, whose leftover overlap setting is ignored',
    { ...symbol, label_config: { column: '', allowOverlap: false } },
    builder,
    drawing([symbolSpec(symbol, { ...ICONS, visibility: 'visible' })], [GEOLENS_SPRITE]),
  ],
  [
    'category icons, matched on the stringified column',
    withSymbol({ iconImage: 'marker', categoryColumn: 'kind', categories: [{ value: 'bus', icon: 'bus' }, { value: 'rail', icon: 'train' }] }),
    builder,
    drawing([symbolSpec(symbol, {
      ...ICONS,
      'icon-image': ['match', ['to-string', ['get', 'kind']], 'bus', 'geolens:bus', 'rail', 'geolens:train', 'geolens:marker'],
      visibility: 'visible',
    })], [GEOLENS_SPRITE]),
  ],
  [
    'a sized, rotated and anchored icon',
    withSymbol({ iconImage: 'bus', iconSize: 1.25, iconRotation: 15, iconAnchor: 'bottom', iconOffset: [0, -1] }),
    builder,
    drawing([symbolSpec(symbol, {
      ...ICONS,
      'icon-image': 'geolens:bus',
      'icon-size': 1.25,
      'icon-rotate': 15,
      'icon-anchor': 'bottom',
      'icon-offset': [0, -1],
      visibility: 'visible',
    })], [GEOLENS_SPRITE]),
  ],
  [
    'a hidden, filtered symbol layer under a master opacity',
    { ...symbol, visible: false, filter: FILTER, opacity: 0.4 },
    builder,
    drawing([symbolSpec(symbol, { ...ICONS, visibility: 'none' }, { 'icon-opacity': 0.4 }, { filter: FILTER })], [GEOLENS_SPRITE]),
  ],
  ['a line layer', line, builder, drawing([lineSpecRow(line, { 'line-color': '#ef4444', 'line-width': 2, 'line-opacity': 1, 'line-layer-opacity': 1 })])],
  [
    'a line layer without line paint',
    { ...line, paint: {} },
    builder,
    drawing([lineSpecRow(line, { 'line-color': MAP_COLORS.default.fill, 'line-width': 2, 'line-opacity': 1, 'line-layer-opacity': 1 })]),
  ],
  [
    'a line with stale fill and circle paint',
    { ...line, paint: { 'line-color': '#ef4444', 'fill-color': '#00ff00', 'circle-radius': 8 } },
    builder,
    drawing([lineSpecRow(line, { 'line-color': '#ef4444', 'line-opacity': 1, 'line-layer-opacity': 1 })]),
  ],
  [
    'a stored dasharray, which wins over a legacy layout one',
    dashedLine,
    builder,
    drawing([lineSpecRow(dashedLine, { 'line-color': '#a16207', 'line-width': 1.5, 'line-dasharray': [4, 2], 'line-opacity': 1, 'line-layer-opacity': 1 })]),
  ],
  [
    'a legacy dasharray stored in layout, migrated into paint',
    { ...line, layout: { 'line-dasharray': [3, 1] } },
    builder,
    drawing([lineSpecRow(line, { 'line-color': '#ef4444', 'line-width': 2, 'line-dasharray': [3, 1], 'line-opacity': 1, 'line-layer-opacity': 1 })]),
  ],
  [
    'a graduated line width, with no scalar fallback in the spec',
    graduatedWidth,
    builder,
    drawing([lineSpecRow(graduatedWidth, { 'line-color': '#0284c7', 'line-width': graduatedWidth.paint['line-width'], 'line-opacity': 1, 'line-layer-opacity': 1 })]),
  ],
  [
    'a hidden, filtered line layer under a master opacity',
    { ...line, visible: false, filter: FILTER, opacity: 0.6 },
    builder,
    drawing([lineSpecRow(line, { 'line-color': '#ef4444', 'line-width': 2, 'line-opacity': 1, 'line-layer-opacity': 0.6 }, { layout: { 'line-cap': 'round', 'line-join': 'round', visibility: 'none' }, filter: FILTER })]),
  ],
  [
    'an arrow line, whose companion carries the icon',
    arrowLine,
    builder,
    drawing(
      [
        lineSpecRow(arrowLine, { 'line-color': '#2563eb', 'line-width': 2, 'line-opacity': 1, 'line-layer-opacity': 1 }),
        arrowSpecRow(arrowLine, { color: '#1e3a8a', size: 14, spacing: 80 }),
      ],
      [ARROW_IMAGE as unknown as ImageSpec],
    ),
  ],
  [
    'a point layer with a label',
    { ...point, label_config: { column: 'name' } },
    builder,
    drawing([circle(point, { ...pointPaint, 'circle-opacity': 1 }), labelCompanionSpec(point)]),
  ],
  [
    'a server cluster with a label',
    { ...serverCluster, label_config: { column: 'name' } },
    builder,
    drawing(cluster(serverCluster, { source: ownSource(serverCluster), color: treeRamp, points: treePoints }).concat(labelCompanionSpec(serverCluster, ownSource(serverCluster)))),
  ],
];

describe('describeLayers specs', () => {
  it.each(rows)('describes the map layers of %s', (_label, layer, context, expected) => {
    const [described] = describeLayers([toSyncInput(layer)], context).layers;
    expect({ specs: described.specs, images: described.images }).toEqual(expected);
  });
});

/** A map holding the source a described layer draws from, and the adapter input for that layer. */
function setUp(layer: MapLayerResponse, context: RenderContext = builder) {
  const input = toSyncInput(layer);
  const { layers: [described], sources } = describeLayers([input], context);
  const source = sources.get(described.sourceId)!;
  const recording = new RecordingMap();
  recording.addSource(described.sourceId, source as unknown as Record<string, unknown>);
  const adapterInput = { ...adapterInputFor(input, described), sourceType: source.type === 'geojson' ? 'geojson' as const : 'vector' as const };
  return { recording, described, adapter: getAdapter(described.drawsAs), adapterInput };
}

function held(specs: readonly LayerSpec[]) {
  return specs.map(({ layer }) => layer);
}

const ADAPTER_CASES: [label: string, layer: MapLayerResponse, context: RenderContext][] = [
  ['circle', point, builder],
  ['cluster', serverCluster, builder],
  ['bounded cluster', boundedCluster, builderWithClusterData],
  ['heatmap', heatmapByRamp, builder],
  ['symbol', { ...symbol, label_config: { column: 'name' } }, builder],
  ['line', line, builder],
  ['arrow line', arrowLine, builder],
];

describe("the point adapters' own methods", () => {
  it.each(ADAPTER_CASES)('%s addLayers adds the described map layers', (_label, layer, context) => {
    const { recording, described, adapter, adapterInput } = setUp(layer, context);

    adapter.addLayers(recording.map, adapterInput);

    expect(recording.layerIds().map((id) => recording.layer(id))).toEqual(held(described.specs));
    for (const image of described.images) {
      if (image.kind === 'sprite') expect(recording.getSprite().some(({ id }) => id === image.id)).toBe(true);
      else expect(recording.map.hasImage(image.id)).toBe(true);
    }
    expect(recording.errors).toEqual([]);
  });

  it.each(ADAPTER_CASES)('%s syncPaint brings existing layers to a changed description', (_label, layer, context) => {
    const { recording, adapter, adapterInput } = setUp(layer, context);
    adapter.addLayers(recording.map, adapterInput);
    const changed = { ...layer, opacity: 0.5, filter: FILTER, label_config: null };
    const next = setUp(changed, context);

    adapter.syncPaint(recording.map, next.adapterInput);

    for (const { layer: spec } of next.described.specs) {
      expect(recording.layer(spec.id)?.paint).toEqual(spec.paint);
      expect(recording.layer(spec.id)?.filter).toEqual(spec.filter);
    }
    expect(recording.errors).toEqual([]);
  });

  it.each(ADAPTER_CASES)('%s syncVisibility sets only the visibility, on layers already added', (_label, layer, context) => {
    const { recording, described, adapter, adapterInput } = setUp(layer, context);
    adapter.syncVisibility(recording.map, adapterInput);
    expect(recording.layerIds()).toEqual([]);

    adapter.addLayers(recording.map, adapterInput);
    const before = recording.layerIds().map((id) => recording.layer(id));
    adapter.syncVisibility(recording.map, { ...adapterInput, visible: false });

    expect(recording.layerIds().map((id) => recording.layer(id))).toEqual(
      before.map((added) => ({ ...added, layout: { ...added!.layout, visibility: 'none' } })),
    );
    expect(described.specs.length).toBe(before.length);
  });

  it.each(ADAPTER_CASES)('%s getLayerIds covers every current spec id', (_label, layer, context) => {
    const { described, adapter } = setUp(layer, context);
    const ids = new Set(adapter.getLayerIds(described.id));
    // A superset, not exact equality: a mode-dependent companion (e.g. line's arrow)
    // is always listed for cleanup/z-order even when the current drawing lacks it.
    for (const { layer: spec } of described.specs) expect(ids.has(spec.id)).toBe(true);
  });

  it('circle, heatmap, symbol and line syncPaint leave a map without the layer alone', () => {
    for (const layer of [point, heatmapByRamp, symbol, line]) {
      const { recording, adapter, adapterInput } = setUp(layer);
      adapter.syncPaint(recording.map, adapterInput);
      expect(recording.layerIds()).toEqual([]);
    }
  });

  it('an arrow line removes its companion when the render mode leaves arrow', () => {
    const { recording, adapter, adapterInput } = setUp(arrowLine);
    adapter.addLayers(recording.map, adapterInput);
    expect(recording.layerIds()).toEqual([`layer-${arrowLine.id}`, `layer-${arrowLine.id}-arrow`]);

    const next = setUp({ ...arrowLine, style_config: null });
    adapter.syncPaint(recording.map, next.adapterInput);

    expect(recording.layerIds()).toEqual([`layer-${arrowLine.id}`]);
    expect(recording.errors).toEqual([]);
  });

  it('removing a stored line-cap and line-join returns to round, not the map default', () => {
    const { recording, adapter, adapterInput } = setUp({ ...line, layout: { 'line-cap': 'butt', 'line-join': 'bevel' } });
    adapter.addLayers(recording.map, adapterInput);
    expect(recording.layer(`layer-${line.id}`)?.layout).toEqual(
      expect.objectContaining({ 'line-cap': 'butt', 'line-join': 'bevel' }),
    );

    const next = setUp(line);
    adapter.syncPaint(recording.map, next.adapterInput);

    expect(recording.layer(`layer-${line.id}`)?.layout).toEqual(
      expect.objectContaining({ 'line-cap': 'round', 'line-join': 'round' }),
    );
  });

  it('cluster syncVisibility keeps the counts hidden while they are turned off', () => {
    const countsOff = { ...serverCluster, style_config: { ...serverCluster.style_config, builder: { clusterShowCounts: false } } } as MapLayerResponse;
    const { recording, described, adapter, adapterInput } = setUp(countsOff);
    adapter.addLayers(recording.map, { ...adapterInput, visible: false });

    adapter.syncVisibility(recording.map, adapterInput);

    const [clusters, counts, points] = described.specs.map(({ layer }) => recording.layer(layer.id)?.layout.visibility);
    expect([clusters, counts, points]).toEqual(['visible', 'none', 'visible']);
  });

  it('cluster syncPaint adds the cluster layers the map lacks', () => {
    const { recording, described, adapter, adapterInput } = setUp(serverCluster);

    adapter.syncPaint(recording.map, adapterInput);

    expect(recording.layerIds()).toEqual(described.specs.map(({ layer }) => layer.id));
  });
});

describe('a layer whose saved style an adapter cannot read', () => {
  const brokenHeatmap = {
    ...heatmapByRamp,
    style_config: { ...heatmapByRamp.style_config, builder: { heatmapRamp: 42 } },
  } as unknown as MapLayerResponse;

  it('gets no map layers, and every other layer is described', () => {
    const { layers } = describeLayers([toSyncInput(brokenHeatmap), toSyncInput(point)], builder);

    expect(layers.map(({ id, specs }) => [id, specs.length])).toEqual([[`layer-${brokenHeatmap.id}`, 0], [`layer-${point.id}`, 1]]);
  });

  it('leaves every other layer drawn by a sync pass', () => {
    const recording = new RecordingMap();

    syncLayersToMap(recording.map, [toSyncInput(brokenHeatmap), toSyncInput(point)], new Map(FIXTURE_TOKENS), undefined, { current: new Set() }, { current: '' });

    expect(recording.layerIds()).toEqual([`layer-${point.id}`]);
    expect(recording.layer(`layer-${point.id}`)).toEqual({ ...circle(point, { ...pointPaint, 'circle-opacity': 1 }).layer, minzoom: 0, maxzoom: 22 });
  });
});
