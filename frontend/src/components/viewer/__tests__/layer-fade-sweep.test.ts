// Every opacity the adapters draw must reach zero when the fade factor does, so a
// key an adapter sets from something other than the layer opacity can't be forgotten.
import { adapterInputFor, describeLayers } from '@/components/builder/layer-description';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import { syncRenderContext } from '@/components/builder/map-sync';
import type { SharedLayerResponse } from '@/types/api';
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

const CASES: [string, string, Partial<SharedLayerResponse>][] = [
  ['circle', 'circle', { paint: { 'circle-color': '#222', 'circle-stroke-width': 2, 'circle-stroke-opacity': 0.5 } }],
  ['circle', 'circle with a default paint', {}],
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
  });
});
