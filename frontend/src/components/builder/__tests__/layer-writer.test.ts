// The writer adds missing map layers, keeps the owned keys of existing ones in step, and registers the images they use.
import type { FilterSpecification } from 'maplibre-gl';
import { RecordingMap, TILE_ADOPTION_MS } from '@/test/recording-map';
import { SAVED_LAYERS } from '@/test/fixtures/saved-layers';
import { FIXTURE_TOKENS } from '@/test/fixtures/render-contexts';
import { getSourceIdForLayer, syncLayersToMap, toSyncInput } from '../map-sync';
import { addDescribedLayer, writeDescribedLayer, writeDescribedVisibility } from '../layer-writer';
import type { ImageSpec, LayerDrawing, LayerSpec } from '../layer-adapters/types';

const FILTER = ['==', ['get', 'kind'], 'school'] as FilterSpecification;
const STEP_COLOR = ['step', ['get', 'val'], '#ff0000', 100, '#0000ff'];
const HEAT_RAMP = ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(0,0,0,0)', 1, '#ff0000'];

function circleSpec(overrides: Partial<LayerSpec['layer']> = {}, owned: Partial<Pick<LayerSpec, 'ownedPaint' | 'ownedLayout'>> = {}): LayerSpec {
  return {
    layer: {
      id: 'points',
      type: 'circle',
      source: 'places',
      'source-layer': 'data.places',
      layout: { visibility: 'visible' },
      paint: { 'circle-color': '#3b82f6', 'circle-radius': 4 },
      ...overrides,
    },
    ownedPaint: owned.ownedPaint ?? ['circle-color', 'circle-radius', 'circle-blur'],
    ownedLayout: owned.ownedLayout ?? ['visibility'],
  };
}

function drawn(specs: LayerSpec[], images: ImageSpec[] = []): LayerDrawing {
  return { specs, images };
}

function mapWithSource() {
  const recording = new RecordingMap();
  recording.addSource('places', { type: 'vector', tiles: ['https://tiles.example.test/{z}/{x}/{y}.pbf'] });
  recording.calls.length = 0;
  return recording;
}

