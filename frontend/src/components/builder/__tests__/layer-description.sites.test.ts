// Every builder site that builds an adapter input hands the adapter a layout
// without private keys, a sanitised filter and the layer's label_config.
import { act, renderHook } from '@testing-library/react';
import type { FilterSpecification, Map as MaplibreMap } from 'maplibre-gl';
import { SAVED_LAYERS } from '@/test/fixtures/saved-layers';
import { flushCoalescedFrame } from '@/lib/builder/raf-coalesce';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';
import type { LabelConfig, MapLayerResponse } from '@/types/api';
import { syncLayersToMap, toSyncInput } from '../map-sync';
import { applyLayerOpacityToMap, useLayerMapSync } from '../hooks/use-layer-map-sync';
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

/** A map holding the given layers, whose layout properties are recorded per layer. */
function mapWith(layerIds: string[], layout: Record<string, Record<string, unknown>> = {}) {
  const layers = new Set(layerIds);
  const sources = new Map<string, { type: string }>();
  return {
    isStyleLoaded: () => true,
    getLayer: (id: string) => (layers.has(id) ? { id } : undefined),
    addLayer: (spec: { id: string }) => { layers.add(spec.id); },
    removeLayer: (id: string) => { layers.delete(id); },
    getSource: (id: string) => sources.get(id),
    addSource: (id: string, spec: { type: string }) => { sources.set(id, spec); },
    removeSource: (id: string) => { sources.delete(id); },
    getStyle: () => ({ layers: [] }),
    getSprite: () => [{ id: 'geolens' }],
    addSprite: () => {},
    getLayoutProperty: (id: string, prop: string) => layout[id]?.[prop],
    setLayoutProperty: (id: string, prop: string, value: unknown) => {
      layout[id] = { ...layout[id], [prop]: value };
    },
    getPaintProperty: () => undefined,
    setPaintProperty: () => {},
    setFilter: () => {},
    setLayerZoomRange: () => {},
    moveLayer: () => {},
    triggerRepaint: () => {},
    once: () => {},
    off: () => {},
    on: () => {},
  } as unknown as MaplibreMap;
}

type Run = (layer: MapLayerResponse, map: MaplibreMap) => void;

const runSync: Run = (layer, map) => {
  syncLayersToMap(
    map,
    [toSyncInput(layer)],
    new Map(),
    undefined,
    { current: new Set() },
    { current: '' },
    undefined,
    { mvtSourceLayerPrefix: 'data' },
  );
};

const runOpacityChange: Run = (layer, map) => applyLayerOpacityToMap(map, layer, 0.5, 'data');

const runPaintChange: Run = (layer, map) => {
  const { result } = renderHook(() => useLayerMapSync([layer], vi.fn(), vi.fn(), { current: map }, 'data'));
  act(() => result.current.handlePaintChange(layer.id, layer.paint ?? {}));
  flushCoalescedFrame(`paint:${layer.id}`);
};

const runStyleConfigSync: Run = (layer, map) => {
  const { result } = renderHook(() => useLayerMapSync([layer], vi.fn(), vi.fn(), { current: map }, 'data'));
  result.current.syncStyleConfigToMap(map, layer, layer.paint ?? {});
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
  ['the hillshade opacity path', SAVED_LAYERS.hillshadeDem, hillshadeAdapter, 'syncPaint', runOpacityChange],
  ['the cluster opacity path', SAVED_LAYERS.serverCluster, clusterAdapter, 'syncPaint', runOpacityChange],
  ['the mixed opacity path', SAVED_LAYERS.mixedGeometry, mixedAdapter, 'syncPaint', runOpacityChange],
  ['handlePaintChange', SAVED_LAYERS.polygon, fillAdapter, 'syncPaint', runPaintChange],
  ['syncStyleConfigToMap', SAVED_LAYERS.polygon, fillAdapter, 'syncPaint', runStyleConfigSync],
  ['swapLayerOnMap', SAVED_LAYERS.polygon, fillAdapter, 'addLayers', runRenderModeSwap],
];

const LAYER_MAP_SYNC_PATHS = new Set([
  'the hillshade opacity path',
  'the cluster opacity path',
  'the mixed opacity path',
  'handlePaintChange',
  'syncStyleConfigToMap',
]);

function adapterInputAt(site: Site): AdapterLayerInput {
  const [, fixture, adapter, method, run] = site;
  const layer = withPrivateKeys(fixture);
  const received = vi.spyOn(adapter, method).mockImplementation(() => {});
  run(layer, mapWith([`layer-${layer.id}`]));
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

  it.each(SITES.filter(([site]) => LAYER_MAP_SYNC_PATHS.has(site)))(
    '%s hands the adapter the layer label_config',
    (...site) => {
      expect(adapterInputAt(site).label_config).toEqual(LABEL);
    },
  );

  it.each([
    ['handlePaintChange', runPaintChange],
    ['syncStyleConfigToMap', runStyleConfigSync],
  ] as const)('%s keeps a symbol layer text on the map', (_site, run) => {
    const layer = { ...SAVED_LAYERS.symbolWithLeftoverClassification, label_config: LABEL };
    const layerId = `layer-${layer.id}`;
    const layout = { [layerId]: { 'text-field': ['get', LABEL.column] } };
    run(layer, mapWith([layerId], layout));
    expect(layout[layerId]['text-field']).toEqual(['get', LABEL.column]);
  });
});
