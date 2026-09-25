// describeLayers gives each polygon and GEOMETRY layer the map layers it draws, and the fill and mixed adapters' own methods write exactly those.
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, StyleConfig } from '@/types/api';
import { SAVED_LAYERS } from '@/test/fixtures/saved-layers';
import { FIXTURE_TOKENS, RENDER_CONTEXTS } from '@/test/fixtures/render-contexts';
import { RecordingMap } from '@/test/recording-map';
import { MAP_COLORS } from '@/lib/map-colors';
import { syncLayersToMap, toSyncInput } from '../map-sync';
import { adapterInputFor, describeLayers } from '../layer-description';
import { DEFAULT_CIRCLE_PAINT, DEFAULT_FILL_PAINT, DEFAULT_LINE_PAINT } from '../layer-adapters/builder-defaults';
import { CIRCLE_OWNED_PAINT_PROPERTIES } from '../layer-adapters/circle-adapter';
import {
  EXTRUSION_OWNED_PAINT_PROPERTIES,
  FILL_OWNED_PAINT_PROPERTIES,
  OUTLINE_OWNED_PAINT_PROPERTIES,
} from '../layer-adapters/fill-adapter';
import { FILL_PATTERN_IMAGES } from '../layer-adapters/fill-pattern-images';
import { LINE_OWNED_LAYOUT_PROPERTIES, LINE_OWNED_PAINT_PROPERTIES } from '../layer-adapters/line-adapter';
import { getAdapter } from '../layer-adapters/registry';
import type { ImageSpec, LayerDrawing, LayerSpec } from '../layer-adapters/types';

type Row = [label: string, layer: MapLayerResponse, expected: LayerDrawing];

const {
  polygon,
  strokeOnlyPolygon,
  staleMirrorPolygon,
  patternedPolygon,
  extrusion: buildings,
  categorical,
  graduatedColor,
  mixedGeometry: sketches,
} = SAVED_LAYERS;

const FILTER = ['==', ['get', 'kind'], 'school'] as FilterSpecification;
const OPACITY_BY_ZOOM = ['step', ['zoom'], 0.2, 9, 0.7];
const USE_MATCH = ['match', ['get', 'use'], 'res', '#ff0000', '#00ff00'];
const TRANSPARENT = MAP_COLORS.transparent;
const HEIGHT = ['coalesce', ['to-number', ['get', 'height_m'], 0], 0];
const POLYGONS = ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]] as FilterSpecification;
const LINES = ['in', ['geometry-type'], ['literal', ['LineString', 'MultiLineString']]] as FilterSpecification;
const POINTS = ['in', ['geometry-type'], ['literal', ['Point', 'MultiPoint']]] as FilterSpecification;

const OUTLINE = { 'line-color': MAP_COLORS.default.stroke, 'line-width': 1, 'line-layer-opacity': 1 };
const PARCELS = { 'fill-color': '#3b82f6', 'fill-opacity': 0.3, 'fill-layer-opacity': 1, 'fill-outline-color': TRANSPARENT };
const BUILDINGS = { 'fill-color': '#f97316', 'fill-opacity': 0.6, 'fill-layer-opacity': 1, 'fill-outline-color': TRANSPARENT };
const SKETCHES = { 'fill-color': '#8b5cf6', 'fill-opacity': 0.4, 'fill-layer-opacity': 1 };
const MIXED_LINES = { ...DEFAULT_LINE_PAINT, 'line-opacity': 1, 'line-layer-opacity': 1 };
const MIXED_POINTS = { ...DEFAULT_CIRCLE_PAINT, 'circle-opacity': 1 };

function withBuilder(layer: MapLayerResponse, builder: Record<string, unknown>): MapLayerResponse {
  return { ...layer, style_config: { ...layer.style_config, builder: { ...layer.style_config?.builder, ...builder } } as StyleConfig };
}

function tableSource(layer: MapLayerResponse) {
  return { source: `source-data-${layer.dataset_table_name}`, 'source-layer': `data.${layer.dataset_table_name}` };
}

function drawing(specs: LayerSpec[], images: readonly ImageSpec[] = FILL_PATTERN_IMAGES): LayerDrawing {
  return { specs, images };
}

/** The image a built-in pattern draws with in one colour. */
function tinted(id: string): ImageSpec {
  return { kind: 'image', id, data: expect.any(Function) };
}

