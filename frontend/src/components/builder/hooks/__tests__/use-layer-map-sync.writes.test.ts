// Each builder handler leaves the map layers a sync pass leaves for the state the handler commits.
import type { SetStateAction } from 'react';
import { act, renderHook } from '@testing-library/react';
import type { FilterSpecification } from 'maplibre-gl';
import type { LabelConfig, MapLayerResponse, StyleConfig } from '@/types/api';
import { SAVED_LAYERS } from '@/test/fixtures/saved-layers';
import { FIXTURE_TOKENS } from '@/test/fixtures/render-contexts';
import { RecordingMap } from '@/test/recording-map';
import { __resetForTest, flushCoalescedFrame } from '@/lib/builder/raf-coalesce';
import { syncLayersToMap, toSyncInput } from '../../map-sync';
import { useLayerMapSync } from '../use-layer-map-sync';

const {
  polygon, extrusion, patternedPolygon, line, arrowLine, point, heatmapByRamp, serverCluster, boundedCluster,
  fallbackCluster, symbolWithLeftoverClassification: symbol, mixedGeometry, raster, hillshadeDem,
} = SAVED_LAYERS;

type Handlers = ReturnType<typeof useLayerMapSync>;

const FILTER = ['==', ['get', 'kind'], 'a'] as FilterSpecification;
const LABEL: LabelConfig = { column: 'name' };
const CLUSTER_DATA = new Map<string, GeoJSON.FeatureCollection>([
  [boundedCluster.id, { type: 'FeatureCollection', features: [] }],
]);
const relief = { ...hillshadeDem, paint: { ...hillshadeDem.paint, '_hypso-enabled': true, '_hypso-ramp': 'Blues' } };
const gradientLine: MapLayerResponse = {
  ...line,
  paint: { ...line.paint, 'line-gradient': ['interpolate', ['linear'], ['line-progress'], 0, '#ff0000', 1, '#0000ff'] },
  style_config: { builder: { lineGradient: { stops: [{ position: 0, color: '#ff0000' }, { position: 1, color: '#0000ff' }] } } },
};

function withBuilder(layer: MapLayerResponse, builder: Record<string, unknown>): MapLayerResponse {
  return { ...layer, style_config: { ...layer.style_config, builder: { ...layer.style_config?.builder, ...builder } } as StyleConfig };
}

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
  };
  sync(layers);
  return { recording, sync };
}

function drawn(recording: RecordingMap) {
  return recording.layerIds().map((id) => recording.layer(id));
}

/** The handlers over a synced map, with state held the way React commits it. */
function mountHandlers(layers: MapLayerResponse[]) {
  const { recording, sync } = syncedMap(layers);
  let state = layers;
  const setLocalLayers = (update: SetStateAction<MapLayerResponse[]>) => {
    state = typeof update === 'function' ? update(state) : update;
  };
  const hook = renderHook(
    ({ current }: { current: MapLayerResponse[] }) =>
      useLayerMapSync(current, setLocalLayers, vi.fn(), { current: recording.map }),
    { initialProps: { current: layers } },
  );
  recording.calls.length = 0;
  return {
    recording,
    sync,
    handlers: (): Handlers => hook.result.current,
    state: () => state,
    commit: () => hook.rerender({ current: state }),
    flushFrames: () => {
      for (const layer of layers) flushCoalescedFrame(`paint:${layer.id}`);
    },
  };
}

type Mounted = ReturnType<typeof mountHandlers>;

/** The map layers a pass over `initial` and then `final` leaves. */
function passedLayers(initial: MapLayerResponse[], final: MapLayerResponse[]) {
  const passed = syncedMap(initial);
  passed.sync(final);
  return drawn(passed.recording);
}

function run(layers: MapLayerResponse[], edit: (handlers: Handlers) => void): Mounted {
  const mounted = mountHandlers(layers);
  act(() => edit(mounted.handlers()));
  mounted.flushFrames();
  return mounted;
}

function expectMatchesPass(layers: MapLayerResponse[], mounted: Mounted) {
  expect(drawn(mounted.recording)).toEqual(passedLayers(layers, mounted.state()));
  expect(mounted.recording.errors).toEqual([]);
}

function layoutOf(mounted: Mounted, id: string) {
  return mounted.recording.layer(id)?.layout;
}

afterEach(() => {
  __resetForTest();
  vi.restoreAllMocks();
});

