// describeLayers gives each raster and DEM layer the map layers it draws, and the raster and hillshade adapters' own methods write exactly those.
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, StyleConfig } from '@/types/api';
import { SAVED_LAYERS } from '@/test/fixtures/saved-layers';
import { FIXTURE_TOKENS, RENDER_CONTEXTS } from '@/test/fixtures/render-contexts';
import { RecordingMap } from '@/test/recording-map';
import { syncLayersToMap, toSyncInput } from '../map-sync';
import { adapterInputFor, describeLayers } from '../layer-description';
import { buildElevationExpression } from '../color-relief-sync';
import { DEFAULT_HILLSHADE_PAINT } from '../layer-adapters/builder-defaults';
import {
  COLOR_RELIEF_OWNED_PAINT_PROPERTIES,
  HILLSHADE_PAINT_PROPERTIES,
  hillshadeAdapter,
} from '../layer-adapters/hillshade-adapter';
import { RASTER_SPEC_PAINT_PROPERTIES } from '../layer-adapters/raster-adapter';
import { getAdapter } from '../layer-adapters/registry';
import type { LayerDrawing, LayerSpec } from '../layer-adapters/types';

type Row = [label: string, layer: MapLayerResponse, expected: LayerDrawing];

const { raster, hillshadeDem: dem, terrainDem } = SAVED_LAYERS;
const { builder } = RENDER_CONTEXTS;

const FILTER = ['==', ['get', 'kind'], 'school'] as FilterSpecification;
const HYPSO = { ...dem.paint, '_hypso-enabled': true };
const STYLED_RASTER = {
  'raster-brightness-min': 0.15,
  'raster-brightness-max': 0.9,
  'raster-contrast': 0.25,
  'raster-saturation': -0.2,
  'raster-hue-rotate': 45,
  'raster-resampling': 'nearest',
  'raster-fade-duration': 100,
};

function drawing(specs: LayerSpec[]): LayerDrawing {
  return { specs, images: [] };
}

type Overrides = Partial<LayerSpec['layer']>;

function rasterSpec(paint: Record<string, unknown>, overrides: Overrides = {}): LayerSpec {
  return {
    layer: { id: `layer-${raster.id}`, type: 'raster', source: `source-${raster.id}`, layout: { visibility: 'visible' }, paint, ...overrides },
    ownedPaint: RASTER_SPEC_PAINT_PROPERTIES,
    ownedLayout: ['visibility'],
  };
}

function hillshadeSpec(paint: Record<string, unknown> = {}, overrides: Overrides = {}): LayerSpec {
  return {
    layer: {
      id: `layer-${dem.id}`,
      type: 'hillshade',
      source: `source-${dem.id}`,
      layout: { visibility: 'visible' },
      paint: { ...DEFAULT_HILLSHADE_PAINT, ...paint },
      ...overrides,
    },
    ownedPaint: HILLSHADE_PAINT_PROPERTIES,
    ownedLayout: ['visibility'],
  };
}

function reliefSpec(ramp = 'Viridis', reversed = false, overrides: Overrides = {}): LayerSpec {
  return {
    layer: {
      id: `layer-${dem.id}-colorrelief`,
      type: 'color-relief',
      source: `source-${dem.id}`,
      layout: { visibility: 'visible' },
      paint: { 'color-relief-color': buildElevationExpression(ramp, undefined, undefined, reversed), 'color-relief-opacity': 0.7 },
      ...overrides,
    },
    ownedPaint: COLOR_RELIEF_OWNED_PAINT_PROPERTIES,
    ownedLayout: ['visibility'],
  };
}

const hidden = { layout: { visibility: 'none' } };

