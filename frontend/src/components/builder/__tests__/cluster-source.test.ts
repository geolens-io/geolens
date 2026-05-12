import { describe, expect, it } from 'vitest';
import { getClusterSourceStrategy, shouldFetchClusterGeoJson, shouldUseServerClusterTiles } from '../cluster-source';

const baseLayer = {
  dataset_geometry_type: 'POINT',
  dataset_record_type: 'vector_dataset',
  layer_type: 'vector_geolens',
  is_dem: false,
  style_config: { render_mode: 'cluster' },
};

describe('cluster source strategy', () => {
  it('uses bounded GeoJSON for small point cluster layers', () => {
    const layer = { ...baseLayer, dataset_feature_count: 250 };

    expect(getClusterSourceStrategy(layer)).toMatchObject({ kind: 'bounded-geojson', status: 'eligible' });
    expect(shouldFetchClusterGeoJson(layer)).toBe(true);
    expect(shouldUseServerClusterTiles(layer)).toBe(false);
  });

  it('uses server tiles for large point cluster layers', () => {
    const layer = { ...baseLayer, dataset_feature_count: 50_000 };

    expect(getClusterSourceStrategy(layer)).toMatchObject({ kind: 'server-tile', status: 'too-many-features' });
    expect(shouldFetchClusterGeoJson(layer)).toBe(false);
    expect(shouldUseServerClusterTiles(layer)).toBe(true);
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