type Overrides = Partial<LayerSpec['layer']>;

function fill(layer: MapLayerResponse, paint: Record<string, unknown>, overrides: Overrides = {}): LayerSpec {
  return {
    layer: { id: `layer-${layer.id}`, type: 'fill', ...tableSource(layer), layout: { visibility: 'visible' }, paint, ...overrides },
    ownedPaint: FILL_OWNED_PAINT_PROPERTIES,
    ownedLayout: [],
  };
}

function outline(layer: MapLayerResponse, paint: Record<string, unknown> = OUTLINE, overrides: Overrides = {}): LayerSpec {
  return {
    layer: { id: `layer-${layer.id}-outline`, type: 'line', ...tableSource(layer), layout: { visibility: 'visible' }, paint, ...overrides },
    ownedPaint: OUTLINE_OWNED_PAINT_PROPERTIES,
    ownedLayout: ['visibility'],
  };
}

/** The label companion a polygon/GEOMETRY layer draws: forced to point
 *  placement (fill geometry never places labels along a line). */
function label(layer: MapLayerResponse, overrides: Overrides = {}): LayerSpec {
  return {
    layer: {
      id: `layer-${layer.id}-label`,
      type: 'symbol',
      ...tableSource(layer),
      layout: {
        'text-field': ['get', 'name'],
        'text-size': 12,
        'symbol-placement': 'point',
        'text-allow-overlap': false,
        'text-font': ['Noto Sans Regular'],
        'text-max-width': 10,
        'text-anchor': 'center',
        'text-offset': [0, 0],
        'symbol-avoid-edges': true,
        visibility: 'visible',
      },
      paint: {
        'text-color': MAP_COLORS.label.color,
        'text-halo-color': MAP_COLORS.label.halo,
        'text-halo-width': 1.5,
        'text-opacity': 1,
      },
      minzoom: 0,
      maxzoom: 22,
      ...overrides,
    },
    ownedPaint: ['text-color', 'text-halo-color', 'text-halo-width', 'text-opacity'],
    // 'visibility' is not owned: writeDescribedVisibility is the label's only
    // visibility writer after the initial add, so a stale syncPaint input
    // cannot roll it back.
    ownedLayout: [
      'text-field', 'text-size', 'symbol-placement', 'text-allow-overlap',
      'text-font', 'text-max-width', 'text-anchor', 'text-offset',
      'symbol-avoid-edges',
    ],
  };
}

function extrusion(layer: MapLayerResponse, paint: Record<string, unknown>, overrides: Overrides = {}): LayerSpec {
  return {
    layer: {
      id: `layer-${layer.id}-extrusion`,
      type: 'fill-extrusion',
      ...tableSource(layer),
      minzoom: 14,
      maxzoom: 22,
      layout: { visibility: 'visible' },
      paint: {
        'fill-extrusion-height': HEIGHT,
        'fill-extrusion-base': 0,
        'fill-extrusion-opacity': 0.85,
        'fill-extrusion-vertical-gradient': true,
        ...paint,
      },
      ...overrides,
    },
    ownedPaint: EXTRUSION_OWNED_PAINT_PROPERTIES,
    ownedLayout: [],
  };
}

function mixed(
  layer: MapLayerResponse,
  paint: { fill: Record<string, unknown>; outline?: Record<string, unknown>; lines?: Record<string, unknown>; points?: Record<string, unknown> },
  parts: { visibility?: 'visible' | 'none'; lineLayout?: Record<string, unknown>; filter?: FilterSpecification } = {},
): LayerSpec[] {
  const id = `layer-${layer.id}`;
  const { visibility = 'visible' } = parts;
  const source = tableSource(layer);
  const within = (family: FilterSpecification) => (parts.filter ? ['all', family, parts.filter] : family) as FilterSpecification;
  return [
    {
      layer: { id, type: 'fill', ...source, filter: within(POLYGONS), layout: { visibility }, paint: paint.fill },
      ownedPaint: FILL_OWNED_PAINT_PROPERTIES,
      ownedLayout: [],
    },
    {
      layer: { id: `${id}-outline`, type: 'line', ...source, filter: within(POLYGONS), layout: { visibility }, paint: paint.outline ?? OUTLINE },
      ownedPaint: OUTLINE_OWNED_PAINT_PROPERTIES,
      ownedLayout: [],
    },
    {
      layer: {
        id: `${id}-lines`,
        type: 'line',
        ...source,
        filter: within(LINES),
        layout: { 'line-cap': 'round', 'line-join': 'round', ...parts.lineLayout, visibility },
        paint: paint.lines ?? MIXED_LINES,
      },
      ownedPaint: [...LINE_OWNED_PAINT_PROPERTIES, 'line-layer-opacity'],
      ownedLayout: LINE_OWNED_LAYOUT_PROPERTIES,
    },
    {
      layer: { id: `${id}-points`, type: 'circle', ...source, filter: within(POINTS), layout: { visibility }, paint: paint.points ?? MIXED_POINTS },
      ownedPaint: CIRCLE_OWNED_PAINT_PROPERTIES,
      ownedLayout: [],
    },
  ];
}

