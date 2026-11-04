// Every opacity the adapters draw must reach zero when the fade factor does, so a
// key an adapter sets from something other than the layer opacity can't be forgotten.
import { adapterInputFor, describeLayers } from '@/components/builder/layer-description';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import { syncRenderContext } from '@/components/builder/map-sync';
import type { SharedLayerResponse } from '@/types/api';
import { Color, validateStyleMin } from '@maplibre/maplibre-gl-style-spec';
import { toViewerSyncInput } from '../ViewerMap';

const BASE = {
  id: 'l1',
  dataset_id: 'ds',
  dataset_name: 'Data',
  display_name: 'Data',
  table_name: 'data',
  geometry_type: 'POINT',
  column_info: null,
  sort_order: 0,
  visible: true,
  show_in_legend: true,
  opacity: 0.8,
  paint: {},
  layout: {},
  filter: null,
  label_config: null,
  popup_config: null,
  style_config: null,
  tile_url: '',
} as unknown as SharedLayerResponse;

const LABEL = { column: 'name', textOpacity: 0.9 };
const ZOOM_LABEL = { column: 'name', textOpacity: ['interpolate', ['linear'], ['zoom'], 5, 0, 8, 0.9] };

const CASE_OPACITY = ['case', ['has', 'x'], 1, 0.3];
const MATCH_OPACITY = ['match', ['get', 'kind'], 'a', 1, 0.5];
const SUM_OPACITY = ['+', ['get', 'a'], 0.1];
const STOPS_WITH_EXPRESSIONS = ['interpolate', ['linear'], ['zoom'], 5, ['get', 'a'], 10, 1];
const STEPS_WITH_EXPRESSIONS = ['step', ['zoom'], ['get', 'a'], 8, 0.9];

// Feature-based expressions don't interpolate in MapLibre, so those keys snap rather than fade.
const EXPRESSION_CASES: [string, string, Partial<SharedLayerResponse>][] = [
  ...[
    ['case', CASE_OPACITY],
    ['match', MATCH_OPACITY],
    ['arithmetic', SUM_OPACITY],
    ['interpolate with expression outputs', STOPS_WITH_EXPRESSIONS],
    ['step with expression outputs', STEPS_WITH_EXPRESSIONS],
  ].flatMap(([name, expression]) => [
    ['circle', `circle fill opacity as a ${name}`, { paint: { 'circle-opacity': expression } }],
    ['circle', `circle ring opacity as a ${name}`, { paint: { 'circle-stroke-width': 2, 'circle-stroke-opacity': expression } }],
    ['circle', `circle label opacity as a ${name}`, { label_config: { column: 'name', textOpacity: expression } as never }],
    ['symbol', `symbol text opacity as a ${name}`, { style_config: { render_mode: 'symbol' } as never, label_config: { column: 'name', textOpacity: expression } as never }],
    ['mixed', `mixed point opacity as a ${name}`, { geometry_type: 'GEOMETRY', paint: { 'circle-opacity': expression } }],
    ['cluster', `unclustered point opacity as a ${name}`, { feature_count: 5_000_000, style_config: { render_mode: 'cluster' } as never, paint: { 'circle-opacity': expression } }],
  ] as [string, string, Partial<SharedLayerResponse>][]),
];

