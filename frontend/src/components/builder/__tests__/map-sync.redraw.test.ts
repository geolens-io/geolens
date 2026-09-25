// A sync pass redraws a layer whose family or source changes.
import type { MapLayerResponse } from '@/types/api';
import { SAVED_LAYERS } from '@/test/fixtures/saved-layers';
import { FIXTURE_TOKENS } from '@/test/fixtures/render-contexts';
import { RecordingMap } from '@/test/recording-map';
import { applyCopiedStyleToLayer, extractCopyableStyle } from '@/lib/builder/layer-style-clipboard';
import { syncLayersToMap, toSyncInput, writeLayerToMap } from '../map-sync';

const { point, polygon, heatmapByRamp, serverCluster, boundedCluster, symbolWithLeftoverClassification: symbol } = SAVED_LAYERS;

const CLUSTER_DATA = new Map<string, GeoJSON.FeatureCollection>([
  [boundedCluster.id, { type: 'FeatureCollection', features: [] }],
]);

/** A map drawn by one sync pass, and the pass to run on it again. */
function syncedMap(layers: MapLayerResponse[]) {
  const recording = new RecordingMap();
  const managed = { current: new Set<string>() };
  const order = { current: '' };
  const sync = (next: MapLayerResponse[]) => {
    syncLayersToMap(recording.map, next.map(toSyncInput), new Map(FIXTURE_TOKENS), undefined, managed, order, CLUSTER_DATA, {
      mvtSourceLayerPrefix: 'data',
    });
    vi.runAllTimers();
  };
  sync(layers);
  return { recording, sync };
}

/** The map's layers in stack order, bottom first. */
function drawn(recording: RecordingMap) {
  return recording.layerIds().map((id) => recording.layer(id));
}

function pasted(target: MapLayerResponse, source: MapLayerResponse): MapLayerResponse {
  return applyCopiedStyleToLayer(target, extractCopyableStyle(source));
}

const labelledPoint = { ...point, label_config: { column: 'name' } };
/** A point layer with more features than a cluster draws in the browser. */
const manyPoints = { ...point, dataset_feature_count: 250_000 };

const PASTES: [label: string, target: MapLayerResponse, source: MapLayerResponse][] = [
  ['a point to a heatmap', point, heatmapByRamp],
  ['a heatmap to a point', heatmapByRamp, point],
  ['a point to a symbol', point, symbol],
  ['a symbol to a point', symbol, point],
  ['a labelled point to a heatmap', labelledPoint, heatmapByRamp],
  ['a point to a cluster whose GeoJSON has not arrived', point, boundedCluster],
  ['a bounded cluster to a point', boundedCluster, point],
  ['a point layer too large to cluster in the browser to a server cluster', manyPoints, serverCluster],
  ['a server cluster to a point', serverCluster, point],
];

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('syncLayersToMap after a family change', () => {
  it.each(PASTES)('draws %s as a fresh pass does, alone, above and below another layer', (_label, target, source) => {
    const next = pasted(target, source);
    for (const [before, after] of [[[target], [next]], [[target, polygon], [next, polygon]], [[polygon, target], [polygon, next]]]) {
      const { recording, sync } = syncedMap(before);
      sync(after);
      expect(drawn(recording)).toEqual(drawn(syncedMap(after).recording));
      expect(recording.errors).toEqual([]);
    }
  });

  it.each(Object.entries(SAVED_LAYERS))('adds, removes and moves nothing in a second pass over the %s fixture', (_key, layer) => {
    const { recording, sync } = syncedMap([layer]);
    recording.calls.length = 0;

    sync([layer]);

    const structural = recording.calls.filter(([method]) => ['addLayer', 'removeLayer', 'moveLayer', 'addSource', 'removeSource'].includes(method));
    expect(structural).toEqual([]);
  });
});

describe('writeLayerToMap after a family change', () => {
  it('leaves a layer the map draws from another source for the next pass to replace', () => {
    const { recording, sync } = syncedMap([manyPoints]);
    const next = pasted(manyPoints, serverCluster);
    recording.calls.length = 0;

    writeLayerToMap(recording.map, toSyncInput(next));
    expect(recording.calls).toEqual([]);

    sync([next]);
    expect(drawn(recording)).toEqual(drawn(syncedMap([next]).recording));
    expect(recording.errors).toEqual([]);
  });
});
