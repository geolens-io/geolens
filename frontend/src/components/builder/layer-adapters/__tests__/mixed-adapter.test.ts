import { describe, it, expect, vi } from 'vitest';
import {
  mixedAdapter,
  mixedFamilyFilter,
  mixedInteractiveLayerIds,
  mixedLinesLayerId,
  mixedPointsLayerId,
} from '../mixed-adapter';
import type { AdapterLayerInput } from '../types';

/**
 * Mixed-geometry adapter pins (fix #430 codex r23).
 *
 * A GEOMETRY-sentinel (mixed-family sketch) layer must install one sublayer per
 * geometry family, each hard-filtered on ['geometry-type'], so no family is
 * silently dropped on maps. Like the cluster adapter, filters use raw
 * map.setFilter with the family predicate composed unconditionally — a data
 * filter must never REPLACE the family filter.
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
    id: 'layer-mixed-1',
    dataset_table_name: 'ds_sketch',
    dataset_geometry_type: 'GEOMETRY',
    opacity: 1,
    visible: true,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    style_config: null,
    sourceId: 'source-mixed-1',
    layerId: 'layer-mixed-1',
    sourceLayer: 'ds_sketch',
    tileUrl: '/tiles/{z}/{x}/{y}',
    ...overrides,
  };
}

const ALL_IDS = [
  'layer-mixed-1',
  'layer-mixed-1-outline',
  mixedLinesLayerId('layer-mixed-1'),
  mixedPointsLayerId('layer-mixed-1'),
];

describe('mixed adapter — addLayers installs one filtered sublayer per family', () => {
  it('adds fill + outline + lines + points, each with a geometry-type filter', () => {
    const map = createMockMap();
    mixedAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput());

    expect(map.addLayer).toHaveBeenCalledTimes(4);
    const calls = map.addLayer.mock.calls as Array<[{ id: string; type: string; filter?: unknown }]>;
    expect(calls.map(([c]) => c.id)).toEqual(ALL_IDS);
    expect(calls.map(([c]) => c.type)).toEqual(['fill', 'line', 'line', 'circle']);
    for (const [call] of calls) {
      expect(JSON.stringify(call.filter)).toContain('geometry-type');
    }
  });

  it('honors visible=false at add-time on every sublayer (BUG-01 pin)', () => {
    const map = createMockMap();
    mixedAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    const calls = map.addLayer.mock.calls as Array<[{ id: string; layout?: { visibility?: string } }]>;
    for (const [call] of calls) {
      expect(call.layout?.visibility).toBe('none');
    }
  });
});

describe('mixed adapter — data filters COMPOSE with family filters (never replace)', () => {
  const dataFilter = ['==', ['get', 'category'], 'A'] as unknown as import('maplibre-gl').FilterSpecification;

  it('mixedFamilyFilter wraps the data filter in ["all", family, data]', () => {
    const composed = mixedFamilyFilter('point', dataFilter) as unknown[];
    expect(composed[0]).toBe('all');
    expect(JSON.stringify(composed[1])).toContain('geometry-type');
    expect(composed[2]).toEqual(dataFilter);
  });

  it('mixedFamilyFilter returns the bare family filter when the data filter is empty', () => {
    for (const empty of [null, undefined, [] as unknown[]]) {
      const bare = mixedFamilyFilter('line', empty) as unknown[];
      expect(bare[0]).toBe('in');
      expect(JSON.stringify(bare)).toContain('LineString');
    }
  });

  it('syncPaint re-asserts a composed filter on every sublayer', () => {
    const map = createMockMap({ layerExists: true });
    mixedAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput({ filter: dataFilter }));

    const filterCalls = map.setFilter.mock.calls as Array<[string, unknown[]]>;
    for (const id of ALL_IDS) {
      const call = filterCalls.find(([layerId]) => layerId === id);
      expect(call).toBeDefined();
      expect(call![1][0]).toBe('all');
    }
  });
});

describe('mixed adapter — syncPaint self-heals missing sublayers', () => {
  it('re-adds the graph when sublayers are missing (cluster-adapter pattern)', () => {
    const map = createMockMap({ layerExists: false });
    mixedAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput());
    expect(map.addLayer).toHaveBeenCalledTimes(4);
  });
});

describe('mixed adapter — syncVisibility covers all sublayers', () => {
  it('setLayoutProperty visibility=none for all four ids', () => {
    const map = createMockMap({ layerExists: true });
    mixedAdapter.syncVisibility(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    const ids = (map.setLayoutProperty.mock.calls as Array<[string, string, string]>)
      .filter(([, prop, val]) => prop === 'visibility' && val === 'none')
      .map(([id]) => id);
    expect(ids).toEqual(ALL_IDS);
  });
});

describe('mixed adapter — id contracts', () => {
  it('getLayerIds returns fill, outline, lines, points', () => {
    expect(mixedAdapter.getLayerIds('layer-abc')).toEqual([
      'layer-abc',
      'layer-abc-outline',
      'layer-abc-lines',
      'layer-abc-points',
    ]);
  });

  it('mixedInteractiveLayerIds excludes the outline (fill already covers polygon hits)', () => {
    expect(mixedInteractiveLayerIds('layer-abc')).toEqual([
      'layer-abc',
      'layer-abc-lines',
      'layer-abc-points',
    ]);
  });
});
