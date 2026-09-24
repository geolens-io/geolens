import { describe, expect, it } from 'vitest';
import { buildGraduatedExpression, buildGraduatedSizeExpression, getRampColors } from '@/lib/color-ramps';
import { MAP_COLORS } from '@/lib/map-colors';
import type { BuilderStyleConfig, MapLayerResponse } from '@/types/api';
import { SAVED_LAYERS, ZOOM_FADED_STATIONS, savedLayer, toSharedLayer } from '@/test/fixtures/saved-layers';
import { legendFacts, type LegendClasses, type LegendFacts, type LegendRamp, type LegendSwatch } from '../legend-facts';

type Row = [label: string, layer: MapLayerResponse, expected: LegendFacts | null];

/** The outline the fill and mixed adapters draw when the style sets none. */
const DEFAULT_OUTLINE = { color: MAP_COLORS.default.stroke, width: 1 };

function swatch(overrides: Partial<LegendSwatch> = {}): LegendSwatch {
  return { fill: null, fillOpacity: 1, opacity: 1, stroke: null, pattern: null, ...overrides };
}

/** No classes, heatmap ramp or weight column, as for any unclassified layer that is not a heatmap. */
const PLAIN = { classes: null, ramp: null, weightColumn: null } as const;

const fixtureFacts: Record<keyof typeof SAVED_LAYERS, Omit<LegendFacts, 'name' | keyof typeof PLAIN> | null> = {
  polygon: { drawsAs: 'fill', swatch: swatch({ fill: '#3b82f6', fillOpacity: 0.3, stroke: DEFAULT_OUTLINE }) },
  strokeOnlyPolygon: {
    drawsAs: 'fill',
    swatch: swatch({ fill: '#0ea5e9', fillOpacity: 0, stroke: { color: '#0369a1', width: 2 } }),
  },
  staleMirrorPolygon: {
    drawsAs: 'fill',
    swatch: swatch({ fill: '#22c55e', fillOpacity: 0.3, stroke: { color: '#15803d', width: 1.5 } }),
  },
  patternedPolygon: {
    drawsAs: 'fill',
    swatch: swatch({ fillOpacity: 0.8, stroke: DEFAULT_OUTLINE, pattern: { id: 'geolens-fill-hatch', tint: '#16a34a' } }),
  },
  extrusion: { drawsAs: 'fill', swatch: swatch({ fill: '#f97316', fillOpacity: 0.6, stroke: DEFAULT_OUTLINE }) },
  line: { drawsAs: 'line', swatch: swatch({ fill: '#ef4444' }) },
  dashedLine: { drawsAs: 'line', swatch: swatch({ fill: '#a16207' }) },
  arrowLine: { drawsAs: 'line', swatch: swatch({ fill: '#2563eb' }) },
  point: { drawsAs: 'circle', swatch: swatch({ fill: '#3b82f6', stroke: { color: '#1d4ed8', width: 1 } }) },
  ringlessPoint: { drawsAs: 'circle', swatch: swatch({ fill: '#f59e0b' }) },
  categorical: { drawsAs: 'fill', swatch: swatch({ fillOpacity: 0.7, stroke: DEFAULT_OUTLINE }) },
  graduatedColor: { drawsAs: 'fill', swatch: swatch({ fillOpacity: 0.3, stroke: DEFAULT_OUTLINE }) },
  graduatedRadius: { drawsAs: 'circle', swatch: swatch({ fill: '#dc2626' }) },
  graduatedWidth: { drawsAs: 'line', swatch: swatch({ fill: '#0284c7' }) },
  heatmapByRamp: { drawsAs: 'heatmap', swatch: null },
  reversedHeatmap: { drawsAs: 'heatmap', swatch: null },
  heatmapByExpression: { drawsAs: 'heatmap', swatch: null },
  boundedCluster: { drawsAs: 'cluster', swatch: swatch({ fill: '#0d9488', stroke: { color: '#134e4a', width: 1 } }) },
  serverCluster: { drawsAs: 'cluster', swatch: swatch({ fill: '#16a34a' }) },
  fallbackCluster: { drawsAs: 'cluster', swatch: swatch({ fill: '#9333ea' }) },
  symbolWithLeftoverClassification: { drawsAs: 'symbol', swatch: swatch() },
  mixedGeometry: { drawsAs: 'mixed', swatch: swatch({ fill: '#8b5cf6', fillOpacity: 0.4, stroke: DEFAULT_OUTLINE }) },
  raster: { drawsAs: 'raster', swatch: null },
  hillshadeDem: { drawsAs: 'hillshade', swatch: null },
  terrainDem: null,
  folderRow: null,
};

const graduated = (target: LegendClasses['target'], title: string, items: LegendClasses['items'], breaks: number[]): LegendClasses =>
  ({ mode: 'graduated', target, title, items, breaks });
const sized = (color: string, sizes: number[]) => sizes.map((size) => ({ color, size }));
const colored = (colors: string[]) => colors.map((color) => ({ color }));

const ZONING_CLASSES: LegendClasses = {
  mode: 'categorical',
  target: 'color',
  title: 'zone',
  items: [
    { color: '#66c2a5', label: 'Residential' },
    { color: '#fc8d62', label: 'Commercial' },
    { color: '#8da0cb', label: 'Industrial' },
  ],
  breaks: [],
};

