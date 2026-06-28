import { describe, it, expect, vi } from 'vitest';
import { clusterAdapter, clusterCircleLayerId, clusterCountLayerId, clusterColorValue } from '../cluster-adapter';
import type { AdapterLayerInput } from '../types';

/**
 * Cluster adapter regression pins (1134-01 MAP-18).
 *
 * - BUG-01 pin: addLayers — all 3 sub-layers (cluster circle, cluster count, unclustered point)
 *   honor visible=false at add-time.
 * - syncPaint calls setFilter on all 3 sub-layers (intentional v1026 exception: cluster uses
 *   raw setFilter with combineFilter(unclusteredFilter, input.filter) / combineFilter(clusterFilter, input.filter)
 *   rather than the shared syncLayerFilter helper — the compound filter cannot go through syncLayerFilter
 *   because it requires the base cluster/unclustered predicate to be included unconditionally).
 * - syncVisibility sets visibility for all 3 sub-layers.
 * - getLayerIds returns [clusterCircleLayerId, clusterCountLayerId, layerId].
 */

function createMockMap(opts: { layerExists?: boolean } = {}) {
  const { layerExists = false } = opts;
  return {
    addLayer: vi.fn(),
    getLayer: vi.fn().mockReturnValue(layerExists ? { id: 'mock-layer' } : undefined),
    setFilter: vi.fn(),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getLayoutProperty: vi.fn().mockReturnValue(undefined),
    getPaintProperty: vi.fn().mockReturnValue(undefined),
  };
}

function makeInput(overrides: Partial<AdapterLayerInput> = {}): AdapterLayerInput {
  return {
    id: 'layer-cluster-1',
    dataset_table_name: 'ds_cluster',
    dataset_geometry_type: 'POINT',
    opacity: 1,
    visible: true,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    style_config: { render_mode: 'cluster' },
    sourceId: 'source-cluster-1',
    layerId: 'layer-cluster-1',
    sourceLayer: 'ds_cluster',
    sourceType: 'geojson',
    tileUrl: '/tiles/{z}/{x}/{y}',
    ...overrides,
  };
}

describe('cluster adapter — addLayers honors visible=false at add-time (BUG-01 PASS pin)', () => {
  it('all 3 sub-layers receive layout.visibility === "none" when visible=false', () => {
    const map = createMockMap({ layerExists: false });
    clusterAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    // clusterCircle + clusterCount + unclusteredPoint = 3 addLayer calls
    expect(map.addLayer).toHaveBeenCalledTimes(3);

    const calls = map.addLayer.mock.calls as Array<[{ id: string; layout?: { visibility?: string } }]>;

    const circleCall = calls.find(([c]) => c.id === clusterCircleLayerId('layer-cluster-1'));
    expect(circleCall).toBeDefined();
    expect(circleCall![0].layout?.visibility).toBe('none');

    const countCall = calls.find(([c]) => c.id === clusterCountLayerId('layer-cluster-1'));
    expect(countCall).toBeDefined();
    expect(countCall![0].layout?.visibility).toBe('none');

    const unclusteredCall = calls.find(([c]) => c.id === 'layer-cluster-1');
    expect(unclusteredCall).toBeDefined();
    expect(unclusteredCall![0].layout?.visibility).toBe('none');
  });
});

describe('cluster adapter — syncPaint calls setFilter on all 3 sub-layers', () => {
  /**
   * Cluster uses raw map.setFilter (NOT syncLayerFilter) because its filters are
   * compound: combineFilter(['has', 'point_count'], input.filter) for cluster layers
   * and combineFilter(['!', ['has', 'point_count']], input.filter) for unclustered.
   * This is the intentional v1026 exception — the compound filter requires the
   * cluster predicate to be included unconditionally.
   */
  it('setFilter is called on all sub-layers during syncPaint (compound filter shape)', () => {
    // For syncPaint to proceed, all 3 layers must be present
    const map = createMockMap({ layerExists: true });
    const input = makeInput({ filter: ['==', ['get', 'category'], 'A'] as unknown as import('maplibre-gl').FilterSpecification });
    clusterAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, input);

    // setFilter must have been called at least 3 times (one per sub-layer)
    expect(map.setFilter.mock.calls.length).toBeGreaterThanOrEqual(3);

    // Verify the cluster layers received compound filters (array filters)
    const filterCalls = map.setFilter.mock.calls as Array<[string, unknown]>;
    const clusterCircleFilter = filterCalls.find(([id]) => id === clusterCircleLayerId('layer-cluster-1'));
    expect(clusterCircleFilter).toBeDefined();
    // The compound filter must be an array (e.g. ['all', ['has', 'point_count'], ...])
    expect(Array.isArray(clusterCircleFilter![1])).toBe(true);

    const unclusteredFilter = filterCalls.find(([id]) => id === 'layer-cluster-1');
    expect(unclusteredFilter).toBeDefined();
    expect(Array.isArray(unclusteredFilter![1])).toBe(true);
  });
});