const HANDLER_CASES: [label: string, layers: MapLayerResponse[], edit: (handlers: Handlers, id: string) => void][] = [
  ['a toggle hides an extruded, labelled polygon', [{ ...extrusion, label_config: LABEL }], (h, id) => h.handleToggleVisibility(id)],
  ['a toggle shows an arrow line', [{ ...arrowLine, visible: false }], (h, id) => h.handleToggleVisibility(id)],
  ['a toggle shows a bounded cluster', [{ ...boundedCluster, visible: false }], (h, id) => h.handleToggleVisibility(id)],
  ['a toggle hides a hillshade and its relief', [relief], (h, id) => h.handleToggleVisibility(id)],
  ['a toggle hides a mixed layer', [mixedGeometry], (h, id) => h.handleToggleVisibility(id)],
  ['opacity on an extruded polygon', [extrusion], (h, id) => h.handleOpacityChange(id, 0.4)],
  ['opacity on an arrow line', [arrowLine], (h, id) => h.handleOpacityChange(id, 0.4)],
  ['opacity on a symbol layer', [symbol], (h, id) => h.handleOpacityChange(id, 0.4)],
  ['opacity on a heatmap', [heatmapByRamp], (h, id) => h.handleOpacityChange(id, 0.4)],
  ['opacity on a raster', [raster], (h, id) => h.handleOpacityChange(id, 0.4)],
  ['opacity on a hillshade', [relief], (h, id) => h.handleOpacityChange(id, 0.4)],
  ['opacity on a server cluster', [serverCluster], (h, id) => h.handleOpacityChange(id, 0.4)],
  ['opacity on a mixed layer', [mixedGeometry], (h, id) => h.handleOpacityChange(id, 0.4)],
  ['opacity on a point layer', [point], (h, id) => h.handleOpacityChange(id, 0.4)],
  ['a fill colour', [polygon], (h, id) => h.handlePaintChange(id, { ...polygon.paint, 'fill-color': '#123456' })],
  ['a line gradient', [line], (h, id) => h.handlePaintChange(id, gradientLine.paint)],
  ['a heatmap radius', [heatmapByRamp], (h, id) => h.handlePaintChange(id, { ...heatmapByRamp.paint, 'heatmap-radius': 40 })],
  ['a new relief ramp', [relief], (h, id) => h.handlePaintChange(id, { ...relief.paint, '_hypso-ramp': 'Reds' })],
  ['a raster contrast', [raster], (h, id) => h.handlePaintChange(id, { 'raster-contrast': 0.3 })],
  ['a fallback cluster colour', [fallbackCluster], (h, id) => h.handlePaintChange(id, { ...fallbackCluster.paint, 'circle-color': '#123456' })],
  ['a data-driven colour on a gradient line', [gradientLine], (h, id) => h.handleStyleConfigChange(
    id,
    { mode: 'categorical', column: 'kind', categories: [{ value: 'a', label: 'A', color: '#ff0000' }] } as StyleConfig,
    { ...gradientLine.paint, 'line-color': ['match', ['get', 'kind'], 'a', '#ff0000', '#cccccc'] },
  )],
  ['a colour over a pattern', [patternedPolygon], (h, id) => h.handleStyleConfigChange(
    id,
    patternedPolygon.style_config ?? null,
    { ...patternedPolygon.paint, 'fill-color': '#123456' },
  )],
  ['a pattern over a colour', [polygon], (h, id) => h.handleStyleConfigChange(
    id,
    polygon.style_config ?? null,
    { ...polygon.paint, 'fill-pattern': 'geolens-fill-hatch' },
  )],
  ['a cleared height column', [extrusion], (h, id) => h.handleStyleConfigChange(id, { builder: { heightScale: 1 } } as StyleConfig, extrusion.paint, { replace: true })],
  ['arrow mode turned off', [arrowLine], (h, id) => h.handleStyleConfigChange(id, { builder: arrowLine.style_config?.builder } as StyleConfig, arrowLine.paint, { replace: true })],
  ['a cluster colour ramp', [serverCluster], (h, id) => h.handleStyleConfigChange(
    id,
    withBuilder(serverCluster, { clusterColorRamp: [{ count: 0, color: '#fef08a' }, { count: 50, color: '#a16207' }] }).style_config ?? null,
    serverCluster.paint,
  )],
  ['a zoom range on an extruded polygon', [extrusion], (h, id) => h.handleLayoutChange(id, { _minzoom: 15, _maxzoom: 18 })],
  ['a zoom range on an arrow line', [arrowLine], (h, id) => h.handleLayoutChange(id, { ...arrowLine.layout, _minzoom: 5, _maxzoom: 12 })],
  ['a zoom range on a mixed layer', [mixedGeometry], (h, id) => h.handleLayoutChange(id, { _minzoom: 5, _maxzoom: 12 })],
  ['a removed line cap', [{ ...line, layout: { 'line-cap': 'square' } }], (h, id) => h.handleLayoutChange(id, {})],
  ['a filter on a mixed layer', [mixedGeometry], (h, id) => h.handleFilterChange(id, FILTER)],
  ['a filter on a server cluster', [serverCluster], (h, id) => h.handleFilterChange(id, FILTER)],
  ['a filter on an extruded, labelled polygon', [{ ...extrusion, label_config: LABEL }], (h, id) => h.handleFilterChange(id, FILTER)],
  ['a label on a point layer', [point], (h, id) => h.handleLabelChange(id, LABEL)],
  ['a cleared label', [{ ...point, label_config: LABEL }], (h, id) => h.handleLabelChange(id, null)],
  ['a label on a symbol layer', [symbol], (h, id) => h.handleLabelChange(id, LABEL)],
  ['a label on a heatmap', [heatmapByRamp], (h, id) => h.handleLabelChange(id, LABEL)],
];

