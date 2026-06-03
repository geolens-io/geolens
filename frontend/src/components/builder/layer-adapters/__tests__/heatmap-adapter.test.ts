import { describe, it, expect, vi } from 'vitest';
import { heatmapAdapter } from '../heatmap-adapter';
import type { AdapterLayerInput } from '../types';

/**
 * Phase 1051 IN-02 (iter-2 re-review): direct unit coverage of CR-04's
 * compounding formula at heatmap-adapter.addLayers, and WR-01's
 * compounded write at heatmap-adapter.syncPaint.
 *
 * Previously, the only assertion was renderAs.test.ts checking the initial
 * patch contains `{ 'heatmap-opacity': 0.8 }` — not the runtime compounding
 * formula. A regression that re-introduced the original buggy formula
 * (`(opacity ?? 1) * 0.8` instead of `(rawPaint['heatmap-opacity'] ?? 0.8) *
 * (opacity ?? 1)`) would not fail any test. These tests pin the contract.
 */

interface AddLayerCall {
  paint: Record<string, unknown>;
}

interface MockMapHeatmap {
  addLayer: ReturnType<typeof vi.fn>;
  setFilter: ReturnType<typeof vi.fn>;
  getLayer: ReturnType<typeof vi.fn>;
  getPaintProperty: ReturnType<typeof vi.fn>;
  setPaintProperty: ReturnType<typeof vi.fn>;
  setLayoutProperty: ReturnType<typeof vi.fn>;
}

function createMockMap(opts: { layerExists?: boolean } = {}): MockMapHeatmap {
  const { layerExists = true } = opts;
  return {
    addLayer: vi.fn(),
    setFilter: vi.fn(),
    getLayer: vi.fn().mockReturnValue(layerExists ? { id: 'mock-layer' } : undefined),
    // Default getPaintProperty returns a sentinel that always differs from val,
    // forcing the paintValueChanged branch in syncPaint to fire.
    getPaintProperty: vi.fn().mockReturnValue(undefined),
    setPaintProperty: vi.fn(),
    setLayoutProperty: vi.fn(),
  };
}

function makeInput(overrides: Partial<AdapterLayerInput> = {}): AdapterLayerInput {
  return {
    id: 'layer-1',
    dataset_table_name: 'ds_1',
    dataset_geometry_type: 'POINT',
    opacity: 1,
    visible: true,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    style_config: { render_mode: 'heatmap' },
    sourceId: 'source-1',
    layerId: 'layer-1',
    sourceLayer: 'ds_1',
    sourceType: 'vector',
    tileUrl: 'http://example/{z}/{x}/{y}',
    ...overrides,
  };
}

describe('heatmap-adapter addLayers — Phase 1051 CR-04 opacity compounding', () => {
  it('Test 1: compounds stored heatmap-opacity with master opacity at add-time', () => {
    const map = createMockMap();

    heatmapAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput({
      paint: { 'heatmap-opacity': 0.5 },
      opacity: 0.6,
    }));

    expect(map.addLayer).toHaveBeenCalledTimes(1);
    const call = map.addLayer.mock.calls[0][0] as AddLayerCall;
    expect(call.paint['heatmap-opacity']).toBeCloseTo(0.5 * 0.6, 4);
  });

  it('Test 2: falls back to default 0.8 when rawPaint omits heatmap-opacity', () => {
    const map = createMockMap();

    heatmapAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput({
      paint: {},
      opacity: 0.5,
    }));

    const call = map.addLayer.mock.calls[0][0] as AddLayerCall;
    expect(call.paint['heatmap-opacity']).toBeCloseTo(0.8 * 0.5, 4);
  });

  it('Test 3: when master opacity is 1, stored heatmap-opacity is preserved unchanged', () => {
    const map = createMockMap();

    heatmapAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput({
      paint: { 'heatmap-opacity': 0.3 },
      opacity: 1,
    }));

    const call = map.addLayer.mock.calls[0][0] as AddLayerCall;
    expect(call.paint['heatmap-opacity']).toBeCloseTo(0.3, 4);
  });

  it('Test 4: regression guard — formula must NOT be the buggy (opacity ?? 1) * 0.8', () => {
    // The pre-CR-04 bug: every add ignored stored heatmap-opacity and multiplied
    // master opacity by the hard-coded default 0.8. With stored=0.5, opacity=1,
    // the buggy formula would yield 0.8, not 0.5.
    const map = createMockMap();

    heatmapAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput({
      paint: { 'heatmap-opacity': 0.5 },
      opacity: 1,
    }));

    const call = map.addLayer.mock.calls[0][0] as AddLayerCall;
    expect(call.paint['heatmap-opacity']).not.toBeCloseTo(0.8, 4);
    expect(call.paint['heatmap-opacity']).toBeCloseTo(0.5, 4);
  });
});