/** The fixtures whose paint draws a classification; every other fixture has none. */
const fixtureClasses: Partial<Record<keyof typeof SAVED_LAYERS, LegendClasses[]>> = {
  categorical: [ZONING_CLASSES],
  graduatedColor: [graduated('color', 'pop', colored(['#fee8c8', '#fdbb84', '#e34a33']), [1000, 5000])],
  graduatedRadius: [graduated('radius', 'Magnitude', sized('#dc2626', [4, 8, 14]), [5, 6])],
  graduatedWidth: [graduated('width', 'flow', sized('#0284c7', [1, 3, 6]), [10, 100])],
};

/** A ramp built from a named ramp: its five map colours, evenly spaced. */
const builderRamp = (name: string, reversed = false): LegendRamp =>
  ({ colors: getRampColors(name, 5, reversed), stops: [0, 0.25, 0.5, 0.75, 1], mode: 'interpolate', name, reversed });
/** A ramp read from a stored heatmap-color expression. */
const storedRamp = (colors: string[], stops: number[], mode: LegendRamp['mode'] = 'interpolate'): LegendRamp =>
  ({ colors, stops, mode, name: null, reversed: false });

/** The heatmap fixtures' ramps and weight columns. */
const fixtureHeat: Partial<Record<keyof typeof SAVED_LAYERS, Pick<LegendFacts, 'ramp' | 'weightColumn'>>> = {
  heatmapByRamp: { ramp: builderRamp('Blues'), weightColumn: 'severity' },
  reversedHeatmap: { ramp: builderRamp('Viridis', true), weightColumn: null },
  heatmapByExpression: { ramp: storedRamp(['#7c3aed', '#f0abfc'], [0, 1]), weightColumn: null },
};

const fixtureRows: Row[] = Object.entries(SAVED_LAYERS).map(([key, layer]) => {
  const facts = fixtureFacts[key as keyof typeof SAVED_LAYERS];
  const classes = fixtureClasses[key as keyof typeof SAVED_LAYERS] ?? null;
  const heat = fixtureHeat[key as keyof typeof SAVED_LAYERS];
  return [key, layer, facts && { name: layer.display_name ?? '', ...facts, ...PLAIN, classes, ...heat }];
});

/** Facts for `savedLayer()`'s unstyled polygon under the given name. */
const unstyledPolygon = (name: string): LegendFacts => ({
  name,
  drawsAs: 'fill',
  swatch: swatch({ fill: MAP_COLORS.default.fill, fillOpacity: 0.3, stroke: DEFAULT_OUTLINE }),
  ...PLAIN,
});

const nameRows: Row[] = [
  ['null display name', savedLayer({ display_name: null, dataset_name: 'County parcels' }), unstyledPolygon('County parcels')],
  ['empty display name', savedLayer({ display_name: '', dataset_name: 'County parcels' }), unstyledPolygon('County parcels')],
  ['whitespace display name', savedLayer({ display_name: '   ', dataset_name: 'County parcels' }), unstyledPolygon('County parcels')],
  ['legendLabel override', savedLayer({ display_name: 'Parcels', style_config: { legendLabel: 'Tax parcels' } }), unstyledPolygon('Tax parcels')],
  ['whitespace legendLabel', savedLayer({ display_name: 'Parcels', style_config: { legendLabel: '  ' } }), unstyledPolygon('Parcels')],
  ['padded display name', savedLayer({ display_name: '  Parcels  ' }), unstyledPolygon('Parcels')],
  ['no usable name', savedLayer({ display_name: ' ', dataset_name: '' }), unstyledPolygon('')],
];

const terrainLabelRow: Row = [
  'terrain DEM with a legendLabel',
  { ...SAVED_LAYERS.terrainDem, style_config: { render_mode: 'terrain', legendLabel: 'Relief' } },
  null,
];

const polygon = (paint: Record<string, unknown>, builder?: BuilderStyleConfig) =>
  savedLayer({ paint, style_config: builder ? { builder } : null });
const point = (paint: Record<string, unknown>, builder?: BuilderStyleConfig) =>
  savedLayer({ dataset_geometry_type: 'MULTIPOINT', paint, style_config: builder ? { builder } : null });
const fillFacts = (overrides: Partial<LegendSwatch>): LegendFacts =>
  ({ name: 'Layer 1', drawsAs: 'fill', swatch: swatch({ fillOpacity: 0.3, ...overrides }), ...PLAIN });
const circleFacts = (overrides: Partial<LegendSwatch>): LegendFacts =>
  ({ name: 'Layer 1', drawsAs: 'circle', swatch: swatch(overrides), ...PLAIN });
const ring = { color: '#ea580c', width: 2 };