describe('the handlers write through the layer writer', () => {
  it.each(HANDLER_CASES)('%s leaves the layers a pass leaves', (_label, layers, edit) => {
    const mounted = run(layers, (h) => edit(h, layers[0].id));
    expectMatchesPass(layers, mounted);
  });

  it('keeps a disabled outline hidden when a toggle shows the polygon', () => {
    const hidden = { ...withBuilder(polygon, { strokeDisabled: true }), visible: false };
    const mounted = run([hidden], (h) => h.handleToggleVisibility(hidden.id));
    expectMatchesPass([hidden], mounted);
    expect(layoutOf(mounted, `layer-${hidden.id}`)?.visibility).toBe('visible');
    expect(layoutOf(mounted, `layer-${hidden.id}-outline`)?.visibility).toBe('none');
  });

  it('keeps the count layer hidden when a toggle shows a cluster with counts off', () => {
    const hidden = { ...withBuilder(serverCluster, { clusterShowCounts: false }), visible: false };
    const mounted = run([hidden], (h) => h.handleToggleVisibility(hidden.id));
    expectMatchesPass([hidden], mounted);
    expect(layoutOf(mounted, `layer-${hidden.id}-cluster`)?.visibility).toBe('visible');
    expect(layoutOf(mounted, `layer-${hidden.id}-cluster-count`)?.visibility).toBe('none');
  });

  it('puts the master opacity on the layer opacity keys and leaves fill-opacity unmultiplied', () => {
    const layer = { ...polygon, paint: { ...polygon.paint, 'fill-opacity': 0.3 } };
    const mounted = run([layer], (h) => h.handleOpacityChange(layer.id, 0.5));
    expectMatchesPass([layer], mounted);
    expect(mounted.recording.layer(`layer-${layer.id}`)?.paint).toMatchObject({ 'fill-opacity': 0.3, 'fill-layer-opacity': 0.5 });
    expect(mounted.recording.layer(`layer-${layer.id}-outline`)?.paint['line-layer-opacity']).toBe(0.5);
  });

  it('writes no filter when clearing the filter of an unfiltered layer', () => {
    const layers = [{ ...extrusion, label_config: LABEL }];
    const mounted = run(layers, (h) => h.handleFilterChange(layers[0].id, null));
    expect(mounted.recording.callsTo('setFilter')).toEqual([]);
  });

  it('renames a hillshade legend entry in place, keeping its source', () => {
    const mounted = run([relief], (h) => h.handleStyleConfigChange(relief.id, { ...relief.style_config, legendLabel: 'Relief' } as StyleConfig, relief.paint));
    expectMatchesPass([relief], mounted);
    const rebuilt = mounted.recording.calls.filter(([method]) => ['removeSource', 'addSource', 'removeLayer', 'addLayer'].includes(method));
    expect(rebuilt).toEqual([]);
  });

  it('leaves a switch to terrain to the pass, which removes the layer, its relief and its source', () => {
    const mounted = run([relief], (h) => h.handleStyleConfigChange(relief.id, { render_mode: 'terrain' } as StyleConfig, relief.paint));
    expect(mounted.recording.calls).toEqual([]);

    mounted.sync(mounted.state());

    expect(mounted.recording.layerIds()).toEqual([]);
    expect(mounted.recording.getStyle().sources).toEqual({});
  });

  it('sets and clears a layout key no spec owns', () => {
    const mounted = run([polygon], (h) => h.handleLayoutChange(polygon.id, { 'fill-sort-key': 3 }));
    expect(layoutOf(mounted, `layer-${polygon.id}`)?.['fill-sort-key']).toBe(3);

    mounted.commit();
    act(() => mounted.handlers().handleLayoutChange(polygon.id, {}));

    expect(layoutOf(mounted, `layer-${polygon.id}`)).not.toHaveProperty('fill-sort-key');
  });

  it('draws a legacy layout dash as paint when the line editor moves it', () => {
    const legacy = { ...line, layout: { 'line-dasharray': [3, 2] } };
    const mounted = run([legacy], (h) => {
      h.handlePaintChange(legacy.id, { ...legacy.paint, 'line-dasharray': [3, 2] });
      h.handleLayoutChange(legacy.id, {});
    });
    expectMatchesPass([legacy], mounted);
    expect(mounted.recording.layer(`layer-${legacy.id}`)?.paint['line-dasharray']).toEqual([3, 2]);
    expect(layoutOf(mounted, `layer-${legacy.id}`)).not.toHaveProperty('line-dasharray');
  });

  it('writes a toggle at once, without waiting for a frame', () => {
    const frame = vi.spyOn(globalThis, 'requestAnimationFrame');
    const mountedMap = mountHandlers([polygon]);
    act(() => mountedMap.handlers().handleToggleVisibility(polygon.id));
    expect(layoutOf(mountedMap, `layer-${polygon.id}`)?.visibility).toBe('none');
    expect(frame).not.toHaveBeenCalled();
  });

  it('ignores an id that matches no layer', () => {
    const setDirty = vi.fn();
    let committed = false;
    const { recording } = syncedMap([polygon]);
    recording.calls.length = 0;
    const { result } = renderHook(() => useLayerMapSync([polygon], () => { committed = true; }, setDirty, { current: recording.map }));

    act(() => result.current.handleToggleVisibility('layer-that-does-not-exist'));

    expect(committed).toBe(false);
    expect(setDirty).not.toHaveBeenCalled();
    expect(recording.calls).toEqual([]);
  });
});