describe('writeDescribedLayer', () => {
  it('adds a missing spec with its paint, layout and filter', () => {
    const recording = mapWithSource();
    const spec = circleSpec({
      filter: FILTER,
      layout: { visibility: 'none', 'circle-sort-key': 2 },
      paint: { 'circle-color': STEP_COLOR, 'circle-radius': 4, 'circle-translate': [1, 2] },
    });

    writeDescribedLayer(recording.map, drawn([spec]));

    expect(recording.layer('points')).toEqual(spec.layer);
    expect(recording.errors).toEqual([]);
  });

  it('adds a layer with scalar stand-ins for its arrays, then writes the arrays and the filter', () => {
    const recording = mapWithSource();

    writeDescribedLayer(recording.map, drawn([circleSpec({
      filter: FILTER,
      paint: { 'circle-color': STEP_COLOR, 'circle-radius': 4, 'circle-translate': [1, 2] },
    }, { ownedPaint: ['circle-color', 'circle-radius'] })]));

    const [[added]] = recording.callsTo('addLayer') as [[{ paint: Record<string, unknown>; filter?: unknown }]];
    expect(added.paint).toEqual({ 'circle-color': '#ff0000', 'circle-radius': 4 });
    expect(added).not.toHaveProperty('filter');
    expect(recording.callsTo('setPaintProperty')).toEqual(expect.arrayContaining([
      ['points', 'circle-color', STEP_COLOR],
      ['points', 'circle-translate', [1, 2]],
    ]));
    expect(recording.callsTo('setFilter')).toEqual([['points', FILTER]]);
  });

  it('adds a layer without an expression-only key and writes the expression after', () => {
    const recording = mapWithSource();
    const heat: LayerSpec = {
      layer: { id: 'heat', type: 'heatmap', source: 'places', layout: {}, paint: { 'heatmap-color': HEAT_RAMP, 'heatmap-radius': 30 } },
      ownedPaint: ['heatmap-color', 'heatmap-radius'],
      ownedLayout: [],
    };

    writeDescribedLayer(recording.map, drawn([heat]));

    const [[added]] = recording.callsTo('addLayer') as [[{ paint: Record<string, unknown> }]];
    expect(added.paint).toEqual({ 'heatmap-radius': 30 });
    expect(recording.layer('heat')?.paint).toEqual(heat.layer.paint);
    expect(recording.errors).toEqual([]);
  });

  it('writes only the owned keys that changed on an existing layer', () => {
    const recording = mapWithSource();
    writeDescribedLayer(recording.map, drawn([circleSpec()]));
    recording.calls.length = 0;

    writeDescribedLayer(recording.map, drawn([circleSpec({ paint: { 'circle-color': '#3b82f6', 'circle-radius': 9 } })]));

    expect(recording.callsTo('setPaintProperty')).toEqual([['points', 'circle-radius', 9]]);
    expect(recording.callsTo('setLayoutProperty')).toEqual([]);
    expect(recording.callsTo('addLayer')).toEqual([]);
  });

  it('clears the owned keys a spec drops and leaves the rest of the layer alone', () => {
    const recording = mapWithSource();
    writeDescribedLayer(recording.map, drawn([circleSpec({
      layout: { visibility: 'visible', 'circle-sort-key': 2, 'text-field': 'kept' },
      paint: { 'circle-color': '#3b82f6', 'circle-radius': 4, 'circle-blur': 1, 'circle-pitch-scale': 'map' },
    }, { ownedLayout: ['visibility', 'circle-sort-key'] })]));

    writeDescribedLayer(recording.map, drawn([circleSpec({}, { ownedLayout: ['visibility', 'circle-sort-key'] })]));

    expect(recording.layer('points')?.paint).toEqual({ 'circle-color': '#3b82f6', 'circle-radius': 4, 'circle-pitch-scale': 'map' });
    expect(recording.layer('points')?.layout).toEqual({ visibility: 'visible', 'text-field': 'kept' });
  });

  it('keeps the filter of an existing layer in step and clears it when the spec has none', () => {
    const recording = mapWithSource();
    writeDescribedLayer(recording.map, drawn([circleSpec()]));

    writeDescribedLayer(recording.map, drawn([circleSpec({ filter: FILTER })]));
    expect(recording.layer('points')?.filter).toEqual(FILTER);

    writeDescribedLayer(recording.map, drawn([circleSpec()]));
    expect(recording.layer('points')).not.toHaveProperty('filter');
  });

  it('leaves the filter alone on a layer that has none', () => {
    const recording = mapWithSource();
    writeDescribedLayer(recording.map, drawn([circleSpec()]));

    writeDescribedLayer(recording.map, drawn([circleSpec({ paint: { 'circle-color': '#000000', 'circle-radius': 4 } })]));

    expect(recording.callsTo('setFilter')).toEqual([]);
  });

  it('clears the filter of a layer whose spec drops it', () => {
    const recording = mapWithSource();
    writeDescribedLayer(recording.map, drawn([circleSpec({ filter: FILTER })]));
    recording.calls.length = 0;

    writeDescribedLayer(recording.map, drawn([circleSpec()]));

    expect(recording.callsTo('setFilter')).toEqual([['points', null]]);
    expect(recording.layer('points')).not.toHaveProperty('filter');
  });

  it('makes no further writes for a spec MapLibre refuses', () => {
    const recording = new RecordingMap();

    writeDescribedLayer(recording.map, drawn([circleSpec({ filter: FILTER, paint: { 'circle-color': STEP_COLOR } })]));

    expect(recording.layer('points')).toBeUndefined();
    expect(recording.callsTo('setPaintProperty')).toEqual([]);
    expect(recording.callsTo('setFilter')).toEqual([]);
  });

  it('keeps writing the other specs when one throws', () => {
    const recording = mapWithSource();
    const addLayer = recording.addLayer.bind(recording);
    vi.spyOn(recording, 'addLayer').mockImplementation((layer, beforeId) => {
      if (layer.id === 'points') throw new Error('Style is not done loading');
      return addLayer(layer, beforeId);
    });

    writeDescribedLayer(recording.map, drawn([circleSpec(), circleSpec({ id: 'labels' })]));

    expect(recording.layerIds()).toEqual(['labels']);
  });

  it('registers a sprite once, against the page origin', () => {
    const recording = mapWithSource();
    const sprite: ImageSpec = { kind: 'sprite', id: 'geolens', url: '/api/maps/sprites/geolens' };

    writeDescribedLayer(recording.map, drawn([circleSpec()], [sprite]));
    writeDescribedLayer(recording.map, drawn([circleSpec()], [sprite]));

    expect(recording.callsTo('addSprite')).toEqual([['geolens', `${window.location.origin}/api/maps/sprites/geolens`]]);
  });

  it('registers an image once, building its pixels only when the map lacks it', () => {
    const recording = mapWithSource();
    const pixels = { width: 1, height: 1, data: new Uint8ClampedArray(4) };
    const data = vi.fn(() => pixels);
    const arrow: ImageSpec = { kind: 'image', id: 'arrow', data, options: { sdf: true, pixelRatio: 1 } };

    writeDescribedLayer(recording.map, drawn([], [arrow]));
    writeDescribedLayer(recording.map, drawn([], [arrow]));

    expect(recording.callsTo('addImage')).toEqual([['arrow', { sdf: true, pixelRatio: 1 }]]);
    expect(data).toHaveBeenCalledTimes(1);
  });
});

