import { describe, expect, it } from 'vitest';
import { fitsAggregateFilterLimits, getClusterSourceKey, getClusterSourceStrategy, shouldFetchClusterGeoJson } from '../cluster-source';
import type { Cql2Expression } from '@/lib/maplibre-filter-utils';

const baseLayer = {
  dataset_geometry_type: 'POINT',
  dataset_record_type: 'vector_dataset',
  layer_type: 'vector_geolens',
  is_dem: false,
  style_config: { render_mode: 'cluster' as const },
};

describe('cluster source strategy', () => {
  it('uses bounded GeoJSON for small point cluster layers', () => {
    const layer = { ...baseLayer, dataset_feature_count: 250 };

    expect(getClusterSourceStrategy(layer)).toMatchObject({ kind: 'bounded-geojson', status: 'eligible' });
    expect(shouldFetchClusterGeoJson(layer)).toBe(true);
  });

  it('uses server tiles for large point cluster layers', () => {
    const layer = { ...baseLayer, dataset_feature_count: 50_000 };

    expect(getClusterSourceStrategy(layer)).toMatchObject({ kind: 'server-tile', status: 'too-many-features' });
    expect(shouldFetchClusterGeoJson(layer)).toBe(false);
  });

  it('falls back for missing counts or unsupported geometry', () => {
    expect(getClusterSourceStrategy({ ...baseLayer, dataset_feature_count: null })).toMatchObject({
      kind: 'fallback',
      status: 'missing-count',
    });
    expect(getClusterSourceStrategy({
      ...baseLayer,
      dataset_feature_count: 50_000,
      dataset_geometry_type: 'POLYGON',
    })).toMatchObject({
      kind: 'fallback',
      status: 'not-point',
    });
  });
});

// The cluster fetch effect keys on this signature so that
// paint/opacity/filter edits (new layers-array identity, same cluster set)
// never re-trigger network GeoJSON fetches.
describe('getClusterSourceKey', () => {
  const clusterLayer = { ...baseLayer, id: 'l1', dataset_id: 'ds1', dataset_feature_count: 250 };

  it('returns an empty key when no layer is in cluster render mode', () => {
    const heatmap = { ...clusterLayer, style_config: { render_mode: 'heatmap' as const } };
    expect(getClusterSourceKey([heatmap])).toBe('');
  });

  it('is stable across array/object identity changes that leave cluster inputs unchanged', () => {
    const first = getClusterSourceKey([{ ...clusterLayer }]);
    const second = getClusterSourceKey([{ ...clusterLayer }]);
    expect(first).toBe(second);
    expect(first).toContain('l1|ds1|bounded-geojson');
  });

  it('changes when membership, dataset, or resolved strategy change', () => {
    const base = getClusterSourceKey([clusterLayer]);
    expect(getClusterSourceKey([{ ...clusterLayer, dataset_id: 'ds2' }])).not.toBe(base);
    expect(getClusterSourceKey([{ ...clusterLayer, dataset_feature_count: 50_000 }])).not.toBe(base);
    expect(getClusterSourceKey([clusterLayer, { ...clusterLayer, id: 'l2' }])).not.toBe(base);
  });
});

describe('fitsAggregateFilterLimits', () => {
  const isNull: Cql2Expression = { op: 'isNull', args: [{ property: 'a' }] };
  const nested = (levels: number) => {
    let node = isNull;
    for (let i = 0; i < levels; i += 1) node = { op: 'not', args: [node] };
    return node;
  };

  it('takes what the aggregate endpoint takes and nothing past its limits', () => {
    // Each `not` adds an object and a list; the endpoint refuses past 64 levels.
    expect(fitsAggregateFilterLimits(nested(30))).toBe(true);
    expect(fitsAggregateFilterLimits(nested(31))).toBe(false);
    const list = (count: number, size = 1): Cql2Expression => ({
      op: 'in',
      args: [{ property: 'a' }, Array.from({ length: count }, (_, i) => `${i}`.padStart(size, 'x'))],
    });
    expect(fitsAggregateFilterLimits(list(1000))).toBe(true);
    expect(fitsAggregateFilterLimits(list(1001))).toBe(false);
    expect(fitsAggregateFilterLimits(list(4, 2400))).toBe(true);
    expect(fitsAggregateFilterLimits(list(4, 2500))).toBe(false);
  });
});