const CASES: [string, string, Partial<SharedLayerResponse>][] = [
  ...EXPRESSION_CASES,
  ['circle', 'circle', { paint: { 'circle-color': '#222', 'circle-stroke-width': 2, 'circle-stroke-opacity': 0.5 } }],
  ['circle', 'circle with a default paint', {}],
  ['circle', 'circle with a zoom-interpolated opacity', { paint: { 'circle-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.2, 10, 0.9] } }],
  ['circle', 'circle with a data-driven opacity', { paint: { 'circle-opacity': ['get', 'o'] } }],
  ['circle', 'circle with a zoom-stepped ring opacity', { paint: { 'circle-stroke-width': 2, 'circle-stroke-opacity': ['step', ['zoom'], 0.2, 8, 0.9] } }],
  ['mixed', 'mixed geometry with a zoom-stepped point opacity', { geometry_type: 'GEOMETRY', paint: { 'circle-opacity': ['step', ['zoom'], 0.2, 8, 0.9] } }],
  ['cluster', 'cluster with a zoom-stepped point opacity', { feature_count: 5_000_000, style_config: { render_mode: 'cluster' } as never, paint: { 'circle-opacity': ['step', ['zoom'], 0.2, 8, 0.9] } }],
  ['circle', 'circle with a label', { label_config: LABEL as never }],
  ['circle', 'circle with a zoom-expression label', { label_config: ZOOM_LABEL as never }],
  ['symbol', 'symbol with a label', { style_config: { render_mode: 'symbol' } as never, label_config: LABEL as never }],
  ['cluster', 'cluster with a label', { feature_count: 5_000_000, style_config: { render_mode: 'cluster' } as never, label_config: LABEL as never }],
  ['heatmap', 'heatmap', { style_config: { render_mode: 'heatmap' } as never }],
  ['line', 'line with a label', { geometry_type: 'LINESTRING', paint: { 'line-color': '#222' }, label_config: LABEL as never }],
  ['fill', 'polygon', { geometry_type: 'POLYGON', paint: { 'fill-color': '#336699' } }],
  ['fill', 'polygon with a label', { geometry_type: 'POLYGON', label_config: LABEL as never }],
  [
    'fill',
    'extruded polygon with a configured extrusion opacity',
    { geometry_type: 'POLYGON', style_config: { builder: { heightColumn: 'h', extrusionOpacity: 0.6 } } as never },
  ],
  [
    'fill',
    'extruded polygon with the default extrusion opacity',
    { geometry_type: 'POLYGON', style_config: { builder: { heightColumn: 'h' } } as never },
  ],
  ['mixed', 'mixed geometry', { geometry_type: 'GEOMETRY', label_config: LABEL as never }],
  ['raster', 'raster', { geometry_type: null, layer_type: 'raster_geolens' } as never],
  [
    'hillshade',
    'hillshade with an elevation tint',
    { geometry_type: null, is_dem: true, layer_type: 'raster_geolens', paint: { '_hypso-enabled': true }, style_config: { render_mode: 'hillshade' } as never },
  ],
];

// The per-feature tier sits under the layer-wide one, which carries the fade.
const PER_FEATURE = new Set(['fill-opacity', 'line-opacity']);

function zeroed(value: unknown): boolean {
  if (typeof value === 'number') return value === 0;
  if (!Array.isArray(value)) return false;
  if (value[0] === '*') return value.some(zeroed);
  const first = value[0] === 'step' ? 2 : 4;
  return value.slice(first).filter((_, i) => i % 2 === 0).every(zeroed);
}

describe('opacity keys at fade factor zero', () => {
  it.each(CASES)('%s: %s draws every opacity key at zero', (drawsAs, _name, override) => {
    const layer = { ...BASE, ...override };
    const input = toViewerSyncInput(layer, 'k', new Set(), new Map([['k', { factor: 0 }]]));
    const context = syncRenderContext(new Map(), undefined, undefined, { idPrefix: 'viewer-', mvtSourceLayerPrefix: 'data' });
    const [described] = describeLayers([input], context).layers;
    expect(described.drawsAs).toBe(drawsAs);

    const specs = getAdapter(described.drawsAs).describe!(adapterInputFor(input, described)).specs;
    const opacities = specs.flatMap(({ layer: spec }) =>
      Object.entries(spec.paint)
        .filter(([key]) => key.includes('opacity') && !PER_FEATURE.has(key))
        .map(([key, value]) => ({ layer: spec.id, key, value })),
    );
    expect(opacities.length).toBeGreaterThan(0);
    expect(opacities.filter(({ value }) => !zeroed(value))).toEqual([]);

    // MapLibre accepts what the fade writes: zoom stays at the top of a step or interpolate.
    const sources = {
      vector: { type: 'vector', tiles: ['https://t/{z}/{x}/{y}.pbf'] },
      raster: { type: 'raster', tiles: ['https://t/{z}/{x}/{y}.png'] },
      dem: { type: 'raster-dem', tiles: ['https://t/{z}/{x}/{y}.png'] },
    } as const;
    const sourceFor = (type: string) => (type === 'raster' ? 'raster' : ['hillshade', 'color-relief'].includes(type) ? 'dem' : 'vector');
    const style = {
      version: 8,
      sources,
      layers: specs.map(({ layer: spec }) => ({
        id: spec.id,
        type: spec.type,
        source: sourceFor(spec.type),
        ...(sourceFor(spec.type) === 'vector' ? { 'source-layer': 'data' } : {}),
        paint: Object.fromEntries(Object.entries(spec.paint).filter(([key]) => key.includes('opacity'))),
      })),
    };
    const errors = validateStyleMin(style as never).filter(({ message }) => /opacity/.test(message));
    expect(errors.map(({ message }) => message)).toEqual([]);
  });
});

describe('hillshade colours at fade factor zero', () => {
  it.each(['red', 'hsl(0,100%,50%)', 'rgb(100%,0%,0%)', '#f00', 'rgba(255,0,0,0.5)'])('%s ends fully transparent', (color) => {
    const layer = {
      ...BASE,
      geometry_type: null,
      is_dem: true,
      layer_type: 'raster_geolens',
      style_config: { render_mode: 'hillshade' },
      paint: { 'hillshade-shadow-color': color, 'hillshade-highlight-color': color, 'hillshade-accent-color': color },
    } as unknown as SharedLayerResponse;
    const input = toViewerSyncInput(layer, 'k', new Set(), new Map([['k', { factor: 0 }]]));
    const context = syncRenderContext(new Map(), undefined, undefined, { idPrefix: 'viewer-', mvtSourceLayerPrefix: 'data' });
    const [described] = describeLayers([input], context).layers;
    const [spec] = getAdapter(described.drawsAs).describe!(adapterInputFor(input, described)).specs.filter(({ layer: l }) => l.type === 'hillshade');
    for (const key of ['hillshade-shadow-color', 'hillshade-highlight-color', 'hillshade-accent-color']) {
      expect(Color.parse(spec.layer.paint[key] as string)?.a).toBe(0);
    }
  });
});

describe('the drawing type of a layer mid-fade', () => {
  const draws = (override: Partial<SharedLayerResponse>, factor: number) => {
    const input = toViewerSyncInput({ ...BASE, ...override }, 'k', new Set(), new Map([['k', { factor }]]));
    const context = syncRenderContext(new Map(), undefined, undefined, { idPrefix: 'viewer-', mvtSourceLayerPrefix: 'data' });
    return describeLayers([input], context).layers[0].drawsAs;
  };

  it.each([
    ['line paint', { 'line-color': '#222' }, 'line'],
    ['fill paint', { 'fill-color': '#336699' }, 'fill'],
    ['no paint', {}, 'fill'],
  ])('keeps a layer with %s drawn as %s, whether its geometry type is null or empty', (_name, paint, type) => {
    for (const geometry_type of [null, '']) {
      const override = { geometry_type, paint } as unknown as Partial<SharedLayerResponse>;
      expect(draws(override, 1)).toBe(type);
      expect(draws(override, 0)).toBe(type);
    }
  });
});
