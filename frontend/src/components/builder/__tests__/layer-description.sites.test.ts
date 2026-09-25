// Every builder site that builds an adapter input hands the adapter a layout
// without private keys, a sanitised filter and the layer's label_config.
import { act, renderHook } from '@testing-library/react';
import type { FilterSpecification, Map as MaplibreMap } from 'maplibre-gl';
import { SAVED_LAYERS } from '@/test/fixtures/saved-layers';
import { FIXTURE_TOKENS } from '@/test/fixtures/render-contexts';
import { RecordingMap } from '@/test/recording-map';
import { flushCoalescedFrame } from '@/lib/builder/raf-coalesce';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';
import type { LabelConfig, MapLayerResponse } from '@/types/api';
import { syncLayersToMap, toSyncInput, writeLayerToMap } from '../map-sync';
import { useLayerMapSync } from '../hooks/use-layer-map-sync';
import { useRenderModeLayers } from '../hooks/use-render-mode-layers';
import { clusterAdapter } from '../layer-adapters/cluster-adapter';
import { fillAdapter } from '../layer-adapters/fill-adapter';
import { hillshadeAdapter } from '../layer-adapters/hillshade-adapter';
import { mixedAdapter } from '../layer-adapters/mixed-adapter';
import type { AdapterLayerInput, LayerAdapter } from '../layer-adapters/types';

const NUMERIC_FILTER = ['>', ['get', 'pop'], 100] as FilterSpecification;
const LABEL: LabelConfig = { column: 'name' };

function withPrivateKeys(layer: MapLayerResponse): MapLayerResponse {
  return {
    ...layer,
    layout: { ...layer.layout, visibility: 'visible', _minzoom: 4, _maxzoom: 16 },
    filter: NUMERIC_FILTER,
    label_config: LABEL,
  };
}

function sync(map: MaplibreMap, layer: MapLayerResponse) {
  syncLayersToMap(
    map,
    [toSyncInput(layer)],
    new Map(FIXTURE_TOKENS),
    undefined,
    { current: new Set() },
    { current: '' },
    undefined,
    { mvtSourceLayerPrefix: 'data' },
  );
}

/** A map a sync pass drew the layer on. */
function drawnMap(layer: MapLayerResponse): RecordingMap {
  const recording = new RecordingMap();
  sync(recording.map, layer);
  return recording;
}

type Run = (layer: MapLayerResponse, map: MaplibreMap) => void;

const runSync: Run = (layer) => sync(new RecordingMap().map, layer);

const runWrite: Run = (layer, map) => writeLayerToMap(map, toSyncInput(layer));

const runPaintChange: Run = (layer, map) => {
  const { result } = renderHook(() => useLayerMapSync([layer], vi.fn(), vi.fn(), { current: map }));
  act(() => result.current.handlePaintChange(layer.id, layer.paint ?? {}));
  flushCoalescedFrame(`paint:${layer.id}`);
};

const runStyleConfigChange: Run = (layer, map) => {
  const { result } = renderHook(() => useLayerMapSync([layer], vi.fn(), vi.fn(), { current: map }));
  act(() => result.current.handleStyleConfigChange(layer.id, layer.style_config ?? null, layer.paint ?? {}));
};

const runRenderModeSwap: Run = (layer, map) => {
  const { result } = renderHook(() => useRenderModeLayers({
    layersRef: { current: [layer] },
    setLocalLayers: vi.fn(),
    setHasUnsavedChanges: vi.fn(),
    mapInstanceRef: { current: map },
    mvtSourceLayerPrefix: 'data',
  }));
  act(() => result.current.swapLayerOnMap(layer, 'fill', layer.paint ?? {}));
};

type Site = [
  site: string,
  layer: MapLayerResponse,
  adapter: LayerAdapter,
  method: 'addLayers' | 'syncPaint',
  run: Run,
];

const SITES: Site[] = [
  ['syncLayersToMap', SAVED_LAYERS.polygon, fillAdapter, 'addLayers', runSync],
  ['writeLayerToMap on a polygon', SAVED_LAYERS.polygon, fillAdapter, 'syncPaint', runWrite],
  ['writeLayerToMap on a hillshade', SAVED_LAYERS.hillshadeDem, hillshadeAdapter, 'syncPaint', runWrite],
  ['writeLayerToMap on a cluster', SAVED_LAYERS.serverCluster, clusterAdapter, 'syncPaint', runWrite],
  ['writeLayerToMap on a mixed layer', SAVED_LAYERS.mixedGeometry, mixedAdapter, 'syncPaint', runWrite],
  ['handlePaintChange', SAVED_LAYERS.polygon, fillAdapter, 'syncPaint', runPaintChange],
  ['swapLayerOnMap', SAVED_LAYERS.polygon, fillAdapter, 'addLayers', runRenderModeSwap],
];

const WRITE_PATHS = new Set(SITES.map(([site]) => site).filter((site) => site.startsWith('writeLayerToMap') || site === 'handlePaintChange'));

function adapterInputAt(site: Site): AdapterLayerInput {
  const [, fixture, adapter, method, run] = site;
  const layer = withPrivateKeys(fixture);
  const map = drawnMap(layer);
  const received = vi.spyOn(adapter, method).mockImplementation(() => {});
  run(layer, map.map);
  expect(received).toHaveBeenCalled();
  return received.mock.calls.at(-1)![1];
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('adapter input sites', () => {
  it.each(SITES)('%s hands the adapter a layout without private keys and a sanitised filter', (...site) => {
    const input = adapterInputAt(site);
    expect(input.layout).toEqual({ ...site[1].layout, visibility: 'visible' });
    expect(input.filter).not.toEqual(NUMERIC_FILTER);
    expect(input.filter).toEqual(sanitizeNullableNumericFilter(NUMERIC_FILTER));
  });

  it.each(SITES.filter(([site]) => WRITE_PATHS.has(site)))(
    '%s hands the adapter the layer label_config',
    (...site) => {
      expect(adapterInputAt(site).label_config).toEqual(LABEL);
    },
  );

  it.each([
    ['handlePaintChange', runPaintChange],
    ['handleStyleConfigChange', runStyleConfigChange],
  ] as const)('%s keeps a symbol layer text on the map', (_site, run) => {
    const layer = { ...SAVED_LAYERS.symbolWithLeftoverClassification, label_config: LABEL };
    const recording = drawnMap(layer);
    run(layer, recording.map);
    expect(recording.layer(`layer-${layer.id}`)?.layout['text-field']).toEqual(['get', LABEL.column]);
  });
});
