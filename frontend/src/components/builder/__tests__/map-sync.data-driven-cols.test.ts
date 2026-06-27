import { describe, it, expect } from 'vitest';
import {
  getDataDrivenColumnsForLayer,
  getDataDrivenColumnsForSource,
  type SyncLayerInput,
} from '@/components/builder/map-sync';

describe('getDataDrivenColumnsForLayer', () => {
  it('extracts the categorical / graduated column from style_config', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: { mode: 'categorical', column: 'economy', ramp: 'YlOrRd', categories: [] },
      paint: {},
    });
    expect(cols).toEqual(['economy']);
  });

  it('extracts the heatmap weight column from paint', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: { '_heatmap-weight-column': 'magnitude' },
    });
    expect(cols).toEqual(['magnitude']);
  });

  it('extracts the 3D extrusion height column from paint', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: { '_height_column': 'elevation_m' },
    });
    expect(cols).toEqual(['elevation_m']);
  });

  it('finds columns referenced via ["get", "<col>"] expressions', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {
        'fill-color': [
          'case',
          ['==', ['get', 'economy'], null],
          '#ccc',
          [
            'match',
            ['get', 'economy'],
            'G7', '#e41a1c',
            'BRIC', '#629363',
            '#cccccc',
          ],
        ],
      },
    });
    expect(cols).toEqual(['economy']);
  });

  it('dedupes columns referenced from multiple sources', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: { mode: 'graduated', column: 'pop_est', ramp: 'YlOrRd', breaks: [] },
      paint: {
        'fill-color': ['interpolate', ['linear'], ['get', 'pop_est'], 0, '#fff', 1000000, '#000'],
      },
    });
    expect(cols).toEqual(['pop_est']);
  });

  it('returns empty array for layers with no data-driven inputs', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: { 'fill-color': '#3b82f6' },
    });
    expect(cols).toEqual([]);
  });

  it('handles nested expressions and multiple column references', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {
        'fill-color': ['match', ['get', 'category'], 'a', '#f00', '#fff'],
        'fill-opacity': ['*', ['get', 'opacity_factor'], 0.5],
      },
    });
    expect(cols.sort()).toEqual(['category', 'opacity_factor']);
  });

  it('returns label_config.column when style_config and paint have no columns', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {},
      label_config: { column: 'NAME', fontSize: 12, placement: 'point', minZoom: 0, maxZoom: 22, allowOverlap: false },
    });
    expect(cols).toEqual(['NAME']);
  });

  it('dedupes label_config.column when it equals the style_config column', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: { mode: 'graduated', column: 'pop_est', ramp: 'YlOrRd', breaks: [] },
      paint: {},
      label_config: { column: 'pop_est', fontSize: 12, placement: 'point', minZoom: 0, maxZoom: 22, allowOverlap: false },
    });
    expect(cols).toEqual(['pop_est']);
  });

  it('contributes nothing when label_config is null', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {},
      label_config: null,
    });
    expect(cols).toEqual([]);
  });

  it('contributes nothing when label_config is undefined', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {},
    });
    expect(cols).toEqual([]);
  });

  it('contributes nothing when label_config has an empty column string', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {},
      label_config: { column: '', fontSize: 12, placement: 'point', minZoom: 0, maxZoom: 22, allowOverlap: false },
    });
    expect(cols).toEqual([]);
  });

  // builder-audit #338 P1-03: filter-only columns must survive the z<10 attribute
  // budget, so the column collector now walks layer.filter for get/has refs.
  it('extracts a filter-only column referenced via ["get", col] (P1-03)', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: { 'fill-color': '#3b82f6' },
      filter: ['==', ['get', 'status'], 'active'],
    });
    expect(cols).toEqual(['status']);
  });

  it('extracts a filter column referenced via ["has", col] (P1-03)', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {},
      filter: ['all', ['has', 'zone'], ['>', ['get', 'pop'], 100]],
    });
    expect(cols.sort()).toEqual(['pop', 'zone']);
  });

  it('unions filter columns with paint/label columns and dedupes', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: { mode: 'graduated', column: 'pop_est', ramp: 'YlOrRd', breaks: [] },
      paint: {},
      filter: ['all', ['==', ['get', 'pop_est'], 0], ['has', 'region']],
    });
    expect(cols.sort()).toEqual(['pop_est', 'region']);
  });
});

describe('getDataDrivenColumnsForSource', () => {
  function makeLayer(
    id: string,
    dataset_table_name: string,
    style_config: SyncLayerInput['style_config'] = null,
    paint: SyncLayerInput['paint'] = {},
    label_config: SyncLayerInput['label_config'] = null,
  ): SyncLayerInput {
    return {
      id,
      dataset_id: `ds-${id}`,
      dataset_table_name,
      dataset_geometry_type: 'MultiPolygon',
      opacity: 1,
      visible: true,
      paint,
      layout: {},
      filter: null,
      style_config,
      label_config,
    };
  }

  it('unions columns from every layer sharing a source via dedupe', () => {
    const layers: SyncLayerInput[] = [
      makeLayer('l1', 'countries', { mode: 'categorical', column: 'economy', ramp: 'YlOrRd', categories: [] }),
      makeLayer('l2', 'countries', { mode: 'graduated', column: 'pop_est', ramp: 'YlOrRd', breaks: [] }),
      makeLayer('l3', 'reefs', { mode: 'categorical', column: 'type', ramp: 'YlOrRd', categories: [] }),
    ];
    const cols = getDataDrivenColumnsForSource('source-data-countries', layers);
    expect(cols.sort()).toEqual(['economy', 'pop_est']);
  });

  it('unions label_config.column from layers sharing a deduped source', () => {
    const layers: SyncLayerInput[] = [
      makeLayer(
        'l1',
        'counties',
        { mode: 'graduated', column: 'median_income', ramp: 'YlOrRd', breaks: [] },
        {},
        { column: 'NAME', fontSize: 12, placement: 'point', minZoom: 0, maxZoom: 22, allowOverlap: false },
      ),
      makeLayer('l2', 'counties', null, {}, null),
    ];
    const cols = getDataDrivenColumnsForSource('source-data-counties', layers);
    expect(cols.sort()).toEqual(['NAME', 'median_income']);
  });

  it('returns empty array when no layer matches the source', () => {
    const layers: SyncLayerInput[] = [
      makeLayer('l1', 'countries', { mode: 'categorical', column: 'economy', ramp: 'YlOrRd', categories: [] }),
    ];
    const cols = getDataDrivenColumnsForSource('source-data-other_table', layers);
    expect(cols).toEqual([]);
  });

  it('ignores layers using a different source even on the same table (cluster)', () => {
    // A cluster layer takes a per-layer source-id; even at the same table_name,
    // it does NOT share `source-data-{table}` with non-cluster layers.
    const layers: SyncLayerInput[] = [
      makeLayer('l1', 'countries', { mode: 'categorical', column: 'economy', ramp: 'YlOrRd', categories: [] }),
      // simulated cluster layer
      {
        ...makeLayer('l2', 'countries'),
        style_config: { render_mode: 'cluster' } as SyncLayerInput['style_config'],
      },
    ];
    const cols = getDataDrivenColumnsForSource('source-data-countries', layers);
    expect(cols).toEqual(['economy']);
  });
});