const hidden = { layout: { visibility: 'none' } };
const snakeCase = {
  ...polygon,
  opacity: 0.7,
  paint: {},
  style_config: {
    builder: {
      height_column: 'height',
      height_scale: 1.8,
      extrusion_min_zoom: 12.5,
      extrusion_opacity: 0.96,
      outline_color: '#07111f',
      outline_width: 0.28,
    },
  } as unknown as StyleConfig,
};

const rows: Row[] = [
  ['a polygon layer', polygon, drawing([fill(polygon, PARCELS), outline(polygon)])],
  [
    'a polygon layer without fill paint, over the default fill',
    { ...polygon, paint: {} },
    drawing([fill(polygon, { ...DEFAULT_FILL_PAINT, 'fill-layer-opacity': 1, 'fill-outline-color': TRANSPARENT }), outline(polygon)]),
  ],
  [
    'stale line, circle and extrusion paint, which stays off the fill',
    { ...polygon, paint: { 'fill-color': '#ff0000', 'line-color': '#00ff00', 'circle-radius': 8, 'fill-extrusion-height': 30 } },
    drawing([fill(polygon, { ...PARCELS, 'fill-color': '#ff0000' }), outline(polygon)]),
  ],
  [
    'a stroke-only polygon, whose outline colour draws the native outline too',
    strokeOnlyPolygon,
    drawing([
      fill(strokeOnlyPolygon, { 'fill-color': '#0ea5e9', 'fill-opacity': 0, 'fill-layer-opacity': 1, 'fill-outline-color': '#0369a1' }),
      outline(strokeOnlyPolygon, { 'line-color': '#0369a1', 'line-width': 2, 'line-layer-opacity': 1 }),
    ]),
  ],
  [
    'a stale paint mirror, which the builder stroke overrides and which stays off the map',
    staleMirrorPolygon,
    drawing([
      fill(staleMirrorPolygon, { 'fill-color': '#22c55e', 'fill-opacity': 0.3, 'fill-layer-opacity': 1, 'fill-outline-color': '#15803d' }),
      outline(staleMirrorPolygon, { 'line-color': '#15803d', 'line-width': 1.5, 'line-layer-opacity': 1 }),
    ]),
  ],
  [
    'an authored outline, which draws the native outline too',
    withBuilder(polygon, { outlineColor: '#123456', outlineWidth: 3 }),
    drawing([
      fill(polygon, { ...PARCELS, 'fill-outline-color': '#123456' }),
      outline(polygon, { 'line-color': '#123456', 'line-width': 3, 'line-layer-opacity': 1 }),
    ]),
  ],
  [
    'a stored native outline colour without an authored stroke, which the stroke rule replaces',
    { ...polygon, paint: { 'fill-color': '#3b82f6', 'fill-opacity': 0.4, 'fill-outline-color': '#abcdef' } },
    drawing([fill(polygon, { ...PARCELS, 'fill-opacity': 0.4 }), outline(polygon)]),
  ],
  [
    'a disabled stroke, which hides the outline',
    withBuilder(polygon, { strokeDisabled: true }),
    drawing([fill(polygon, PARCELS), outline(polygon, OUTLINE, hidden)]),
  ],
  [
    'a stroke disabled in the paint mirror',
    { ...polygon, paint: { ...polygon.paint, '_stroke-disabled': true } },
    drawing([fill(polygon, PARCELS), outline(polygon, OUTLINE, hidden)]),
  ],
  [
    'a built-in pattern, tinted in the saved fill colour',
    patternedPolygon,
    drawing(
      [
        fill(patternedPolygon, { 'fill-pattern': 'geolens-fill-hatch#16a34a', 'fill-opacity': 0.8, 'fill-layer-opacity': 1, 'fill-outline-color': TRANSPARENT }),
        outline(patternedPolygon),
      ],
      [...FILL_PATTERN_IMAGES, tinted('geolens-fill-hatch#16a34a')],
    ),
  ],
  [
    'a built-in pattern with no colour to tint it',
    { ...polygon, paint: { 'fill-pattern': 'geolens-fill-grid' } },
    drawing([
      fill(polygon, { 'fill-pattern': 'geolens-fill-grid', 'fill-opacity': 0.3, 'fill-layer-opacity': 1, 'fill-outline-color': TRANSPARENT }),
      outline(polygon),
    ]),
  ],
  [
    'a categorical fill',
    categorical,
    drawing([fill(categorical, { ...PARCELS, 'fill-color': categorical.paint['fill-color'], 'fill-opacity': 0.7 }), outline(categorical)]),
  ],
  [
    'a graduated fill colour',
    graduatedColor,
    drawing([fill(graduatedColor, { ...PARCELS, 'fill-color': graduatedColor.paint['fill-color'] }), outline(graduatedColor)]),
  ],
  [
    'a master opacity, which only the layer opacity keys carry',
    { ...polygon, opacity: 0.5, paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.3 } },
    drawing([
      fill(polygon, { ...PARCELS, 'fill-color': '#ff0000', 'fill-layer-opacity': 0.5 }),
      outline(polygon, { ...OUTLINE, 'line-layer-opacity': 0.5 }),
    ]),
  ],
  [
    'an expression fill opacity under a master opacity, kept as it is',
    { ...polygon, opacity: 0.5, paint: { 'fill-color': '#ff0000', 'fill-opacity': OPACITY_BY_ZOOM } },
    drawing([
      fill(polygon, { ...PARCELS, 'fill-color': '#ff0000', 'fill-opacity': OPACITY_BY_ZOOM, 'fill-layer-opacity': 0.5 }),
      outline(polygon, { ...OUTLINE, 'line-layer-opacity': 0.5 }),
    ]),
  ],
  [
    'a hidden, filtered polygon layer',
    { ...polygon, visible: false, filter: FILTER },
    drawing([fill(polygon, PARCELS, { ...hidden, filter: FILTER }), outline(polygon, OUTLINE, { ...hidden, filter: FILTER })]),
  ],
  [
    'a stored layout key, which only the fill takes',
    { ...polygon, layout: { 'fill-sort-key': 2 } },
    drawing([fill(polygon, PARCELS, { layout: { 'fill-sort-key': 2, visibility: 'visible' } }), outline(polygon)]),
  ],
  [
    'an extrusion by a builder height column',
    buildings,
    drawing([fill(buildings, BUILDINGS), outline(buildings), extrusion(buildings, { 'fill-extrusion-color': '#f97316' })]),
  ],
  [
    'an extrusion by the legacy paint key, which stays off the map',
    { ...polygon, paint: { 'fill-color': '#f97316', _height_column: 'height_m' } },
    drawing([fill(polygon, { ...PARCELS, 'fill-color': '#f97316' }), outline(polygon), extrusion(polygon, { 'fill-extrusion-color': '#f97316' })]),
  ],
  [
    'snake_case builder keys from a saved API payload',
    snakeCase,
    drawing([
      fill(polygon, { ...DEFAULT_FILL_PAINT, 'fill-layer-opacity': 0.7, 'fill-outline-color': '#07111f' }),
      outline(polygon, { 'line-color': '#07111f', 'line-width': 0.28, 'line-layer-opacity': 0.7 }),
      extrusion(polygon, {
        'fill-extrusion-height': ['*', ['coalesce', ['to-number', ['get', 'height'], 0], 0], 1.8],
        'fill-extrusion-color': MAP_COLORS.default.fill,
        'fill-extrusion-opacity': 0.96,
      }, { minzoom: 12.5 }),
    ]),
  ],
  [
    'a scaled, translucent extrusion',
    withBuilder(buildings, { heightScale: 2, extrusionOpacity: 0.5 }),
    drawing([
      fill(buildings, BUILDINGS),
      outline(buildings),
      extrusion(buildings, { 'fill-extrusion-height': ['*', HEIGHT, 2], 'fill-extrusion-color': '#f97316', 'fill-extrusion-opacity': 0.5 }),
    ]),
  ],
  [
    'a data-driven extrusion colour, which wins over the saved fill colour',
    withBuilder({ ...buildings, paint: { 'fill-color': USE_MATCH } }, { fillColorSaved: '#0000ff' }),
    drawing([
      fill(buildings, { ...BUILDINGS, 'fill-color': USE_MATCH, 'fill-opacity': 0.3 }),
      outline(buildings),
      extrusion(buildings, { 'fill-extrusion-color': USE_MATCH }),
    ]),
  ],
  [
    'a patterned extrusion, coloured by the saved fill colour',
    withBuilder({ ...buildings, paint: { 'fill-pattern': 'geolens-fill-hatch' } }, { fillColorSaved: '#ff0000' }),
    drawing(
      [
        fill(buildings, { 'fill-pattern': 'geolens-fill-hatch#ff0000', 'fill-opacity': 0.3, 'fill-layer-opacity': 1, 'fill-outline-color': TRANSPARENT }),
        outline(buildings),
        extrusion(buildings, { 'fill-extrusion-color': '#ff0000' }),
      ],
      [...FILL_PATTERN_IMAGES, tinted('geolens-fill-hatch#ff0000')],
    ),
  ],
  [
    'an extrusion minimum of 13',
    withBuilder(buildings, { extrusionMinZoom: 13 }),
    drawing([fill(buildings, BUILDINGS), outline(buildings), extrusion(buildings, { 'fill-extrusion-color': '#f97316' }, { minzoom: 13 })]),
  ],
  [
    "an extrusion within the layer's zoom range",
    { ...buildings, layout: { _minzoom: 15, _maxzoom: 18 } },
    drawing([
      fill(buildings, BUILDINGS),
      outline(buildings),
      extrusion(buildings, { 'fill-extrusion-color': '#f97316' }, { minzoom: 15, maxzoom: 18 }),
    ]),
  ],
  [
    'a zoom range that ends below the extrusion minimum, which leaves the extrusion no zoom to draw at',
    { ...buildings, layout: { _maxzoom: 10 } },
    drawing([
      fill(buildings, BUILDINGS),
      outline(buildings),
      extrusion(buildings, { 'fill-extrusion-color': '#f97316' }, { minzoom: 14, maxzoom: 14 }),
    ]),
  ],
  [
    'a hidden extrusion',
    { ...buildings, visible: false },
    drawing([
      fill(buildings, BUILDINGS, hidden),
      outline(buildings, OUTLINE, hidden),
      extrusion(buildings, { 'fill-extrusion-color': '#f97316' }, hidden),
    ]),
  ],
  ['a GEOMETRY layer, one sublayer per family', sketches, drawing(mixed(sketches, { fill: SKETCHES }))],
  [
    'a GEOMETRY layer without paint, over the default fill',
    { ...sketches, paint: {} },
    drawing(mixed(sketches, { fill: { ...DEFAULT_FILL_PAINT, 'fill-layer-opacity': 1 } })),
  ],
  [
    'a legacy data filter on a GEOMETRY layer, converted and composed with each family filter',
    { ...sketches, filter: ['==', 'status', 'open'] as unknown as FilterSpecification },
    drawing(mixed(sketches, { fill: SKETCHES }, { filter: ['==', ['get', 'status'], 'open'] as FilterSpecification })),
  ],
  [
    'an expression data filter on a GEOMETRY layer, composed as it is',
    { ...sketches, filter: FILTER },
    drawing(mixed(sketches, { fill: SKETCHES }, { filter: FILTER })),
  ],
  [
    'line and circle paint and a stored line cap on a GEOMETRY layer',
    { ...sketches, layout: { 'line-cap': 'butt' }, paint: { 'line-color': '#ff0000', 'line-width': 3, 'circle-radius': 6 } },
    drawing(mixed(sketches, {
      fill: { ...DEFAULT_FILL_PAINT, 'fill-layer-opacity': 1 },
      lines: { 'line-color': '#ff0000', 'line-width': 3, 'line-opacity': 1, 'line-layer-opacity': 1 },
      points: { 'circle-radius': 6, 'circle-opacity': 1 },
    }, { lineLayout: { 'line-cap': 'butt' } })),
  ],
  [
    'a patterned GEOMETRY layer',
    withBuilder({ ...sketches, paint: { 'fill-pattern': 'geolens-fill-dots' } }, { fillColorSaved: '#16a34a' }),
    drawing(
      mixed(sketches, { fill: { 'fill-pattern': 'geolens-fill-dots#16a34a', 'fill-opacity': 0.3, 'fill-layer-opacity': 1 } }),
      [...FILL_PATTERN_IMAGES, tinted('geolens-fill-dots#16a34a')],
    ),
  ],
  [
    'a hidden GEOMETRY layer under a master opacity, which multiplies only the point opacity',
    {
      ...sketches,
      visible: false,
      opacity: 0.5,
      paint: { 'fill-color': '#8b5cf6', 'fill-opacity': 0.3, 'line-color': '#ff0000', 'line-opacity': 0.6, 'circle-color': '#00ff00', 'circle-opacity': 0.8 },
    },
    drawing(mixed(sketches, {
      fill: { 'fill-color': '#8b5cf6', 'fill-opacity': 0.3, 'fill-layer-opacity': 0.5 },
      outline: { ...OUTLINE, 'line-layer-opacity': 0.5 },
      lines: { 'line-color': '#ff0000', 'line-opacity': 0.6, 'line-layer-opacity': 0.5 },
      points: { 'circle-color': '#00ff00', 'circle-opacity': 0.4 },
    }, { visibility: 'none' })),
  ],
  [
    'a polygon with a label',
    { ...polygon, label_config: { column: 'name' } },
    drawing([fill(polygon, PARCELS), outline(polygon), label(polygon)]),
  ],
  [
    'a GEOMETRY layer with a label',
    { ...sketches, label_config: { column: 'name' } },
    drawing(mixed(sketches, { fill: SKETCHES, outline: OUTLINE, lines: MIXED_LINES, points: MIXED_POINTS }).concat(label(sketches))),
  ],
];

