import { describe, it, expect } from 'vitest';
import {
  getDataDrivenColumnsForLayer,
  getDataDrivenColumnsForSource,
  toSyncInput,
  type SyncLayerInput,
} from '@/components/builder/map-sync';
import type { MapLayerResponse } from '@/types/api';

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

  // #350: popup custom visible_fields + title-template placeholders must be
  // requested via cols= or they get stripped at z<10 and the popup shows
  // "No attributes" despite being configured.
  it('extracts popup_config.visible_fields (custom selection)', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {},
      popup_config: { enabled: true, expression: null, visible_fields: ['pop2025', 'label'] },
    });
    expect(cols.sort()).toEqual(['label', 'pop2025']);
  });

  it('extracts {placeholder} columns from popup_config.expression', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {},
      popup_config: { enabled: true, expression: '{city}, {state}', visible_fields: null },
    });
    expect(cols.sort()).toEqual(['city', 'state']);
  });

  it('unions popup columns with paint columns and dedupes', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: { mode: 'graduated', column: 'pop2025', ramp: 'YlOrRd', breaks: [] },
      paint: {},
      popup_config: { enabled: true, expression: '{name}', visible_fields: ['pop2025'] },
    });
    expect(cols.sort()).toEqual(['name', 'pop2025']);
  });

  it('ignores popup columns when the popup is disabled', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {},
      popup_config: { enabled: false, expression: '{city}', visible_fields: ['pop2025'] },
    });
    expect(cols).toEqual([]);
  });

  it('contributes nothing when visible_fields is null (show-all mode) and no expression', () => {
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {},
      popup_config: { enabled: true, expression: null, visible_fields: null },
    });
    expect(cols).toEqual([]);
  });
});

describe('getDataDrivenColumnsForSource', () => {
  function makeLayer(
    id: string,
    dataset_table_name: string,
    style_config: SyncLayerInput['style_config'] = null,
    paint: SyncLayerInput['paint'] = {},
    label_config: SyncLayerInput['label_config'] = null,
    popup_config: SyncLayerInput['popup_config'] = null,
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
      popup_config,
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

  // #350: popup columns must flow through the source-union path too — this
  // is the BuilderMap path that produces the cols= set for the shared MVT source.
  it('unions popup_config columns from layers sharing a deduped source', () => {
    const layers: SyncLayerInput[] = [
      makeLayer(
        'l1',
        'cities',
        null,
        {},
        null,
        { enabled: true, expression: '{city}, {state}', visible_fields: ['pop2025', 'label'] },
      ),
      makeLayer('l2', 'cities', null, {}, null, null),
    ];
    const cols = getDataDrivenColumnsForSource('source-data-cities', layers);
    expect(cols.sort()).toEqual(['city', 'label', 'pop2025', 'state']);
  });

  it('dedupes a popup field that also drives styling on a sibling layer', () => {
    const layers: SyncLayerInput[] = [
      makeLayer('l1', 'cities', { mode: 'graduated', column: 'pop2025', ramp: 'YlOrRd', breaks: [] }),
      makeLayer('l2', 'cities', null, {}, null, {
        enabled: true,
        expression: null,
        visible_fields: ['pop2025', 'label'],
      }),
    ];
    const cols = getDataDrivenColumnsForSource('source-data-cities', layers);
    expect(cols.sort()).toEqual(['label', 'pop2025']);
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

// #350: the builder→cols path relies on popup_config surviving the
// MapLayerResponse → SyncLayerInput conversion. A silent drop here would
// resurrect the "No attributes" bug, so pin the copy with a test.
describe('toSyncInput popup_config preservation', () => {
  it('carries popup_config through the conversion', () => {
    const popup = { enabled: true, expression: '{city}', visible_fields: ['pop2025'] };
    const layer = {
      id: 'l1',
      dataset_id: 'ds-1',
      dataset_table_name: 'cities',
      dataset_geometry_type: 'MultiPoint',
      opacity: 1,
      visible: true,
      paint: {},
      layout: {},
      filter: null,
      popup_config: popup,
    } as unknown as MapLayerResponse;
    expect(toSyncInput(layer).popup_config).toEqual(popup);
  });

  it('defaults popup_config to null when absent', () => {
    const layer = {
      id: 'l1',
      dataset_id: 'ds-1',
      dataset_table_name: 'cities',
      dataset_geometry_type: 'MultiPoint',
      opacity: 1,
      visible: true,
      paint: {},
      layout: {},
      filter: null,
    } as unknown as MapLayerResponse;
    expect(toSyncInput(layer).popup_config).toBeNull();
  });
});