describe('addDescribedLayer', () => {
  it('adds every spec without asking the map first', () => {
    const recording = mapWithSource();
    writeDescribedLayer(recording.map, drawn([circleSpec()]));
    recording.calls.length = 0;

    addDescribedLayer(recording.map, drawn([circleSpec(), circleSpec({ id: 'labels' })]));

    expect(recording.callsTo('addLayer').map(([layer]) => (layer as { id: string }).id)).toEqual(['points', 'labels']);
    expect(recording.layerIds()).toEqual(['points', 'labels']);
  });
});

describe('writeDescribedVisibility', () => {
  it('sets the visibility of the specs on the map and nothing else', () => {
    const recording = mapWithSource();
    writeDescribedLayer(recording.map, drawn([circleSpec()]));
    recording.calls.length = 0;
    const hidden = { layout: { visibility: 'none' }, paint: { 'circle-color': '#000000' } };

    writeDescribedVisibility(recording.map, drawn([circleSpec(hidden), circleSpec({ ...hidden, id: 'missing' })]));

    expect(recording.calls).toEqual([['setLayoutProperty', 'points', 'visibility', 'none']]);
    expect(recording.layerIds()).toEqual(['points']);
  });
});

describe('a sync pass that writes a layer and a new tile URL together', () => {
  it('refreshes the tiles once the source adopts the new URL', () => {
    vi.useFakeTimers();
    try {
      const recording = new RecordingMap();
      const managed = { current: new Set<string>() };
      const order = { current: '' };
      const layer = toSyncInput(SAVED_LAYERS.point);
      const tokens = new Map(FIXTURE_TOKENS);
      syncLayersToMap(recording.map, [layer], tokens, undefined, managed, order);

      const edited = {
        ...layer,
        paint: { ...layer.paint, 'circle-radius': 9 },
        popup_config: { enabled: true, expression: null, visible_fields: ['name'] },
      };
      syncLayersToMap(recording.map, [edited], tokens, undefined, managed, order);

      const sourceId = getSourceIdForLayer(layer);
      expect(recording.callsTo('setTiles')).toEqual([[sourceId, [expect.stringContaining('cols=name')]]]);
      expect(recording.layer(`layer-${layer.id}`)?.paint['circle-radius']).toBe(9);
      vi.advanceTimersByTime(TILE_ADOPTION_MS - 1);
      expect(recording.callsTo('refreshTiles')).toEqual([]);
      vi.runAllTimers();
      expect(recording.callsTo('refreshTiles')).toEqual([[sourceId]]);
    } finally {
      vi.useRealTimers();
    }
  });
});