describe('describeLayers polygon specs', () => {
  it.each(rows)('describes the map layers of %s', (_label, layer, expected) => {
    const [described] = describeLayers([toSyncInput(layer)], RENDER_CONTEXTS.builder).layers;
    expect({ specs: described.specs, images: described.images }).toEqual(expected);
  });

  it.each([[42], [{ r: 1 }], [['#fff']], [true]])(
    'draws a patterned extrusion untinted and in the default colour when the saved fill colour is %o',
    (junk) => {
      const layer = withBuilder({ ...buildings, paint: { 'fill-pattern': 'geolens-fill-hatch' } }, { fillColorSaved: junk });
      const [described] = describeLayers([toSyncInput(layer)], RENDER_CONTEXTS.builder).layers;
      const [fillSpec, , extrusionSpec] = described.specs;
      expect(fillSpec.layer.paint['fill-pattern']).toBe('geolens-fill-hatch');
      expect(extrusionSpec.layer.paint['fill-extrusion-color']).toBe(MAP_COLORS.default.fill);
      expect(described.images).toEqual(FILL_PATTERN_IMAGES);
    },
  );
});

/** A map holding the source a described layer draws from, and the adapter input for that layer. */
function setUp(layer: MapLayerResponse) {
  const input = toSyncInput(layer);
  const { layers: [described], sources } = describeLayers([input], RENDER_CONTEXTS.builder);
  const recording = new RecordingMap();
  recording.addSource(described.sourceId, sources.get(described.sourceId) as unknown as Record<string, unknown>);
  const adapterInput = { ...adapterInputFor(input, described), sourceType: 'vector' as const };
  return { recording, described, adapter: getAdapter(described.drawsAs), adapterInput };
}

