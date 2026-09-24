// writeLayerToMap leaves the layers a sync pass drew as the next pass would leave them, and writes no source.
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, StyleConfig } from '@/types/api';
import { SAVED_LAYERS } from '@/test/fixtures/saved-layers';
import { FIXTURE_TOKENS } from '@/test/fixtures/render-contexts';
import { RecordingMap } from '@/test/recording-map';
import { applyCopiedStyleToLayer, extractCopyableStyle } from '@/lib/builder/layer-style-clipboard';
import { syncLayersToMap, toSyncInput, writeLayerToMap } from '../map-sync';

const {
  polygon, extrusion, strokeOnlyPolygon, patternedPolygon, line, arrowLine, dashedLine, point, heatmapByRamp,
  serverCluster, boundedCluster, fallbackCluster, symbolWithLeftoverClassification: symbol, mixedGeometry,
  raster, hillshadeDem,
} = SAVED_LAYERS;

const FILTER = ['==', ['get', 'kind'], 'a'] as FilterSpecification;
const CLUSTER_DATA = new Map<string, GeoJSON.FeatureCollection>([
  [boundedCluster.id, { type: 'FeatureCollection', features: [] }],
]);
const relief = { ...hillshadeDem, paint: { ...hillshadeDem.paint, '_hypso-enabled': true, '_hypso-ramp': 'Blues' } };

/** A map drawn by one sync pass, and the pass to run on it again. */
function syncedMap(layers: MapLayerResponse[]) {
  const recording = new RecordingMap();
  const managed = { current: new Set<string>() };
  const order = { current: '' };
  const sync = (next: MapLayerResponse[]) => {
    syncLayersToMap(
      recording.map,
      next.map(toSyncInput),
      new Map(FIXTURE_TOKENS),
      undefined,
      managed,
      order,
      CLUSTER_DATA,
      { mvtSourceLayerPrefix: 'data' },
    );
    vi.runAllTimers();
  };
  sync(layers);
  return { recording, sync };
}

function drawn(recording: RecordingMap) {
  return recording.layerIds().map((id) => recording.layer(id));
}

/** The layer with every field a handler edits changed, plus a paint edit of its family. */
function changed(layer: MapLayerResponse, paint: Record<string, unknown>): MapLayerResponse {
  return {
    ...layer,
    opacity: 0.4,
    visible: false,
    filter: FILTER,
    layout: { ...layer.layout, _minzoom: 3, _maxzoom: 15 },
    label_config: { column: 'name' },
    paint: { ...layer.paint, ...paint },
  };
}

const CASES: [label: string, layer: MapLayerResponse, paint: Record<string, unknown>][] = [
  ['polygon', polygon, { 'fill-color': '#123456' }],
  ['extruded polygon', extrusion, { 'fill-color': '#123456' }],
  ['stroke-only polygon', strokeOnlyPolygon, { '_outline-width': 3 }],
  ['patterned polygon', patternedPolygon, { 'fill-opacity': 0.5 }],
  ['line', line, { 'line-width': 5 }],
  ['arrow line', arrowLine, { 'line-color': '#123456' }],
  ['dashed line', dashedLine, { 'line-dasharray': [1, 1] }],
  ['point', point, { 'circle-radius': 9 }],
  ['heatmap', heatmapByRamp, { 'heatmap-radius': 40 }],
  ['server cluster', serverCluster, { 'circle-color': '#123456' }],
  ['bounded cluster', boundedCluster, { 'circle-color': '#123456' }],
  ['fallback cluster', fallbackCluster, { 'circle-color': '#123456' }],
  ['symbol', symbol, {}],
  ['mixed geometry', mixedGeometry, { 'fill-color': '#123456' }],
  ['raster', raster, { 'raster-contrast': 0.3 }],
  ['hillshade with a colour relief', relief, { 'hillshade-exaggeration': 0.8, '_hypso-ramp': 'Reds' }],
];

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('writeLayerToMap', () => {
  it.each(CASES)('leaves the %s layers the next pass leaves, through a change and back', (_label, layer, paint) => {
    const written = syncedMap([layer]);
    const passed = syncedMap([layer]);
    written.recording.calls.length = 0;

    for (const next of [changed(layer, paint), layer]) {
      writeLayerToMap(written.recording.map, toSyncInput(next));
      passed.sync([next]);
      expect(drawn(written.recording)).toEqual(drawn(passed.recording));
    }
    expect(written.recording.errors).toEqual([]);
    const sourceCalls = written.recording.calls.filter(([method]) => ['addSource', 'removeSource', 'setTiles', 'setData'].includes(method));
    expect(sourceCalls).toEqual([]);
  });

  it('removes a cleared label, in a pass and in a write', () => {
    const labelled = { ...point, label_config: { column: 'name' } };
    const written = syncedMap([labelled]);
    const passed = syncedMap([labelled]);
    expect(written.recording.layer(`layer-${point.id}-label`)).toBeDefined();

    writeLayerToMap(written.recording.map, toSyncInput(point));
    passed.sync([point]);

    expect(written.recording.layer(`layer-${point.id}-label`)).toBeUndefined();
    expect(passed.recording.layer(`layer-${point.id}-label`)).toBeUndefined();
  });

  it('writes nothing to a map no pass has drawn', () => {
    const recording = new RecordingMap();
    recording.addSource('source-data-parcels', { type: 'vector', tiles: ['https://maps.example.test/tiles/{z}/{x}/{y}.pbf'] });
    recording.addLayer({ id: `layer-${polygon.id}`, type: 'fill', source: 'source-data-parcels', 'source-layer': 'data.parcels', layout: {}, paint: {} });
    recording.calls.length = 0;

    writeLayerToMap(recording.map, toSyncInput(changed(polygon, {})));

    expect(recording.calls).toEqual([]);
  });

  it('writes nothing after a style reload drops the layers, until the next pass draws them', () => {
    const { recording, sync } = syncedMap([mixedGeometry]);
    for (const id of recording.layerIds()) recording.removeLayer(id);
    for (const id of Object.keys(recording.getStyle().sources)) recording.removeSource(id);
    recording.calls.length = 0;

    writeLayerToMap(recording.map, toSyncInput(changed(mixedGeometry, {})));
    expect(recording.calls).toEqual([]);

    sync([mixedGeometry]);
    writeLayerToMap(recording.map, toSyncInput(changed(mixedGeometry, {})));
    const passed = syncedMap([mixedGeometry]);
    passed.sync([changed(mixedGeometry, {})]);
    expect(drawn(recording)).toEqual(drawn(passed.recording));
  });

  it('leaves a layer the map draws as another family alone', () => {
    const { recording } = syncedMap([point]);
    recording.calls.length = 0;

    writeLayerToMap(recording.map, toSyncInput(applyCopiedStyleToLayer(point, extractCopyableStyle(heatmapByRamp))));

    expect(recording.calls).toEqual([]);
  });

  it('writes nothing for a DEM switched to terrain', () => {
    const { recording } = syncedMap([relief]);
    recording.calls.length = 0;

    writeLayerToMap(recording.map, toSyncInput({ ...relief, style_config: { render_mode: 'terrain' } as StyleConfig }));

    expect(recording.calls).toEqual([]);
  });
});