describe('heatmap-adapter syncPaint — Phase 1051 WR-01 single-write contract', () => {
  it('Test 5: heatmap-opacity is written exactly once per sync (compounded), never with the raw value', () => {
    const map = createMockMap();

    heatmapAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput({
      paint: { 'heatmap-opacity': 0.8 },
      opacity: 0.5,
    }));

    const opacityWrites = map.setPaintProperty.mock.calls.filter(
      ([, prop]) => prop === 'heatmap-opacity',
    );
    expect(opacityWrites).toHaveLength(1);
    // The single write must be the compounded value (0.4), not the raw (0.8).
    const writtenValue = opacityWrites[0][2];
    expect(writtenValue).toBeCloseTo(0.8 * 0.5, 4);
  });

  it('Test 6: syncPaint still propagates non-opacity heatmap-* properties through the generic loop', () => {
    const map = createMockMap();

    heatmapAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput({
      paint: { 'heatmap-radius': 42, 'heatmap-opacity': 0.8 },
      opacity: 1,
    }));

    const radiusWrites = map.setPaintProperty.mock.calls.filter(
      ([, prop]) => prop === 'heatmap-radius',
    );
    expect(radiusWrites).toHaveLength(1);
    expect(radiusWrites[0][2]).toBe(42);
  });
});

/**
 * 1134-01 MAP-18 regression pins — extend the existing heatmap harness.
 * Same 4-test contract used for all adapters:
 *   BUG-01, syncLayerFilter, syncVisibility, getLayerIds.
 */
describe('heatmap adapter — addLayers honors visible=false at add-time (BUG-01 PASS pin)', () => {
  it('addLayer called with layout.visibility === "none" when visible=false', () => {
    const map = createMockMap({ layerExists: false });
    heatmapAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    expect(map.addLayer).toHaveBeenCalledTimes(1);
    const call = map.addLayer.mock.calls[0][0] as { layout?: { visibility?: string } };
    expect(call.layout?.visibility).toBe('none');
  });
});

describe('heatmap adapter — syncPaint calls syncLayerFilter', () => {
  it('setFilter is called on the canvas when a filter is provided via syncPaint', () => {
    const map = createMockMap({ layerExists: true });
    const filter = ['==', ['get', 'intensity'], 'high'] as unknown as import('maplibre-gl').FilterSpecification;
    heatmapAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput({ filter }));

    expect(map.setFilter).toHaveBeenCalledWith('layer-1', filter);
  });
});

describe('heatmap adapter — syncVisibility uses syncSingleLayerVisibility helper', () => {
  it('setLayoutProperty called with visibility=none when visible=false', () => {
    const map = createMockMap({ layerExists: true });
    heatmapAdapter.syncVisibility(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-1', 'visibility', 'none');
  });
});

describe('heatmap adapter — getLayerIds returns [layerId]', () => {
  it('returns array containing only the base layerId', () => {
    const ids = heatmapAdapter.getLayerIds('heat-xyz');
    expect(ids).toEqual(['heat-xyz']);
  });
});