describe('cluster adapter — syncVisibility sets visibility for all 3 sub-layers', () => {
  it('setLayoutProperty called for all sub-layers when visible=false', () => {
    const map = createMockMap({ layerExists: true });
    clusterAdapter.syncVisibility(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    const visCalls = map.setLayoutProperty.mock.calls as Array<[string, string, string]>;
    const ids = visCalls.filter(([, prop, val]) => prop === 'visibility' && val === 'none').map(([id]) => id);

    expect(ids).toContain(clusterCircleLayerId('layer-cluster-1'));
    expect(ids).toContain(clusterCountLayerId('layer-cluster-1'));
    expect(ids).toContain('layer-cluster-1');
  });
});

describe('cluster adapter — getLayerIds returns [clusterCircle, clusterCount, layerId]', () => {
  it('returns all three sub-layer IDs in the documented order', () => {
    const ids = clusterAdapter.getLayerIds('cluster-abc');
    expect(ids).toEqual([
      clusterCircleLayerId('cluster-abc'),
      clusterCountLayerId('cluster-abc'),
      'cluster-abc',
    ]);
  });
});

describe('cluster adapter — BLDR-02 cluster color ramp (point_count step)', () => {
  it('clusterColorValue returns a flat color when ramp has fewer than 2 stops', () => {
    expect(clusterColorValue(undefined, '#abcdef')).toBe('#abcdef');
    expect(clusterColorValue([], '#abcdef')).toBe('#abcdef');
    expect(clusterColorValue([{ count: 0, color: '#111111' }], '#abcdef')).toBe('#abcdef');
  });

  it('clusterColorValue builds a strictly-ascending step expression on point_count', () => {
    const expr = clusterColorValue(
      [
        { count: 750, color: '#333333' },
        { count: 0, color: '#111111' },
        { count: 100, color: '#222222' },
      ],
      '#abcdef',
    );
    // base color first, then strictly-ascending (threshold, color) pairs
    expect(expr).toEqual(['step', ['get', 'point_count'], '#111111', 100, '#222222', 750, '#333333']);
  });

  it('clusterColorValue drops non-ascending/non-positive thresholds and falls back to flat if no valid step remains', () => {
    // base + a single threshold of 0 (dropped, must be > 0) → no valid step → flat
    expect(clusterColorValue([{ count: 0, color: '#111111' }, { count: 0, color: '#222222' }], '#abcdef')).toBe('#abcdef');
  });

  it('addLayers paints the cluster circle with the step expression when a ramp is configured', () => {
    const map = createMockMap({ layerExists: false });
    clusterAdapter.addLayers(
      map as unknown as import('maplibre-gl').Map,
      makeInput({
        style_config: {
          render_mode: 'cluster',
          builder: {
            clusterColorRamp: [
              { count: 0, color: '#111111' },
              { count: 100, color: '#222222' },
              { count: 750, color: '#333333' },
            ],
          },
        },
      }),
    );
    const calls = map.addLayer.mock.calls as Array<[{ id: string; paint?: Record<string, unknown> }]>;
    const circleCall = calls.find(([c]) => c.id === clusterCircleLayerId('layer-cluster-1'));
    expect(circleCall![0].paint?.['circle-color']).toEqual([
      'step', ['get', 'point_count'], '#111111', 100, '#222222', 750, '#333333',
    ]);
  });

  it('addLayers keeps a flat cluster circle color when no ramp is configured', () => {
    const map = createMockMap({ layerExists: false });
    clusterAdapter.addLayers(
      map as unknown as import('maplibre-gl').Map,
      makeInput({
        style_config: { render_mode: 'cluster', builder: { clusterColor: '#0a0a0a' } },
      }),
    );
    const calls = map.addLayer.mock.calls as Array<[{ id: string; paint?: Record<string, unknown> }]>;
    const circleCall = calls.find(([c]) => c.id === clusterCircleLayerId('layer-cluster-1'));
    expect(circleCall![0].paint?.['circle-color']).toBe('#0a0a0a');
  });
});