describe('the handlers write the newest state', () => {
  it('keeps every drawn layer hidden when a toggle lands between a paint edit and its frame', () => {
    const mounted = run([polygon], (h) => {
      h.handlePaintChange(polygon.id, { ...polygon.paint, 'fill-color': '#123456' });
      h.handleToggleVisibility(polygon.id);
    });
    expectMatchesPass([polygon], mounted);
    for (const id of mounted.recording.layerIds()) expect(layoutOf(mounted, id)?.visibility).toBe('none');
  });

  it('keeps a filter set just before a paint edit when the frame fires before the commit', () => {
    const mounted = run([polygon], (h) => {
      h.handleFilterChange(polygon.id, FILTER);
      h.handlePaintChange(polygon.id, { ...polygon.paint, 'fill-color': '#123456' });
    });
    expectMatchesPass([polygon], mounted);
    expect(mounted.recording.layer(`layer-${polygon.id}`)?.filter).toEqual(FILTER);
  });

  it('keeps a filter set just before a paint edit when the frame fires after the commit and a pass', () => {
    const mounted = mountHandlers([polygon]);
    act(() => {
      mounted.handlers().handleFilterChange(polygon.id, FILTER);
      mounted.handlers().handlePaintChange(polygon.id, { ...polygon.paint, 'fill-color': '#123456' });
    });
    mounted.commit();
    mounted.sync(mounted.state());
    mounted.flushFrames();

    expectMatchesPass([polygon], mounted);
    expect(mounted.recording.layer(`layer-${polygon.id}`)?.filter).toEqual(FILTER);
  });

  it('reverts a style and its layout together, as a pass would draw the saved layer', () => {
    const draft = { ...line, layout: { 'line-cap': 'square' }, paint: { ...line.paint, 'line-color': '#000000' } };
    const mounted = run([draft], (h) => {
      h.handleStyleConfigChange(draft.id, line.style_config ?? null, line.paint, { replace: true, restore: true });
      h.handleLayoutChange(draft.id, line.layout);
    });
    expectMatchesPass([draft], mounted);
    expect(layoutOf(mounted, `layer-${line.id}`)?.['line-cap']).toBe('round');
  });
});

