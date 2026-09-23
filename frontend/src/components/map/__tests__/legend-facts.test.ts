import { describe, expect, it } from 'vitest';
import { MAP_COLORS } from '@/lib/map-colors';
import type { BuilderStyleConfig, MapLayerResponse } from '@/types/api';
import { SAVED_LAYERS, savedLayer, toSharedLayer } from '@/test/fixtures/saved-layers';
import { legendFacts, type LegendFacts, type LegendSwatch } from '../legend-facts';

type Row = [label: string, layer: MapLayerResponse, expected: LegendFacts | null];

/** The outline the fill and mixed adapters draw when the style sets none. */
const DEFAULT_OUTLINE = { color: MAP_COLORS.default.stroke, width: 1 };

function swatch(overrides: Partial<LegendSwatch> = {}): LegendSwatch {
  return { fill: null, fillOpacity: 1, opacity: 1, stroke: null, pattern: null, ...overrides };
}

const fixtureFacts: Record<keyof typeof SAVED_LAYERS, Omit<LegendFacts, 'name'> | null> = {
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

const fixtureRows: Row[] = Object.entries(SAVED_LAYERS).map(([key, layer]) => {
  const facts = fixtureFacts[key as keyof typeof SAVED_LAYERS];
  return [key, layer, facts && { name: layer.display_name ?? '', ...facts }];
});

/** Facts for `savedLayer()`'s unstyled polygon under the given name. */
const unstyledPolygon = (name: string): LegendFacts =>
  ({ name, drawsAs: 'fill', swatch: swatch({ fill: MAP_COLORS.default.fill, fillOpacity: 0.3, stroke: DEFAULT_OUTLINE }) });

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
  ({ name: 'Layer 1', drawsAs: 'fill', swatch: swatch({ fillOpacity: 0.3, ...overrides }) });
const circleFacts = (overrides: Partial<LegendSwatch>): LegendFacts =>
  ({ name: 'Layer 1', drawsAs: 'circle', swatch: swatch(overrides) });
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
    { name: 'Layer 1', drawsAs: 'line', swatch: swatch({ fill: MAP_COLORS.default.fill }) },
  ],
  [
    'patterned GEOMETRYCOLLECTION layer',
    savedLayer({ dataset_geometry_type: 'GEOMETRYCOLLECTION', paint: { 'fill-pattern': 'geolens-fill-grid', 'fill-color': '#8b5cf6' } }),
    {
      name: 'Layer 1',
      drawsAs: 'mixed',
      swatch: swatch({ fill: '#8b5cf6', fillOpacity: 0.3, stroke: DEFAULT_OUTLINE, pattern: { id: 'geolens-fill-grid', tint: '#8b5cf6' } }),
    },
  ],
  [
    'mixed layer with builder stroke state',
    savedLayer({
      dataset_geometry_type: 'GEOMETRY',
      paint: { 'fill-color': '#8b5cf6' },
      style_config: { builder: { strokeDisabled: true, outlineColor: '#ec4b7f' } },
    }),
    { name: 'Layer 1', drawsAs: 'mixed', swatch: swatch({ fill: '#8b5cf6', fillOpacity: 0.3, stroke: DEFAULT_OUTLINE }) },
  ],
  [
    'no geometry, circle paint',
    savedLayer({ dataset_geometry_type: null, paint: { 'circle-color': '#fff7ed' } }),
    circleFacts({ fill: '#fff7ed' }),
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