const rows: Row[] = [
  ['a raster layer', raster, drawing([rasterSpec({ 'raster-opacity': 1 })])],
  [
    'raster paint, with the master opacity over a stored raster opacity',
    { ...raster, opacity: 0.7, paint: { ...STYLED_RASTER, 'raster-opacity': 0.2, 'fill-color': '#ff0000' } },
    drawing([rasterSpec({ ...STYLED_RASTER, 'raster-opacity': 0.7 })]),
  ],
  [
    'raster paint values MapLibre would refuse, which are left out',
    { ...raster, paint: { 'raster-contrast': '0.5', 'raster-resampling': 'cubic' } },
    drawing([rasterSpec({ 'raster-opacity': 1 })]),
  ],
  [
    'a colormap and stretch, which change the tiles and not the layer',
    { ...raster, paint: { _colormap: 'viridis', _stretch: 'percentile', _pmin: 5 } },
    drawing([rasterSpec({ 'raster-opacity': 1 })]),
  ],
  ['a hidden raster', { ...raster, visible: false }, drawing([rasterSpec({ 'raster-opacity': 1 }, hidden)])],
  [
    'a colour relief turned on for a raster that is not a DEM, which draws none',
    { ...raster, paint: { '_hypso-enabled': true } },
    drawing([rasterSpec({ 'raster-opacity': 1 })]),
  ],
  ['a raster with a data filter, which a raster layer does not take', { ...raster, filter: FILTER }, drawing([rasterSpec({ 'raster-opacity': 1 })])],
  [
    'a raster with a saved zoom range, which map-sync sets on the layer',
    { ...raster, layout: { _minzoom: 5, _maxzoom: 12 } },
    drawing([rasterSpec({ 'raster-opacity': 1 })]),
  ],
  ['a hillshade DEM', dem, drawing([hillshadeSpec({ 'hillshade-exaggeration': 0.5 })])],
  [
    "hillshade paint, with the exaggeration clamped to MapLibre's range",
    { ...dem, paint: { 'hillshade-illumination-direction': 200, 'hillshade-illumination-anchor': 'map', 'hillshade-exaggeration': 2.1 } },
    drawing([hillshadeSpec({ 'hillshade-illumination-direction': 200, 'hillshade-illumination-anchor': 'map', 'hillshade-exaggeration': 1 })]),
  ],
  [
    "hillshade colours under a master opacity, which scales each colour's alpha",
    {
      ...dem,
      opacity: 0.25,
      paint: { 'hillshade-shadow-color': '#1f2937', 'hillshade-highlight-color': 'rgba(255,255,255,0.8)', 'hillshade-accent-color': '#64748b80' },
    },
    drawing([hillshadeSpec({
      'hillshade-shadow-color': 'rgba(31, 41, 55, 0.25)',
      'hillshade-highlight-color': 'rgba(255, 255, 255, 0.2)',
      'hillshade-accent-color': 'rgba(100, 116, 139, 0.1255)',
    })]),
  ],
  ['a hidden hillshade', { ...dem, visible: false }, drawing([hillshadeSpec({}, hidden)])],
  ['a colour relief on the default ramp, below the hillshade', { ...dem, paint: HYPSO }, drawing([reliefSpec(), hillshadeSpec()])],
  ['a colour relief on a chosen ramp', { ...dem, paint: { ...HYPSO, '_hypso-ramp': 'Blues' } }, drawing([reliefSpec('Blues'), hillshadeSpec()])],
  [
    'a reversed colour relief',
    { ...dem, paint: { ...HYPSO, '_hypso-ramp': 'Blues', '_hypso-reversed': true } },
    drawing([reliefSpec('Blues', true), hillshadeSpec()]),
  ],
  [
    'a colour relief on a layer with a saved zoom range, which the relief carries itself',
    { ...dem, layout: { _minzoom: 6, _maxzoom: 14 }, paint: HYPSO },
    drawing([reliefSpec('Viridis', false, { minzoom: 6, maxzoom: 14 }), hillshadeSpec()]),
  ],
  ['a hidden colour relief', { ...dem, visible: false, paint: HYPSO }, drawing([reliefSpec('Viridis', false, hidden), hillshadeSpec({}, hidden)])],
  [
    'a colour relief on a DEM saved without a render mode, which draws as a hillshade',
    { ...dem, style_config: null, paint: HYPSO },
    drawing([reliefSpec(), hillshadeSpec()]),
  ],
  [
    'a colour relief the layer turns off',
    { ...dem, paint: { ...HYPSO, '_hypso-enabled': false, '_hypso-ramp': 'Blues' } },
    drawing([hillshadeSpec()]),
  ],
];

describe('describeLayers raster specs', () => {
  it.each(rows)('describes the map layers of %s', (_label, layer, expected) => {
    const [described] = describeLayers([toSyncInput(layer)], builder).layers;
    expect({ specs: described.specs, images: described.images }).toEqual(expected);
  });

  it('gives a terrain-mode DEM no map layers, even one with a colour relief turned on', () => {
    const terrain = { ...terrainDem, paint: { '_hypso-enabled': true } };
    expect(describeLayers([toSyncInput(terrain)], builder).layers).toEqual([]);

    const [described] = describeLayers([toSyncInput({ ...terrain, style_config: null })], builder).layers;
    const input = adapterInputFor(toSyncInput(terrain), described);
    expect(hillshadeAdapter.describe?.(input)).toEqual({ specs: [], images: [] });
  });
});