describe('the handlers retry a write the style swap would drop', () => {
  function whileSwapping(layers: MapLayerResponse[]) {
    const mounted = mountHandlers(layers);
    mounted.recording.styleLoaded = false;
    return mounted;
  }

  function idleListeners(mounted: Mounted) {
    return mounted.recording.callsTo('once').filter(([event]) => event === 'idle').length;
  }

  it('replays a layout write on idle', () => {
    const layer = { ...line, layout: { 'line-miter-limit': 3 } };
    const mounted = whileSwapping([layer]);
    act(() => mounted.handlers().handleLayoutChange(layer.id, { 'line-cap': 'square', _minzoom: 4, _maxzoom: 12 }));
    expect(mounted.recording.calls.filter(([method]) => method !== 'once')).toEqual([]);

    mounted.recording.styleLoaded = true;
    act(() => mounted.recording.fire('idle'));

    const drawnLine = mounted.recording.layer(`layer-${layer.id}`);
    expect(drawnLine?.layout).toMatchObject({ 'line-cap': 'square' });
    expect(drawnLine?.layout).not.toHaveProperty('line-miter-limit');
    expect([drawnLine?.minzoom, drawnLine?.maxzoom]).toEqual([4, 12]);
  });

  it('replays a toggle on idle', () => {
    const mounted = whileSwapping([polygon]);
    act(() => mounted.handlers().handleToggleVisibility(polygon.id));
    expect(layoutOf(mounted, `layer-${polygon.id}`)?.visibility).toBe('visible');

    mounted.recording.styleLoaded = true;
    act(() => mounted.recording.fire('idle'));

    expect(layoutOf(mounted, `layer-${polygon.id}`)?.visibility).toBe('none');
  });

  it('lets a newer edit win when the style loads before idle fires', () => {
    const mounted = whileSwapping([polygon]);
    act(() => mounted.handlers().handleToggleVisibility(polygon.id, false));
    mounted.recording.styleLoaded = true;
    mounted.commit();
    act(() => mounted.handlers().handleToggleVisibility(polygon.id, true));
    act(() => mounted.recording.fire('idle'));

    expect(layoutOf(mounted, `layer-${polygon.id}`)?.visibility).toBe('visible');
  });

  it('arms one idle listener per layer and lands the last of its queued edits', () => {
    const mounted = whileSwapping([polygon]);
    act(() => mounted.handlers().handleToggleVisibility(polygon.id, false));
    mounted.commit();
    act(() => mounted.handlers().handleToggleVisibility(polygon.id, true));
    expect(idleListeners(mounted)).toBe(1);

    mounted.recording.styleLoaded = true;
    act(() => mounted.recording.fire('idle'));

    expect(layoutOf(mounted, `layer-${polygon.id}`)?.visibility).toBe('visible');
  });

  it('keeps a queued layout write when a toggle for the same layer follows', () => {
    const mounted = whileSwapping([polygon]);
    act(() => mounted.handlers().handleLayoutChange(polygon.id, { 'fill-sort-key': 2 }));
    act(() => mounted.handlers().handleToggleVisibility(polygon.id, false));

    mounted.recording.styleLoaded = true;
    act(() => mounted.recording.fire('idle'));

    expect(layoutOf(mounted, `layer-${polygon.id}`)).toMatchObject({ 'fill-sort-key': 2, visibility: 'none' });
  });

  it('lands a paint edit and a later opacity edit queued before idle', () => {
    const mounted = whileSwapping([polygon]);
    act(() => mounted.handlers().handlePaintChange(polygon.id, { ...polygon.paint, 'fill-color': '#123456' }));
    act(() => mounted.handlers().handleOpacityChange(polygon.id, 0.25));

    mounted.recording.styleLoaded = true;
    act(() => mounted.recording.fire('idle'));
    mounted.flushFrames();

    expectMatchesPass([polygon], mounted);
    expect(mounted.recording.layer(`layer-${polygon.id}`)?.paint).toMatchObject({ 'fill-color': '#123456', 'fill-layer-opacity': 0.25 });
  });

  it('writes straight through when the style is loaded', () => {
    const mounted = mountHandlers([polygon]);
    act(() => mounted.handlers().handleToggleVisibility(polygon.id));

    expect(layoutOf(mounted, `layer-${polygon.id}`)?.visibility).toBe('none');
    expect(idleListeners(mounted)).toBe(0);
  });
});