function held(specs: readonly LayerSpec[]) {
  return specs.map(({ layer }) => layer);
}

function edited(layer: MapLayerResponse): MapLayerResponse {
  return withBuilder(
    { ...layer, opacity: 0.5, filter: FILTER, paint: { ...layer.paint, 'fill-color': '#654321' } },
    { outlineColor: '#112233', outlineWidth: 4 },
  );
}

const ADAPTER_CASES: [label: string, layer: MapLayerResponse][] = [
  ['fill', polygon],
  ['fill with a stale paint mirror', staleMirrorPolygon],
  ['patterned fill', patternedPolygon],
  ['extruded fill', buildings],
  ['mixed', sketches],
];

describe("the polygon adapters' own methods", () => {
  it.each(ADAPTER_CASES)('%s addLayers adds the described map layers and their images', (_label, layer) => {
    const { recording, described, adapter, adapterInput } = setUp(layer);

    adapter.addLayers(recording.map, adapterInput);

    expect(recording.layerIds().map((id) => recording.layer(id))).toEqual(held(described.specs));
    expect(recording.callsTo('addImage').map(([id]) => id)).toEqual(described.images.map(({ id }) => id));
    expect(recording.errors).toEqual([]);
  });

  it.each(ADAPTER_CASES)('%s syncPaint brings existing layers to a changed description', (_label, layer) => {
    const { recording, adapter, adapterInput } = setUp(layer);
    adapter.addLayers(recording.map, adapterInput);
    const next = setUp(edited(layer));

    adapter.syncPaint(recording.map, next.adapterInput);

    expect(recording.layerIds().map((id) => recording.layer(id))).toEqual(held(next.described.specs));
    expect(next.described.images.filter(({ id }) => !recording.map.hasImage(id))).toEqual([]);
    expect(recording.errors).toEqual([]);
  });

  it.each(ADAPTER_CASES)('%s syncVisibility sets only the visibility, on layers already added', (_label, layer) => {
    const { recording, described, adapter, adapterInput } = setUp(layer);
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

  it.each(ADAPTER_CASES)('%s getLayerIds covers every map layer it describes', (_label, layer) => {
    const { described, adapter } = setUp(layer);
    expect(adapter.getLayerIds(described.id)).toEqual(expect.arrayContaining(described.specs.map(({ layer: spec }) => spec.id)));
  });

  it('fill syncPaint leaves a map without the layer alone', () => {
    const { recording, adapter, adapterInput } = setUp(buildings);
    adapter.syncPaint(recording.map, adapterInput);
    expect(recording.layerIds()).toEqual([]);
  });

  it('fill syncPaint removes the extrusion once the layer has no height column, and adds it back when the column returns', () => {
    const { recording, adapter, adapterInput } = setUp(buildings);
    adapter.addLayers(recording.map, adapterInput);
    const extrusion = recording.layer('layer-layer-buildings-extrusion');

    adapter.syncPaint(recording.map, setUp(withBuilder(buildings, { heightColumn: undefined })).adapterInput);
    expect(recording.layerIds()).toEqual(['layer-layer-buildings', 'layer-layer-buildings-outline']);

    adapter.syncPaint(recording.map, adapterInput);
    expect(recording.layerIds()).toEqual(['layer-layer-buildings', 'layer-layer-buildings-outline', 'layer-layer-buildings-extrusion']);
    expect(recording.layer('layer-layer-buildings-extrusion')).toEqual(extrusion);
    expect(recording.errors).toEqual([]);
  });

  it('fill syncPaint clears the pattern when the layer goes back to a solid fill', () => {
    const { recording, adapter, adapterInput } = setUp(patternedPolygon);
    adapter.addLayers(recording.map, adapterInput);

    adapter.syncPaint(recording.map, setUp({ ...patternedPolygon, paint: { 'fill-color': '#3b82f6' } }).adapterInput);

    expect(recording.layer('layer-layer-parks')?.paint).toEqual(PARCELS);
  });

  it('fill syncPaint keeps the outline of a hidden layer hidden', () => {
    const hiddenPolygon = { ...polygon, visible: false };
    const { recording, adapter, adapterInput } = setUp(hiddenPolygon);
    adapter.addLayers(recording.map, adapterInput);

    adapter.syncPaint(recording.map, setUp({ ...hiddenPolygon, paint: { 'fill-color': '#654321' } }).adapterInput);

    expect(recording.layer('layer-layer-parcels-outline')?.layout.visibility).toBe('none');
  });

  it.each([
    ['shows the outline with the layer', polygon, 'visible'],
    ['keeps the outline of a disabled stroke hidden', withBuilder(polygon, { strokeDisabled: true }), 'none'],
  ] as const)('fill syncVisibility %s', (_label, layer, outlineVisibility) => {
    const { recording, adapter, adapterInput } = setUp({ ...layer, visible: false });
    adapter.addLayers(recording.map, adapterInput);

    adapter.syncVisibility(recording.map, { ...adapterInput, visible: true });

    expect(recording.layer('layer-layer-parcels')?.layout.visibility).toBe('visible');
    expect(recording.layer('layer-layer-parcels-outline')?.layout.visibility).toBe(outlineVisibility);
  });

  it('keeps the plain pattern id in the saved paint', () => {
    const layer = { ...patternedPolygon, paint: { ...patternedPolygon.paint } };
    const { recording, adapter, adapterInput } = setUp(layer);

    adapter.addLayers(recording.map, adapterInput);

    expect(recording.layer('layer-layer-parks')?.paint['fill-pattern']).toBe('geolens-fill-hatch#16a34a');
    expect(layer.paint['fill-pattern']).toBe('geolens-fill-hatch');
    expect(adapterInput.paint['fill-pattern']).toBe('geolens-fill-hatch');
  });

  it('mixed syncPaint adds the sublayers the map lacks', () => {
    const { recording, described, adapter, adapterInput } = setUp(sketches);

    adapter.syncPaint(recording.map, adapterInput);

    expect(recording.layerIds()).toEqual(described.specs.map(({ layer }) => layer.id));
  });

  it('mixed syncPaint gives the lines the stored cap and join, and round for one no longer stored', () => {
    const { recording, adapter, adapterInput } = setUp({ ...sketches, layout: { 'line-cap': 'butt' } });
    adapter.addLayers(recording.map, adapterInput);

    adapter.syncPaint(recording.map, setUp({ ...sketches, layout: { 'line-join': 'bevel' } }).adapterInput);

    expect(recording.layer('layer-layer-sketches-lines')?.layout).toEqual({ 'line-cap': 'round', 'line-join': 'bevel', visibility: 'visible' });
  });
});

/** Two sync passes over one layer, and the map layers each leaves. */
function syncTwice(layer: MapLayerResponse) {
  const recording = new RecordingMap();
  const managed = { current: new Set<string>() };
  const order = { current: '' };
  const passes = [1, 2].map(() => {
    syncLayersToMap(recording.map, [toSyncInput(layer)], new Map(FIXTURE_TOKENS), undefined, managed, order);
    return recording.layerIds().map((id) => recording.layer(id)!);
  });
  return { recording, passes };
}

function zoomRange(layers: { id: string; minzoom?: number; maxzoom?: number }[], id: string) {
  const layer = layers.find((candidate) => candidate.id === id);
  return [layer?.minzoom, layer?.maxzoom];
}

describe('polygon layers through syncLayersToMap', () => {
  it.each(rows)('draws %s the same on a repeat pass as on the first', (_label, layer, expected) => {
    const { recording, passes: [first, repeat] } = syncTwice(layer);
    expect(first.map(({ id }) => id).sort()).toEqual(expected.specs.map((spec) => spec.layer.id).sort());
    expect(repeat).toEqual(first);
    expect(recording.errors).toEqual([]);
  });

  it.each([
    ['a minimum of 13 on a layer with no saved range', withBuilder(buildings, { extrusionMinZoom: 13 }), [0, 22], [13, 22]],
    ['a minimum of 13 on a layer saved as 0-22', { ...withBuilder(buildings, { extrusionMinZoom: 13 }), layout: { _minzoom: 0, _maxzoom: 22 } }, [0, 22], [13, 22]],
    ['the default minimum on a layer with no saved range', buildings, [0, 22], [14, 22]],
    ['the default minimum on a layer ranged 15-18', { ...buildings, layout: { _minzoom: 15, _maxzoom: 18 } }, [15, 18], [15, 18]],
  ] as const)("gives the extrusion for %s its own range, and the fill and outline the layer's", (_label, layer, range, extruded) => {
    const { passes } = syncTwice(layer);
    for (const pass of passes) {
      expect(zoomRange(pass, 'layer-layer-buildings')).toEqual(range);
      expect(zoomRange(pass, 'layer-layer-buildings-outline')).toEqual(range);
      expect(zoomRange(pass, 'layer-layer-buildings-extrusion')).toEqual(extruded);
    }
  });

  it("keeps the extrusion's range through a paint edit between sync passes", () => {
    const zoomed = { ...buildings, layout: { _minzoom: 15, _maxzoom: 18 } };
    const { recording } = syncTwice(zoomed);
    const { adapter, adapterInput } = setUp({ ...zoomed, paint: { ...zoomed.paint, 'fill-color': '#654321' } });

    adapter.syncPaint(recording.map, adapterInput);

    const layer = recording.layer('layer-layer-buildings-extrusion');
    expect([layer?.minzoom, layer?.maxzoom]).toEqual([15, 18]);
    expect(layer?.paint['fill-extrusion-color']).toBe('#654321');
  });
});