/** A map holding the source a described layer draws from, and the adapter input for that layer. */
function setUp(layer: MapLayerResponse) {
  const input = toSyncInput(layer);
  const { layers: [described], sources } = describeLayers([input], builder);
  const source = sources.get(described.sourceId) as unknown as { tiles: string[] } & Record<string, unknown>;
  const recording = new RecordingMap();
  recording.addSource(described.sourceId, source);
  return { recording, described, source, adapter: getAdapter(described.drawsAs), adapterInput: adapterInputFor(input, described) };
}

function held(specs: readonly LayerSpec[]) {
  return specs.map(({ layer }) => layer);
}

function edited(layer: MapLayerResponse): MapLayerResponse {
  return {
    ...layer,
    opacity: 0.5,
    visible: false,
    paint: { ...layer.paint, 'raster-contrast': 0.3, 'hillshade-exaggeration': 0.8, '_hypso-ramp': 'Reds' },
  };
}

const ADAPTER_CASES: [label: string, layer: MapLayerResponse][] = [
  ['raster', { ...raster, paint: STYLED_RASTER }],
  ['hillshade', dem],
  ['hillshade with a colour relief', { ...dem, paint: HYPSO }],
];

describe("the raster adapters' own methods", () => {
  it.each(ADAPTER_CASES)('%s addLayers adds the described map layers', (_label, layer) => {
    const { recording, described, adapter, adapterInput } = setUp(layer);

    adapter.addLayers(recording.map, adapterInput);

    expect(recording.layerIds().map((id) => recording.layer(id))).toEqual(held(described.specs));
    expect(recording.errors).toEqual([]);
  });

  it.each(ADAPTER_CASES)('%s addLayers adds the source from the tile URL it is given when the map lacks it', (_label, layer) => {
    const { described, source, adapter, adapterInput } = setUp(layer);
    const recording = new RecordingMap();
    const tileUrl = source.tiles[0].replace(window.location.origin, '');

    adapter.addLayers(recording.map, { ...adapterInput, tileUrl });

    expect(recording.getStyle().sources).toEqual({
      [described.sourceId]: {
        type: source.type,
        tiles: [`${window.location.origin}${tileUrl}`],
        tileSize: 256,
        minzoom: 0,
        maxzoom: 18,
        ...(source.type === 'raster-dem' ? { encoding: 'mapbox' } : {}),
      },
    });
    expect(recording.layerIds().map((id) => recording.layer(id))).toEqual(held(described.specs));
  });

  it.each(ADAPTER_CASES)('%s syncPaint brings existing layers to a changed description, and leaves their filter alone', (_label, layer) => {
    const { recording, adapter, adapterInput } = setUp(layer);
    adapter.addLayers(recording.map, adapterInput);
    const next = setUp(edited(layer));

    adapter.syncPaint(recording.map, next.adapterInput);

    expect(recording.layerIds().map((id) => recording.layer(id))).toEqual(held(next.described.specs));
    expect(recording.callsTo('setFilter')).toEqual([]);
    expect(recording.errors).toEqual([]);
  });

  it.each(ADAPTER_CASES)('%s syncPaint leaves a map without the layer alone', (_label, layer) => {
    const { recording, adapter, adapterInput } = setUp(layer);
    adapter.syncPaint(recording.map, adapterInput);
    expect(recording.layerIds()).toEqual([]);
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

  it('raster addLayers leaves a raster already on the map alone', () => {
    const { recording, adapter, adapterInput } = setUp(raster);
    adapter.addLayers(recording.map, adapterInput);
    recording.calls.length = 0;

    adapter.addLayers(recording.map, { ...adapterInput, opacity: 0.5 });

    expect(recording.calls).toEqual([]);
  });

  it('hillshade syncPaint rebuilds the colour relief below the hillshade', () => {
    const { recording, adapter, adapterInput } = setUp({ ...dem, paint: HYPSO });
    adapter.addLayers(recording.map, adapterInput);
    recording.calls.length = 0;
    const blues = setUp({ ...dem, paint: { ...HYPSO, '_hypso-ramp': 'Blues' } });

    adapter.syncPaint(recording.map, blues.adapterInput);

    expect(recording.callsTo('removeLayer')).toEqual([['layer-layer-relief-colorrelief']]);
    expect(recording.callsTo('addLayer').map(([layer, beforeId]) => [(layer as { id: string }).id, beforeId]))
      .toEqual([['layer-layer-relief-colorrelief', 'layer-layer-relief']]);
    expect(recording.layerIds().map((id) => recording.layer(id))).toEqual(held(blues.described.specs));
  });

  it('hillshade syncPaint leaves a colour relief whose ramp is unchanged in place', () => {
    const { recording, adapter, adapterInput } = setUp({ ...dem, paint: HYPSO });
    adapter.addLayers(recording.map, adapterInput);
    recording.calls.length = 0;

    adapter.syncPaint(recording.map, { ...adapterInput, opacity: 0.5 });

    expect(recording.callsTo('removeLayer')).toEqual([]);
    expect(recording.callsTo('addLayer')).toEqual([]);
  });

  it('hillshade syncPaint adds a colour relief the layer turns on below the hillshade, and removes it once turned off', () => {
    const { recording, adapter, adapterInput } = setUp(dem);
    adapter.addLayers(recording.map, adapterInput);

    adapter.syncPaint(recording.map, setUp({ ...dem, paint: HYPSO }).adapterInput);
    expect(recording.layerIds()).toEqual(['layer-layer-relief-colorrelief', 'layer-layer-relief']);

    adapter.syncPaint(recording.map, adapterInput);
    expect(recording.layerIds()).toEqual(['layer-layer-relief']);
  });
});

/** Two sync passes over one layer, on a map that keeps what the first pass drew. */
function syncTwice(layer: MapLayerResponse) {
  const recording = new RecordingMap();
  const managed = { current: new Set<string>() };
  const order = { current: '' };
  for (const pass of [1, 2]) {
    syncLayersToMap(recording.map, [toSyncInput(layer)], new Map(FIXTURE_TOKENS), undefined, managed, order);
    expect(recording.errors, `pass ${pass}`).toEqual([]);
  }
  return recording;
}

function zoomOf(recording: RecordingMap, id: string) {
  const layer = recording.layer(id);
  return [layer?.minzoom, layer?.maxzoom];
}

describe('raster layers through syncLayersToMap', () => {
  const zoomedRelief = { ...dem, layout: { _minzoom: 6, _maxzoom: 14 }, paint: HYPSO } as MapLayerResponse;

  it("draws a DEM's colour relief below its hillshade, in the layer's saved zoom range", () => {
    const recording = syncTwice(zoomedRelief);

    expect(recording.layerIds()).toEqual(['layer-layer-relief-colorrelief', 'layer-layer-relief']);
    expect(zoomOf(recording, 'layer-layer-relief-colorrelief')).toEqual([6, 14]);
    expect(zoomOf(recording, 'layer-layer-relief')).toEqual([6, 14]);
  });

  it("keeps the colour relief's zoom range through a paint edit between sync passes", () => {
    const recording = syncTwice(zoomedRelief);
    const { adapter, adapterInput } = setUp({ ...zoomedRelief, paint: { ...HYPSO, '_hypso-ramp': 'Blues' } });

    adapter.syncPaint(recording.map, adapterInput);

    expect(zoomOf(recording, 'layer-layer-relief-colorrelief')).toEqual([6, 14]);
    expect(recording.layer('layer-layer-relief-colorrelief')?.paint['color-relief-color'])
      .toEqual(buildElevationExpression('Blues'));
  });

  it('leaves the colour relief in place on a repeat pass', () => {
    const recording = new RecordingMap();
    const managed = { current: new Set<string>() };
    const order = { current: '' };
    const pass = () => syncLayersToMap(recording.map, [toSyncInput(zoomedRelief)], new Map(FIXTURE_TOKENS), undefined, managed, order);
    pass();
    recording.calls.length = 0;

    pass();

    expect(recording.callsTo('removeLayer')).toEqual([]);
    expect(recording.callsTo('addLayer')).toEqual([]);
  });

  it('draws nothing for a terrain-mode DEM', () => {
    const recording = syncTwice({ ...terrainDem, paint: { '_hypso-enabled': true } } as MapLayerResponse);
    expect(recording.layerIds()).toEqual([]);
  });

  it('draws the colour relief of a DEM saved in the legacy image mode, which draws as a hillshade', () => {
    const legacy = { ...dem, style_config: { render_mode: 'image' } as unknown as StyleConfig, paint: HYPSO };
    const recording = syncTwice(legacy);
    expect(recording.layerIds()).toEqual(['layer-layer-relief-colorrelief', 'layer-layer-relief']);
  });
});
