import { describe, expect, it } from 'vitest';
import { buildGraduatedExpression, buildGraduatedSizeExpression } from '@/lib/color-ramps';
import { MAP_COLORS } from '@/lib/map-colors';
import type { BuilderStyleConfig, MapLayerResponse } from '@/types/api';
import { SAVED_LAYERS, savedLayer, toSharedLayer } from '@/test/fixtures/saved-layers';
import { legendFacts, type LegendClasses, type LegendFacts, type LegendSwatch } from '../legend-facts';

type Row = [label: string, layer: MapLayerResponse, expected: LegendFacts | null];

/** The outline the fill and mixed adapters draw when the style sets none. */
const DEFAULT_OUTLINE = { color: MAP_COLORS.default.stroke, width: 1 };

function swatch(overrides: Partial<LegendSwatch> = {}): LegendSwatch {
  return { fill: null, fillOpacity: 1, opacity: 1, stroke: null, pattern: null, ...overrides };
}

const fixtureFacts: Record<keyof typeof SAVED_LAYERS, Omit<LegendFacts, 'name' | 'classes'> | null> = {
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

const fixtureRows: Row[] = Object.entries(SAVED_LAYERS).map(([key, layer]) => {
  const facts = fixtureFacts[key as keyof typeof SAVED_LAYERS];
  const classes = fixtureClasses[key as keyof typeof SAVED_LAYERS] ?? null;
  return [key, layer, facts && { name: layer.display_name ?? '', ...facts, classes }];
});

/** Facts for `savedLayer()`'s unstyled polygon under the given name. */
const unstyledPolygon = (name: string): LegendFacts => ({
  name,
  drawsAs: 'fill',
  swatch: swatch({ fill: MAP_COLORS.default.fill, fillOpacity: 0.3, stroke: DEFAULT_OUTLINE }),
  classes: null,
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
  ({ name: 'Layer 1', drawsAs: 'fill', swatch: swatch({ fillOpacity: 0.3, ...overrides }), classes: null });
const circleFacts = (overrides: Partial<LegendSwatch>): LegendFacts =>
  ({ name: 'Layer 1', drawsAs: 'circle', swatch: swatch(overrides), classes: null });
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
    'fill opacity from an expression',
    polygon({ 'fill-color': '#3b82f6', 'fill-opacity': ['step', ['get', 'v'], 0.5, 10, 0.9] }),
    fillFacts({ fill: '#3b82f6', fillOpacity: 0.5, stroke: DEFAULT_OUTLINE }),
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
    'point ring width from an expression',
    point({ 'circle-color': '#fff7ed', 'circle-stroke-color': '#ea580c', 'circle-stroke-width': ['step', ['get', 'v'], 2, 10, 4] }),
    circleFacts({ fill: '#fff7ed', stroke: ring }),
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
    { name: 'Layer 1', drawsAs: 'line', swatch: swatch({ fill: MAP_COLORS.default.fill }), classes: null },
  ],
  [
    'patterned GEOMETRYCOLLECTION layer',
    savedLayer({ dataset_geometry_type: 'GEOMETRYCOLLECTION', paint: { 'fill-pattern': 'geolens-fill-grid', 'fill-color': '#8b5cf6' } }),
    {
      name: 'Layer 1',
      drawsAs: 'mixed',
      swatch: swatch({ fill: '#8b5cf6', fillOpacity: 0.3, stroke: DEFAULT_OUTLINE, pattern: { id: 'geolens-fill-grid', tint: '#8b5cf6' } }),
      classes: null,
    },
  ],
  [
    'mixed layer with builder stroke state',
    savedLayer({
      dataset_geometry_type: 'GEOMETRY',
      paint: { 'fill-color': '#8b5cf6' },
      style_config: { builder: { strokeDisabled: true, outlineColor: '#ec4b7f' } },
    }),
    { name: 'Layer 1', drawsAs: 'mixed', swatch: swatch({ fill: '#8b5cf6', fillOpacity: 0.3, stroke: DEFAULT_OUTLINE }), classes: null },
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
    'radius classes coloured by the same column',
    sizedByMagnitude(['step', ['get', 'mag'], '#fee8c8', 6, '#fdbb84', 7, '#e34a33']),
    [MAGNITUDE_SIZES('#fee8c8'), graduated('color', 'Depth (km)', colored(['#fee8c8', '#fdbb84', '#e34a33']), [6, 7])],
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
    [MAGNITUDE_SIZES('#fee8c8')],
  ],
  [
    'radius classes with a zoom-stepped colour',
    sizedByMagnitude(['step', ['zoom'], '#fee8c8', 10, '#e34a33']),
    [MAGNITUDE_SIZES('#fee8c8')],
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