const swatchRows: Row[] = [
  ['polygon with a zero outline width', polygon({ 'fill-color': '#3b82f6', '_outline-width': 0 }), fillFacts({ fill: '#3b82f6' })],
  [
    'outline from the paint mirror',
    polygon({ 'fill-color': '#3b82f6', 'fill-opacity': 0.5, '_outline-color': '#ec4b7f', '_outline-width': 2 }),
    fillFacts({ fill: '#3b82f6', fillOpacity: 0.5, stroke: { color: '#ec4b7f', width: 2 } }),
  ],
  [
    'builder outline width over the paint mirror',
    polygon({ 'fill-color': '#3b82f6', '_outline-color': '#ec4b7f', '_outline-width': 2 }, { outlineWidth: 3 }),
    fillFacts({ fill: '#3b82f6', stroke: { color: '#ec4b7f', width: 3 } }),
  ],
  [
    'builder zero outline width over the paint mirror',
    polygon({ 'fill-color': '#3b82f6', '_outline-color': '#ec4b7f', '_outline-width': 2 }, { outlineWidth: 0 }),
    fillFacts({ fill: '#3b82f6' }),
  ],
  [
    'builder strokeDisabled over the paint mirror',
    polygon({ 'fill-color': '#3b82f6', '_outline-color': '#ec4b7f' }, { strokeDisabled: true, outlineColor: '#ec4b7f' }),
    fillFacts({ fill: '#3b82f6' }),
  ],
  [
    'builder outline colour over the paint mirror',
    polygon({ 'fill-color': '#3b82f6', '_outline-color': '#0058ac' }, { outlineColor: '#ec4b7f' }),
    fillFacts({ fill: '#3b82f6', stroke: { color: '#ec4b7f', width: 1 } }),
  ],
  [
    'legacy outline keys',
    polygon({ 'fill-color': '#3b82f6', 'outline-color': '#7c2d12', 'outline-width': 3 }),
    fillFacts({ fill: '#3b82f6', stroke: { color: '#7c2d12', width: 3 } }),
  ],
  [
    'snake_case builder outline keys',
    polygon({ 'fill-color': '#3b82f6' }, { outline_color: '#1d4ed8', outline_width: 2 } as unknown as BuilderStyleConfig),
    fillFacts({ fill: '#3b82f6', stroke: { color: '#1d4ed8', width: 2 } }),
  ],
  [
    'fill opacity from a data step, at its largest',
    polygon({ 'fill-color': '#3b82f6', 'fill-opacity': ['step', ['get', 'v'], 0.5, 10, 0.9] }),
    fillFacts({ fill: '#3b82f6', fillOpacity: 0.9, stroke: DEFAULT_OUTLINE }),
  ],
  [
    'fill opacity from a match, at its largest output and not its labels',
    polygon({ 'fill-color': '#3b82f6', 'fill-opacity': ['match', ['get', 'n'], 5, 0.2, 7, 0.6, 0.4] }),
    fillFacts({ fill: '#3b82f6', fillOpacity: 0.6, stroke: DEFAULT_OUTLINE }),
  ],
  [
    'fill opacity no output of which is a number',
    polygon({ 'fill-color': '#3b82f6', 'fill-opacity': ['get', 'alpha'] }),
    fillFacts({ fill: '#3b82f6', fillOpacity: 1, stroke: DEFAULT_OUTLINE }),
  ],
  [
    'line opacity faded in by zoom',
    savedLayer({ dataset_geometry_type: 'MULTILINESTRING', paint: { 'line-color': '#ef4444', 'line-opacity': ['interpolate', ['linear'], ['zoom'], 8, 0, 10, 0.8] } }),
    { name: 'Layer 1', drawsAs: 'line', swatch: swatch({ fill: '#ef4444', fillOpacity: 0.8 }), ...PLAIN },
  ],
  [
    'circle opacity from a zoom ramp over a data case',
    point({
      'circle-color': '#e2e8f0',
      'circle-opacity': ['interpolate', ['linear'], ['zoom'], 1.5, ['case', ['>=', ['get', 'pop'], 5000000], 0.9, 0.5], 4, 0.7],
    }),
    circleFacts({ fill: '#e2e8f0', fillOpacity: 0.9 }),
  ],
  ['layer opacity', savedLayer({ opacity: 0.5, paint: { 'fill-color': '#3b82f6' } }), fillFacts({ fill: '#3b82f6', opacity: 0.5, stroke: DEFAULT_OUTLINE })],
  [
    'pattern tinted from paint',
    polygon({ 'fill-pattern': 'geolens-fill-grid', 'fill-color': '#b91c1c' }),
    fillFacts({ fill: '#b91c1c', stroke: DEFAULT_OUTLINE, pattern: { id: 'geolens-fill-grid', tint: '#b91c1c' } }),
  ],
  [
    'pattern with nothing to tint it',
    polygon({ 'fill-pattern': 'geolens-fill-grid' }),
    fillFacts({ stroke: DEFAULT_OUTLINE, pattern: { id: 'geolens-fill-grid', tint: null } }),
  ],
  [
    'pattern id with no built-in preview',
    polygon({ 'fill-pattern': 'custom-sprite', 'fill-color': '#3b82f6' }),
    fillFacts({ fill: '#3b82f6', stroke: DEFAULT_OUTLINE }),
  ],
  [
    'point with a stale builder strokeDisabled',
    point({ 'circle-color': '#fff7ed', 'circle-stroke-color': '#ea580c', 'circle-stroke-width': 2 }, { strokeDisabled: true }),
    circleFacts({ fill: '#fff7ed', stroke: ring }),
  ],
  [
    'point ring colour with no width',
    point({ 'circle-color': '#fff7ed', 'circle-stroke-color': '#ea580c' }),
    circleFacts({ fill: '#fff7ed' }),
  ],
  [
    'point with a zero ring width',
    point({ 'circle-color': '#fff7ed', 'circle-stroke-color': '#ea580c', 'circle-stroke-width': 0 }),
    circleFacts({ fill: '#fff7ed' }),
  ],
  [
    'point ring width with no colour',
    point({ 'circle-color': '#fff7ed', 'circle-stroke-width': 2 }),
    circleFacts({ fill: '#fff7ed', stroke: { color: '#000000', width: 2 } }),
  ],
  [
    'point ring width from a data step, at its largest',
    point({ 'circle-color': '#fff7ed', 'circle-stroke-color': '#ea580c', 'circle-stroke-width': ['step', ['get', 'v'], 2, 10, 4] }),
    circleFacts({ fill: '#fff7ed', stroke: { color: '#ea580c', width: 4 } }),
  ],
  [
    'point ring grown in by zoom',
    point({ 'circle-color': '#fff7ed', 'circle-stroke-color': '#ea580c', 'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 10, 0, 14, 2] }),
    circleFacts({ fill: '#fff7ed', stroke: ring }),
  ],
  [
    'categories faded in by zoom',
    ZOOM_FADED_STATIONS,
    {
      name: 'Stations (green = ADA accessible)',
      drawsAs: 'circle',
      swatch: swatch({ fillOpacity: 0.95, stroke: { color: '#0b0f14', width: 1 } }),
      ...PLAIN,
      classes: [{
        mode: 'categorical',
        target: 'color',
        title: 'ada',
        items: [
          { color: '#22c55e', label: 'ADA accessible' },
          { color: '#a3e635', label: 'Partially accessible' },
          { color: '#94a3b8', label: 'Not accessible' },
        ],
        breaks: [],
      }],
    },
  ],
  [
    'polygon with no paint',
    savedLayer(),
    fillFacts({ fill: MAP_COLORS.default.fill, stroke: DEFAULT_OUTLINE }),
  ],
  [
    'point with no paint',
    point({}),
    circleFacts({ fill: MAP_COLORS.default.fill, stroke: { color: MAP_COLORS.default.stroke, width: 1 } }),
  ],
  [
    'line with no paint',
    savedLayer({ dataset_geometry_type: 'MULTILINESTRING' }),
    { name: 'Layer 1', drawsAs: 'line', swatch: swatch({ fill: MAP_COLORS.default.fill }), ...PLAIN },
  ],
  [
    'patterned GEOMETRYCOLLECTION layer',
    savedLayer({ dataset_geometry_type: 'GEOMETRYCOLLECTION', paint: { 'fill-pattern': 'geolens-fill-grid', 'fill-color': '#8b5cf6' } }),
    {
      name: 'Layer 1',
      drawsAs: 'mixed',
      swatch: swatch({ fill: '#8b5cf6', fillOpacity: 0.3, stroke: DEFAULT_OUTLINE, pattern: { id: 'geolens-fill-grid', tint: '#8b5cf6' } }),
      ...PLAIN,
    },
  ],
  [
    'mixed layer with builder stroke state',
    savedLayer({
      dataset_geometry_type: 'GEOMETRY',
      paint: { 'fill-color': '#8b5cf6' },
      style_config: { builder: { strokeDisabled: true, outlineColor: '#ec4b7f' } },
    }),
    { name: 'Layer 1', drawsAs: 'mixed', swatch: swatch({ fill: '#8b5cf6', fillOpacity: 0.3, stroke: DEFAULT_OUTLINE }), ...PLAIN },
  ],
  [
    'no geometry, circle paint',
    savedLayer({ dataset_geometry_type: null, paint: { 'circle-color': '#fff7ed' } }),
    circleFacts({ fill: '#fff7ed' }),
  ],
];

type ClassRow = [label: string, layer: MapLayerResponse, expected: LegendClasses[] | null];

const kindMatch = ['match', ['get', 'kind'], 'school', '#f472b6', 'clinic', '#60a5fa', '#cccccc'];
const categoricalPoint = (overrides: Partial<MapLayerResponse> = {}) => savedLayer({
  dataset_geometry_type: 'MULTIPOINT',
  paint: { 'circle-radius': 5, 'circle-color': kindMatch },
  style_config: {
    mode: 'categorical',
    column: 'kind',
    categories: [
      { value: 'school', label: 'School', color: '#f472b6' },
      { value: 'clinic', label: 'Clinic', color: '#60a5fa' },
    ],
  },
  ...overrides,
});
const KIND_CLASSES: LegendClasses = {
  mode: 'categorical',
  target: 'color',
  title: 'kind',
  items: [{ color: '#f472b6', label: 'School' }, { color: '#60a5fa', label: 'Clinic' }],
  breaks: [],
};
const depthColor = [
  'interpolate', ['linear'], ['coalesce', ['to-number', ['get', 'depth_km']], 0],
  0, '#fde725', 50, '#f39c12', 200, '#e74c3c', 700, '#7d3c98',
];
const magnitudeRadius = ['step', ['get', 'mag'], 4, 6, 8, 7, 14];
const sizedByMagnitude = (circleColor: unknown) => savedLayer({
  dataset_geometry_type: 'MULTIPOINT',
  paint: { 'circle-radius': magnitudeRadius, 'circle-color': circleColor },
  style_config: { mode: 'graduated', column: 'mag', target: 'radius', sizes: [4, 8, 14], breaks: [6, 7], sizeLabel: 'Magnitude', colorLabel: 'Depth (km)' },
});
/** The graduated-colour fixture with its fill-color replaced. */
const graduatedPop = (fillColor: unknown) => ({ ...SAVED_LAYERS.graduatedColor, paint: { 'fill-color': fillColor } });

/** Magnitude size classes coloured by a step on magnitude at the same breaks, over the given size paint. */
const magnitudeSizedBy = (circleRadius: unknown) => savedLayer({
  dataset_geometry_type: 'MULTIPOINT',
  paint: { 'circle-radius': circleRadius, 'circle-color': ['step', ['get', 'mag'], '#fee8c8', 6, '#fdbb84', 7, '#e34a33'] },
  style_config: { mode: 'graduated', column: 'mag', target: 'radius', sizes: [4, 8, 14], breaks: [6, 7], sizeLabel: 'Magnitude' },
});
const MAGNITUDE_SIZES = (color: string) => graduated('radius', 'Magnitude', sized(color, [4, 8, 14]), [6, 7]);
const DEPTH_COLORS = graduated('color', 'Depth (km)', colored(['#fde725', '#f39c12', '#e74c3c', '#7d3c98']), [50, 200, 700]);

const classRows: ClassRow[] = [
  [
    'categories the paint no longer draws',
    { ...SAVED_LAYERS.categorical, paint: { 'fill-color': '#66c2a5', 'fill-opacity': 0.7 } },
    null,
  ],
  [
    'categories of a column the paint does not read',
    categoricalPoint({ paint: { 'circle-radius': 5, 'circle-color': ['match', ['get', 'use'], 'school', '#f472b6', '#cccccc'] } }),
    null,
  ],
  ['categories on a cluster layer', categoricalPoint({ style_config: { ...categoricalPoint().style_config, render_mode: 'cluster' } }), [KIND_CLASSES]],
  ['categories on a heatmap layer', categoricalPoint({ style_config: { ...categoricalPoint().style_config, render_mode: 'heatmap' } }), null],
  ['categories with no geometry', categoricalPoint({ dataset_geometry_type: null }), [KIND_CLASSES]],
  [
    'categories without labels',
    categoricalPoint({
      style_config: {
        mode: 'categorical',
        column: 'kind',
        categories: [{ value: 'school', color: '#f472b6' }, { value: 3, color: '#60a5fa' }, { value: null, color: '#cccccc' }],
      },
    }),
    [{ ...KIND_CLASSES, items: [{ color: '#f472b6', label: 'school' }, { color: '#60a5fa', label: '3' }, { color: '#cccccc', label: 'null' }] }],
  ],
  ['a categorical mode with no categories', categoricalPoint({ style_config: { mode: 'categorical', column: 'kind', categories: [] } }), null],
  [
    'graduated colours without breaks',
    { ...SAVED_LAYERS.graduatedColor, style_config: { ...SAVED_LAYERS.graduatedColor.style_config, breaks: undefined } },
    [graduated('color', 'pop', colored(['#fee8c8', '#fdbb84', '#e34a33']), [])],
  ],
  [
    'a title from a snake_case column',
    {
      ...SAVED_LAYERS.graduatedColor,
      paint: { 'fill-color': ['step', ['get', '_median_mhi'], '#fee8c8', 50000, '#e34a33'] },
      style_config: { mode: 'graduated', column: '_median_mhi', colors: ['#fee8c8', '#e34a33'], breaks: [50000] },
    },
    [graduated('color', 'median income', colored(['#fee8c8', '#e34a33']), [50000])],
  ],
  ['radius classes painted in one colour', sizedByMagnitude('#ef4444'), [MAGNITUDE_SIZES('#ef4444')]],
  ['radius classes coloured by another column', sizedByMagnitude(depthColor), [MAGNITUDE_SIZES('#fde725'), DEPTH_COLORS]],
  [
    'radius classes coloured by the same column at the same breaks',
    sizedByMagnitude(['step', ['get', 'mag'], '#fee8c8', 6, '#fdbb84', 7, '#e34a33']),
    [graduated('radius', 'Magnitude', [{ color: '#fee8c8', size: 4 }, { color: '#fdbb84', size: 8 }, { color: '#e34a33', size: 14 }], [6, 7])],
  ],
  [
    "the showcase's earthquakes, sized and coloured by magnitude at the same breaks",
    savedLayer({
      dataset_geometry_type: 'MULTIPOINT',
      paint: {
        'circle-radius': [
          'interpolate', ['linear'], ['zoom'],
          1.2, ['step', ['to-number', ['get', 'mag'], 0], 2.5, 5.0, 4.5, 6.0, 7, 7.0, 11],
          6, ['step', ['to-number', ['get', 'mag'], 0], 5, 5.0, 9, 6.0, 14, 7.0, 22],
        ],
        'circle-color': ['step', ['to-number', ['get', 'mag'], 0], '#fecc5c', 5.0, '#fd8d3c', 6.0, '#f03b20', 7.0, '#bd0026'],
      },
      style_config: { mode: 'graduated', target: 'radius', column: 'mag', breaks: [5, 6, 7], sizes: [3, 5, 8, 12], sizeLabel: 'Magnitude' },
    }),
    [graduated('radius', 'Magnitude', [
      { color: '#fecc5c', size: 3 },
      { color: '#fd8d3c', size: 5 },
      { color: '#f03b20', size: 8 },
      { color: '#bd0026', size: 12 },
    ], [5, 6, 7])],
  ],
  [
    'radius classes with an interpolated colour on the same column and breaks',
    savedLayer({
      dataset_geometry_type: 'MULTIPOINT',
      paint: { 'circle-radius': magnitudeRadius, 'circle-color': ['interpolate', ['linear'], ['get', 'mag'], 5, '#fee8c8', 6, '#fdbb84', 7, '#e34a33'] },
      style_config: { mode: 'graduated', column: 'mag', target: 'radius', sizes: [4, 8, 14], breaks: [6, 7], sizeLabel: 'Magnitude' },
    }),
    [MAGNITUDE_SIZES('#fee8c8'), graduated('color', 'Magnitude', colored(['#fee8c8', '#fdbb84', '#e34a33']), [6, 7])],
  ],
  [
    'radius classes whose size paint steps on a shifted column',
    magnitudeSizedBy(['step', ['+', ['get', 'mag'], 1], 4, 6, 8, 7, 14]),
    [MAGNITUDE_SIZES('#fee8c8'), graduated('color', 'Magnitude', colored(['#fee8c8', '#fdbb84', '#e34a33']), [6, 7])],
  ],
  [
    'radius classes whose size paint steps at other breaks',
    magnitudeSizedBy(['step', ['get', 'mag'], 4, 5, 8, 8, 14]),
    [MAGNITUDE_SIZES('#fee8c8'), graduated('color', 'Magnitude', colored(['#fee8c8', '#fdbb84', '#e34a33']), [6, 7])],
  ],
  [
    'radius classes whose size paint is a constant',
    magnitudeSizedBy(6),
    [MAGNITUDE_SIZES('#fee8c8'), graduated('color', 'Magnitude', colored(['#fee8c8', '#fdbb84', '#e34a33']), [6, 7])],
  ],
  [
    "the style builders' guarded size and colour steps at the same breaks",
    savedLayer({
      dataset_geometry_type: 'MULTIPOINT',
      paint: {
        'circle-radius': buildGraduatedSizeExpression('mag', [6, 7], [4, 8, 14]),
        'circle-color': buildGraduatedExpression('mag', [6, 7], ['#fee8c8', '#fdbb84', '#e34a33']),
      },
      style_config: { mode: 'graduated', column: 'mag', target: 'radius', sizes: [4, 8, 14], breaks: [6, 7], sizeLabel: 'Magnitude' },
    }),
    [graduated('radius', 'Magnitude', [{ color: '#fee8c8', size: 4 }, { color: '#fdbb84', size: 8 }, { color: '#e34a33', size: 14 }], [6, 7])],
  ],
  [
    'radius classes coloured by the same column at other breaks',
    savedLayer({
      dataset_geometry_type: 'MULTIPOINT',
      paint: { 'circle-radius': magnitudeRadius, 'circle-color': ['step', ['get', 'mag'], '#fee8c8', 5, '#fdbb84', 8, '#e34a33'] },
      style_config: { mode: 'graduated', column: 'mag', target: 'radius', sizes: [4, 8, 14], breaks: [6, 7], sizeLabel: 'Magnitude' },
    }),
    [MAGNITUDE_SIZES('#fee8c8'), graduated('color', 'Magnitude', colored(['#fee8c8', '#fdbb84', '#e34a33']), [5, 8])],
  ],
  [
    "radius classes over the builder's graduated colour",
    savedLayer({
      dataset_geometry_type: 'MULTIPOINT',
      paint: {
        'circle-radius': buildGraduatedSizeExpression('mag', [6, 7], [4, 8, 14]),
        'circle-color': buildGraduatedExpression('depth_km', [50, 200], ['#fee8c8', '#fdbb84', '#e34a33']),
      },
      style_config: { mode: 'graduated', column: 'mag', target: 'radius', sizes: [4, 8, 14], breaks: [6, 7] },
    }),
    [
      graduated('radius', 'mag', sized('#fee8c8', [4, 8, 14]), [6, 7]),
      graduated('color', 'depth km', colored(['#fee8c8', '#fdbb84', '#e34a33']), [50, 200]),
    ],
  ],
  [
    'radius classes over a case that is not a null guard',
    sizedByMagnitude(['case', ['>', ['get', 'depth_km'], 100], '#e34a33', ['step', ['get', 'depth_km'], '#fee8c8', 50, '#fdbb84']]),
    [MAGNITUDE_SIZES(MAP_COLORS.fallback)],
  ],
  [
    'radius classes over a null-guarded zoom ramp',
    sizedByMagnitude(['case', ['==', ['get', 'foo'], null], '#cccccc', ['step', ['zoom'], '#fee8c8', 10, '#e34a33']]),
    [MAGNITUDE_SIZES(MAP_COLORS.fallback)],
  ],
  [
    'radius classes over a null guard on another column than its ramp',
    sizedByMagnitude(['case', ['==', ['get', 'depth_km'], null], '#cccccc', ['step', ['get', 'basin'], '#fee8c8', 3, '#e34a33']]),
    [MAGNITUDE_SIZES(MAP_COLORS.fallback)],
  ],
  [
    'radius classes over a zoom step with a stray get after its stops',
    sizedByMagnitude(['step', ['zoom'], '#fee8c8', 10, '#e34a33', ['get', 'depth_km'], '#7d3c98']),
    [MAGNITUDE_SIZES(MAP_COLORS.fallback)],
  ],
  [
    'radius classes with a zoom-stepped colour',
    sizedByMagnitude(['step', ['zoom'], '#fee8c8', 10, '#e34a33']),
    [MAGNITUDE_SIZES(MAP_COLORS.fallback)],
  ],
  [
    'radius classes coloured by a step on a shifted column',
    sizedByMagnitude(['step', ['+', ['get', 'mag'], 1], '#fee8c8', 6, '#fdbb84', 7, '#e34a33']),
    [MAGNITUDE_SIZES(MAP_COLORS.fallback)],
  ],
  [
    'radius classes coloured by a number coercion of the same column',
    sizedByMagnitude(['step', ['number', ['get', 'mag']], '#fee8c8', 6, '#fdbb84', 7, '#e34a33']),
    [graduated('radius', 'Magnitude', [{ color: '#fee8c8', size: 4 }, { color: '#fdbb84', size: 8 }, { color: '#e34a33', size: 14 }], [6, 7])],
  ],
  [
    'radius classes coloured through a coalesce of two columns',
    sizedByMagnitude(['step', ['coalesce', ['get', 'mag'], ['get', 'mag_estimate']], '#fee8c8', 6, '#fdbb84', 7, '#e34a33']),
    [MAGNITUDE_SIZES(MAP_COLORS.fallback)],
  ],
  [
    'radius classes coloured through a let binding',
    sizedByMagnitude(['let', 'm', ['get', 'mag'], ['step', ['var', 'm'], '#fee8c8', 6, '#fdbb84', 7, '#e34a33']]),
    [MAGNITUDE_SIZES(MAP_COLORS.fallback)],
  ],
  [
    'width classes with a data-driven line colour',
    {
      ...SAVED_LAYERS.graduatedWidth,
      paint: { ...SAVED_LAYERS.graduatedWidth.paint, 'line-color': ['step', ['get', 'basin'], '#bae6fd', 3, '#0369a1'] },
    },
    [graduated('width', 'flow', sized('#bae6fd', [1, 3, 6]), [10, 100]), graduated('color', 'basin', colored(['#bae6fd', '#0369a1']), [3])],
  ],
  [
    'graduated colours the paint no longer draws',
    graduatedPop(['case', ['==', ['get', 'pop'], null], '#cccccc', ['step', ['get', 'pop'], '#000000', 1000, '#fdbb84', 5000, '#e34a33']]),
    null,
  ],
  [
    'graduated breaks the paint no longer uses',
    graduatedPop(['case', ['==', ['get', 'pop'], null], '#cccccc', ['step', ['get', 'pop'], '#fee8c8', 1000, '#fdbb84', 6000, '#e34a33']]),
    null,
  ],
  [
    'graduated colours over paint the legend cannot read',
    graduatedPop(['match', ['get', 'pop'], 0, '#fee8c8', '#e34a33']),
    [graduated('color', 'pop', colored(['#fee8c8', '#fdbb84', '#e34a33']), [1000, 5000])],
  ],
  [
    'a graduated mode with neither colours nor sizes',
    { ...SAVED_LAYERS.graduatedColor, style_config: { mode: 'graduated', column: 'pop', breaks: [1000] } },
    null,
  ],
];

describe('legendFacts', () => {
  it.each([...fixtureRows, ...nameRows, terrainLabelRow, ...swatchRows])(
    '%s gives the same facts in the builder and viewer shapes',
    (_label, layer, expected) => {
      expect(legendFacts(layer)).toEqual(expected);
      expect(legendFacts(toSharedLayer(layer))).toEqual(expected);
    },
  );
});

describe('legendFacts classes', () => {
  it.each(classRows)('%s gives the same classes in the builder and viewer shapes', (_label, layer, expected) => {
    expect(legendFacts(layer)?.classes).toEqual(expected);
    expect(legendFacts(toSharedLayer(layer))?.classes).toEqual(expected);
  });
});

type HeatRow = [label: string, layer: MapLayerResponse, expected: Pick<LegendFacts, 'ramp' | 'weightColumn'>];

const heatmap = (paint: Record<string, unknown>, style_config: Record<string, unknown> = {}) => savedLayer({
  dataset_geometry_type: 'MULTIPOINT',
  paint: { 'heatmap-radius': 30, ...paint },
  style_config: { mode: 'graduated', column: '', render_mode: 'heatmap', ...style_config },
});

const heatRows: HeatRow[] = [
  ['no ramp at all', heatmap({}), { ramp: builderRamp('YlOrRd'), weightColumn: null }],
  [
    'a stored expression over a reversed builder ramp',
    heatmap(
      { 'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(0,0,0,0)', 0.5, '#7c3aed', 1, '#f0abfc'] },
      { builder: { heatmapRamp: 'Blues', heatmapReversed: true } },
    ),
    { ramp: storedRamp(['#7c3aed', '#f0abfc'], [0, 1]), weightColumn: null },
  ],
  [
    'a builder ramp over a stale top-level ramp',
    heatmap({}, { ramp: 'YlOrRd', builder: { heatmapRamp: 'Viridis' } }),
    { ramp: builderRamp('Viridis'), weightColumn: null },
  ],
  [
    'a builder ramp over a leftover paint mirror',
    heatmap({ '_heatmap-ramp': 'Blues', '_heatmap-reversed': true }, { builder: { heatmapRamp: 'YlOrRd' } }),
    { ramp: builderRamp('YlOrRd'), weightColumn: null },
  ],
  [
    'snake_case builder keys, with no weight in the paint',
    heatmap({}, { builder: { heatmap_ramp: 'Blues', heatmap_reversed: true, heatmap_weight_column: 'mag' } }),
    { ramp: builderRamp('Blues', true), weightColumn: null },
  ],
  [
    'a stale builder weight column over a constant weight',
    heatmap({ 'heatmap-weight': 1 }, { builder: { heatmapWeightColumn: 'severity' } }),
    { ramp: builderRamp('YlOrRd'), weightColumn: null },
  ],
  [
    'a stale builder weight column over another column',
    heatmap({ 'heatmap-weight': ['get', 'calls'] }, { builder: { heatmapWeightColumn: 'severity' } }),
    { ramp: builderRamp('YlOrRd'), weightColumn: 'calls' },
  ],
  [
    'a coerced weight column',
    heatmap({ 'heatmap-weight': ['to-number', ['get', 'mag'], 0] }),
    { ramp: builderRamp('YlOrRd'), weightColumn: 'mag' },
  ],
  [
    'a weight ramp over a column',
    heatmap({ 'heatmap-weight': ['interpolate', ['linear'], ['to-number', ['get', 'mag'], 0], 2.5, 0.05, 8, 1] }),
    { ramp: builderRamp('YlOrRd'), weightColumn: null },
  ],
  [
    'a stored ramp with an opaque colour at zero density',
    heatmap({ 'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, '#0000ff', 1, '#ff0000'] }),
    { ramp: storedRamp(['#0000ff', '#ff0000'], [0, 1]), weightColumn: null },
  ],
  [
    'a stored ramp with a transparent colour at zero density',
    heatmap({ 'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(0,0,0,0)', 1, '#ff0000'] }),
    { ramp: storedRamp(['#ff0000'], [0]), weightColumn: null },
  ],
  [
    'a stored ramp with a zero-alpha hex at zero density',
    heatmap({ 'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, '#2166ac00', 0.5, '#67a9cf', 1, '#ef8a62'] }),
    { ramp: storedRamp(['#67a9cf', '#ef8a62'], [0, 1]), weightColumn: null },
  ],
  [
    'a stored ramp with uneven stops',
    heatmap({ 'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, '#0000ff', 0.1, '#00ff00', 1, '#ff0000'] }),
    { ramp: storedRamp(['#0000ff', '#00ff00', '#ff0000'], [0, 0.1, 1]), weightColumn: null },
  ],
  [
    'a stored ramp whose stops start above zero density',
    heatmap({ 'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0.5, '#0000ff', 0.75, '#00ff00', 1, '#ff0000'] }),
    { ramp: storedRamp(['#0000ff', '#00ff00', '#ff0000'], [0, 0.5, 1]), weightColumn: null },
  ],
  [
    'a stored exponential ramp',
    heatmap({ 'heatmap-color': ['interpolate', ['exponential', 2], ['heatmap-density'], 0, 'rgba(0,0,0,0)', 1, '#ff0000'] }),
    { ramp: null, weightColumn: null },
  ],
  [
    'a stored ramp blended in HCL',
    heatmap({ 'heatmap-color': ['interpolate-hcl', ['linear'], ['heatmap-density'], 0, 'rgba(0,0,0,0)', 1, '#ff0000'] }),
    { ramp: null, weightColumn: null },
  ],
  [
    'a stored ramp blended in Lab',
    heatmap({ 'heatmap-color': ['interpolate-lab', ['linear'], ['heatmap-density'], 0, 'rgba(0,0,0,0)', 1, '#ff0000'] }),
    { ramp: null, weightColumn: null },
  ],
  [
    'a stored ramp over zoom instead of density',
    heatmap({ 'heatmap-color': ['interpolate', ['linear'], ['zoom'], 0, '#0000ff', 10, '#ff0000'] }),
    { ramp: null, weightColumn: null },
  ],
  [
    'a stored step colour',
    heatmap({ 'heatmap-color': ['step', ['heatmap-density'], 'rgba(0,0,0,0)', 0.3, '#fde725', 0.7, '#440154'] }),
    { ramp: storedRamp(['rgba(0,0,0,0)', '#fde725', '#440154'], [0, 0.3, 0.7], 'step'), weightColumn: null },
  ],
  [
    'a stored single colour',
    heatmap({ 'heatmap-color': '#dc2626' }),
    { ramp: storedRamp(['#dc2626'], [0]), weightColumn: null },
  ],
  ['a stored expression with no colours to read', heatmap({ 'heatmap-color': ['get', 'color'] }), { ramp: null, weightColumn: null }],
  ['an empty weight column', heatmap({}, { builder: { heatmapWeightColumn: '' } }), { ramp: builderRamp('YlOrRd'), weightColumn: null }],
  [
    'a weight column left on a layer that is not a heatmap',
    savedLayer({ dataset_geometry_type: 'MULTIPOINT', paint: { 'circle-color': '#f59e0b' }, style_config: { builder: { heatmapWeightColumn: 'mag' } } }),
    { ramp: null, weightColumn: null },
  ],
];

describe('legendFacts heatmap ramp', () => {
  it.each(heatRows)('%s gives the same ramp and weight column in the builder and viewer shapes', (_label, layer, expected) => {
    for (const shape of [layer, toSharedLayer(layer)]) {
      const facts = legendFacts(shape);
      expect({ ramp: facts?.ramp, weightColumn: facts?.weightColumn }).toEqual(expected);
    }
  });
});
