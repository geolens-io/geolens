/**
 * Unit tests for `applySublayerOverrides` (Phase 1059 BSE-01).
 *
 * Uses a fake MapLibre map with vi.fn() mocks for every method the helper touches.
 * Mirrors the fakeMap pattern from ViewerMap.basemap-config.test.tsx.
 *
 * Test cases:
 *   1.  noop_when_overrides_undefined
 *   2.  noop_when_overrides_null
 *   3.  noop_when_overrides_empty_dict
 *   4.  applies_stroke_color_to_classified_road_layers
 *   5.  applies_stroke_width_to_classified_road_layers
 *   6.  applies_casing_to_boundary_layers
 *   7.  applies_min_max_zoom_via_setLayerZoomRange
 *   8.  applies_opacity_multiplicatively_over_layer_type_symbol
 *   9.  null_override_value_does_not_clear
 *  10.  idle_retry_when_style_not_loaded
 *  11.  swallows_setPaintProperty_throws_per_layer
 *  12.  unknown_sublayer_id_silently_ignored
 *  13.  respects_sourcePrefix_for_viewer
 *  14.  applies_multiple_overrides_in_one_call
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { applySublayerOverrides } from '../basemap-style-mutation';

// ---------------------------------------------------------------------------
// Fake MapLibre map factory
// ---------------------------------------------------------------------------

type FakeMap = {
  isStyleLoaded: ReturnType<typeof vi.fn>;
  getStyle: ReturnType<typeof vi.fn>;
  getLayer: ReturnType<typeof vi.fn>;
  setPaintProperty: ReturnType<typeof vi.fn>;
  setLayoutProperty: ReturnType<typeof vi.fn>;
  setLayerZoomRange: ReturnType<typeof vi.fn>;
  once: ReturnType<typeof vi.fn>;
};

function makeFakeMap(overrides: Partial<FakeMap> = {}): FakeMap {
  return {
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({ layers: [] })),
    getLayer: vi.fn((id: string) => ({ id })), // truthy by default — layer exists
    setPaintProperty: vi.fn(),
    setLayoutProperty: vi.fn(),
    setLayerZoomRange: vi.fn(),
    once: vi.fn(),
    ...overrides,
  };
}

// Minimal style layers for testing
function makeRoadLineLayer(id = 'road-primary') {
  return { id, type: 'line', source: 'openmaptiles', 'source-layer': 'road', layout: {}, paint: {} };
}

function makeRoadSymbolLayer(id = 'road-label') {
  return { id, type: 'symbol', source: 'openmaptiles', 'source-layer': 'road', layout: { 'text-field': '{name}' }, paint: {} };
}

function makeBoundaryLineLayer(id = 'admin-boundary') {
  return { id, type: 'line', source: 'openmaptiles', 'source-layer': 'boundary', layout: {}, paint: {} };
}

function makeBoundaryLineCasingLayer(id = 'admin-boundary-casing') {
  return { id, type: 'line', source: 'openmaptiles', 'source-layer': 'boundary', layout: {}, paint: {} };
}

function makeBuildingLayer(id = 'building') {
  return { id, type: 'fill-extrusion', source: 'openmaptiles', 'source-layer': 'building', layout: {}, paint: {} };
}

function makeFillLayer(id = 'water') {
  return { id, type: 'fill', source: 'openmaptiles', 'source-layer': 'water', layout: {}, paint: {} };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('applySublayerOverrides', () => {
  let map: FakeMap;

  beforeEach(() => {
    map = makeFakeMap();
  });

  it('noop_when_overrides_undefined', () => {
    applySublayerOverrides(map as never, undefined);
    expect(map.getStyle).not.toHaveBeenCalled();
    expect(map.setPaintProperty).not.toHaveBeenCalled();
    expect(map.setLayerZoomRange).not.toHaveBeenCalled();
  });

  it('noop_when_overrides_null', () => {
    applySublayerOverrides(map as never, null);
    expect(map.getStyle).not.toHaveBeenCalled();
    expect(map.setPaintProperty).not.toHaveBeenCalled();
    expect(map.setLayerZoomRange).not.toHaveBeenCalled();
  });

  it('noop_when_overrides_empty_dict', () => {
    applySublayerOverrides(map as never, {});
    expect(map.getStyle).not.toHaveBeenCalled();
    expect(map.setPaintProperty).not.toHaveBeenCalled();
    expect(map.setLayerZoomRange).not.toHaveBeenCalled();
  });

  it('applies_stroke_color_to_classified_road_layers', () => {
    map.getStyle.mockReturnValue({ layers: [makeRoadLineLayer('road-primary')] });

    applySublayerOverrides(map as never, { road: { stroke_color: '#ff0000' } });

    expect(map.setPaintProperty).toHaveBeenCalledWith('road-primary', 'line-color', '#ff0000');
  });

  it('applies_stroke_width_to_classified_road_layers', () => {
    map.getStyle.mockReturnValue({ layers: [makeRoadLineLayer('road-secondary')] });

    applySublayerOverrides(map as never, { road: { stroke_width: 3 } });

    expect(map.setPaintProperty).toHaveBeenCalledWith('road-secondary', 'line-width', 3);
  });

  it('applies_casing_to_boundary_layers', () => {
    map.getStyle.mockReturnValue({
      layers: [
        makeBoundaryLineLayer('admin-boundary'),
        makeBoundaryLineCasingLayer('admin-boundary-casing'),
      ],
    });

    applySublayerOverrides(map as never, {
      boundary: { casing_color: '#000000', casing_width: 1 },
    });

    // casing_width → line-gap-width on both boundary layers
    expect(map.setPaintProperty).toHaveBeenCalledWith('admin-boundary', 'line-gap-width', 1);
    expect(map.setPaintProperty).toHaveBeenCalledWith('admin-boundary-casing', 'line-gap-width', 1);
    // casing_color → line-color ONLY on the layer whose id includes 'casing'
    expect(map.setPaintProperty).toHaveBeenCalledWith('admin-boundary-casing', 'line-color', '#000000');
    // Should NOT set line-color on the main boundary layer for casing_color
    const casingColorCalls = (map.setPaintProperty as ReturnType<typeof vi.fn>).mock.calls.filter(
      ([id, prop]: [string, string]) => id === 'admin-boundary' && prop === 'line-color',
    );
    expect(casingColorCalls).toHaveLength(0);
  });

  it('applies_min_max_zoom_via_setLayerZoomRange', () => {
    map.getStyle.mockReturnValue({ layers: [makeRoadLineLayer('road-primary')] });

    applySublayerOverrides(map as never, { road: { min_zoom: 5, max_zoom: 18 } });

    expect(map.setLayerZoomRange).toHaveBeenCalledWith('road-primary', 5, 18);
    expect(map.setPaintProperty).not.toHaveBeenCalled();
  });

  it('applies_opacity_to_line_layer', () => {
    map.getStyle.mockReturnValue({ layers: [makeRoadLineLayer('road-primary')] });

    applySublayerOverrides(map as never, { road: { opacity: 0.5 } });

    expect(map.setPaintProperty).toHaveBeenCalledWith('road-primary', 'line-opacity', 0.5);
  });

  it('applies_opacity_multiplicatively_over_layer_type_symbol', () => {
    map.getStyle.mockReturnValue({ layers: [makeRoadSymbolLayer('road-label')] });

    applySublayerOverrides(map as never, { road: { opacity: 0.5 } });

    // Symbol layers get both text-opacity and icon-opacity
    expect(map.setPaintProperty).toHaveBeenCalledWith('road-label', 'text-opacity', 0.5);
    expect(map.setPaintProperty).toHaveBeenCalledWith('road-label', 'icon-opacity', 0.5);
  });

  it('applies_opacity_to_building_fill_extrusion', () => {
    map.getStyle.mockReturnValue({ layers: [makeBuildingLayer('building-extrusion')] });

    applySublayerOverrides(map as never, { building: { opacity: 0.7 } });

    expect(map.setPaintProperty).toHaveBeenCalledWith('building-extrusion', 'fill-extrusion-opacity', 0.7);
  });

  it('null_override_value_does_not_clear', () => {
    map.getStyle.mockReturnValue({ layers: [makeRoadLineLayer('road-primary')] });

    applySublayerOverrides(map as never, { road: { stroke_color: null, stroke_width: null } });

    // null fields = "use basemap default" = no-op; no setPaintProperty call
    expect(map.setPaintProperty).not.toHaveBeenCalled();
  });

  it('idle_retry_when_style_not_loaded', () => {
    // Style not yet loaded — helper should register an 'idle' listener and return
    map.isStyleLoaded.mockReturnValue(false);
    map.getStyle.mockReturnValue({ layers: [makeRoadLineLayer('road-primary')] });

    applySublayerOverrides(map as never, { road: { stroke_color: '#ff0000' } });

    // Should have registered the idle listener
    expect(map.once).toHaveBeenCalledTimes(1);
    expect(map.once.mock.calls[0][0]).toBe('idle');
    // Should NOT have mutated anything yet
    expect(map.setPaintProperty).not.toHaveBeenCalled();
    expect(map.getStyle).not.toHaveBeenCalled();

    // Now simulate style loaded and fire the idle callback
    map.isStyleLoaded.mockReturnValue(true);
    const idleCallback = map.once.mock.calls[0][1] as () => void;
    idleCallback();

    // After idle fires, mutations should happen
    expect(map.setPaintProperty).toHaveBeenCalledWith('road-primary', 'line-color', '#ff0000');
  });

  it('swallows_setPaintProperty_throws_per_layer', () => {
    // Two matching road layers; the first throws, the second should still be processed
    map.getStyle.mockReturnValue({
      layers: [makeRoadLineLayer('road-first'), makeRoadLineLayer('road-second')],
    });
    (map.setPaintProperty as ReturnType<typeof vi.fn>).mockImplementation((id: string) => {
      if (id === 'road-first') throw new Error('boom');
    });

    // Should not throw
    expect(() => {
      applySublayerOverrides(map as never, { road: { stroke_color: '#ff0000' } });
    }).not.toThrow();

    // Both layers were attempted (helper continued after first throw)
    expect(map.setPaintProperty).toHaveBeenCalledTimes(2);
    expect(map.setPaintProperty).toHaveBeenCalledWith('road-first', 'line-color', '#ff0000');
    expect(map.setPaintProperty).toHaveBeenCalledWith('road-second', 'line-color', '#ff0000');
  });

  it('unknown_sublayer_id_silently_ignored', () => {
    map.getStyle.mockReturnValue({ layers: [makeRoadLineLayer('road-primary')] });

    // 'some_future_provider' is not in SUBLAYER_CLASSIFIERS
    applySublayerOverrides(map as never, { some_future_provider: { stroke_color: '#ffffff' } });

    // No classifier found → zero mutations
    expect(map.setPaintProperty).not.toHaveBeenCalled();
    expect(map.setLayerZoomRange).not.toHaveBeenCalled();
  });

  it('respects_sourcePrefix_for_viewer', () => {
    // Style includes a road layer with source 'viewer-source-abc' (data layer in viewer context)
    // and a road layer with source 'openmaptiles' (basemap layer, no viewer prefix)
    const viewerDataLayer = {
      id: 'viewer-layer-road-data',
      type: 'line',
      source: 'viewer-source-abc',
      'source-layer': 'road',
      layout: {},
      paint: {},
    };
    const basemapRoadLayer = makeRoadLineLayer('road-primary'); // source = 'openmaptiles'

    map.getStyle.mockReturnValue({ layers: [viewerDataLayer, basemapRoadLayer] });

    // Passing VIEWER_SOURCE_PREFIX — data layers with that prefix should be skipped
    applySublayerOverrides(map as never, { road: { stroke_color: '#00ff00' } }, 'viewer-source-');

    // Only the basemap road layer should be mutated
    expect(map.setPaintProperty).toHaveBeenCalledTimes(1);
    expect(map.setPaintProperty).toHaveBeenCalledWith('road-primary', 'line-color', '#00ff00');
    expect(map.setPaintProperty).not.toHaveBeenCalledWith('viewer-layer-road-data', 'line-color', '#00ff00');
  });

  it('applies_multiple_overrides_in_one_call', () => {
    map.getStyle.mockReturnValue({
      layers: [
        makeRoadLineLayer('road-primary'),
        makeBoundaryLineLayer('admin-boundary'),
        makeBuildingLayer('building-extrusion'),
      ],
    });

    applySublayerOverrides(map as never, {
      road: { stroke_color: '#f00' },
      boundary: { stroke_width: 2 },
      building: { opacity: 0.3 },
    });

    expect(map.setPaintProperty).toHaveBeenCalledWith('road-primary', 'line-color', '#f00');
    expect(map.setPaintProperty).toHaveBeenCalledWith('admin-boundary', 'line-width', 2);
    expect(map.setPaintProperty).toHaveBeenCalledWith('building-extrusion', 'fill-extrusion-opacity', 0.3);
  });

  it('does_not_mutate_non_line_layers_for_stroke_color', () => {
    // Fill layer classified as road should not get line-color (only line layers)
    const roadFillLayer = { ...makeFillLayer('road-fill'), 'source-layer': 'road' };
    map.getStyle.mockReturnValue({ layers: [roadFillLayer] });

    applySublayerOverrides(map as never, { road: { stroke_color: '#ff0000' } });

    // Fill layer doesn't match road (isRoadLayer checks type='line'|'symbol')
    expect(map.setPaintProperty).not.toHaveBeenCalled();
  });

  it('applies_only_min_zoom_when_max_zoom_null', () => {
    map.getStyle.mockReturnValue({ layers: [makeRoadLineLayer('road-primary')] });

    applySublayerOverrides(map as never, { road: { min_zoom: 8, max_zoom: null } });

    // max_zoom is null → defaults to 22 (matches UI displayed default in BasemapSublayerEditorScene)
    // WR-01: was 24 (MapLibre max) which would silently extend layers beyond what the UI shows.
    expect(map.setLayerZoomRange).toHaveBeenCalledWith('road-primary', 8, 22);
  });

  it('getLayer_returns_falsy_prevents_mutations', () => {
    // When getLayer returns falsy (layer doesn't exist in map), skip mutation
    map.getStyle.mockReturnValue({ layers: [makeRoadLineLayer('road-primary')] });
    map.getLayer.mockReturnValue(null);

    applySublayerOverrides(map as never, { road: { stroke_color: '#ff0000' } });

    // getLayer returned null → setPaintProperty not called
    expect(map.setPaintProperty).not.toHaveBeenCalled();
  });
});
