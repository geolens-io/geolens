import { getSmartSuggestions } from '../chat-suggestions';
import type { MapLayerResponse } from '@/types/api';

// Mock t function that returns the key with interpolated values
function mockT(key: string, params?: Record<string, string>): string {
  let result = key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      result += ` ${k}=${v}`;
    }
  }
  return result;
}

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'TestLayer',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'test_table',
    dataset_extent_bbox: null,
    dataset_column_info: [
      { name: 'value', type: 'numeric' },
      { name: 'name', type: 'text' },
    ],
    dataset_feature_count: 100,
    dataset_sample_values: null,
    display_name: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    ...overrides,
  };
}

describe('getSmartSuggestions', () => {
  it('returns max 4 suggestions', () => {
    const layers = [
      makeLayer({ id: 'l1', dataset_name: 'A' }),
      makeLayer({ id: 'l2', dataset_name: 'B' }),
      makeLayer({ id: 'l3', dataset_name: 'C' }),
    ];
    const result = getSmartSuggestions(layers, mockT as never);
    expect(result.length).toBeLessThanOrEqual(4);
  });

  it('generates point-specific suggestions (heatmap, cluster)', () => {
    const layer = makeLayer({
      dataset_geometry_type: 'Point',
      style_config: null,
    });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('chat.suggestions.heatmap'))).toBe(true);
  });

  it('generates polygon-specific suggestions (colorBy, areaLabels)', () => {
    const layer = makeLayer({
      dataset_geometry_type: 'Polygon',
      style_config: null,
    });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('chat.suggestions.colorBy'))).toBe(true);
    expect(result.some((s) => s.includes('chat.suggestions.areaLabels'))).toBe(true);
  });

  it('generates line-specific suggestions (varyWidth)', () => {
    const layer = makeLayer({
      dataset_geometry_type: 'LineString',
      dataset_column_info: [{ name: 'speed', type: 'numeric' }],
    });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('chat.suggestions.varyWidth'))).toBe(true);
  });

  it('generates raster suggestions (adjustOpacity)', () => {
    const layer = makeLayer({
      dataset_geometry_type: '',
      layer_type: 'raster' as MapLayerResponse['layer_type'],
      dataset_column_info: [],
    });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('chat.suggestions.adjustOpacity'))).toBe(true);
  });

  it('adds addDataset suggestion when room', () => {
    const result = getSmartSuggestions([], mockT as never);
    expect(result).toHaveLength(1);
    expect(result[0]).toContain('chat.suggestions.addDataset');
  });

  it('generates column-type-aware suggestions for numeric columns', () => {
    const layer = makeLayer({
      dataset_geometry_type: 'LineString',
      dataset_column_info: [{ name: 'population', type: 'integer' }],
    });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('chat.suggestions.distribution'))).toBe(true);
  });

  it('generates column-type-aware suggestions for text columns', () => {
    const layer = makeLayer({
      dataset_geometry_type: 'LineString',
      dataset_column_info: [{ name: 'category', type: 'varchar' }],
    });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('chat.suggestions.categories'))).toBe(true);
  });

  it('generates temporal suggestions for date columns', () => {
    const layer = makeLayer({
      dataset_geometry_type: 'LineString',
      dataset_column_info: [{ name: 'created_at', type: 'timestamp' }],
    });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('chat.suggestions.filterByDate'))).toBe(true);
  });

  it('uses bracket syntax for layer names with spaces', () => {
    const layer = makeLayer({
      display_name: 'My Layer',
      dataset_geometry_type: 'Point',
      style_config: null,
    });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('@[My Layer]'))).toBe(true);
  });

  it('skips point heatmap/cluster for already-styled layers', () => {
    const layer = makeLayer({
      dataset_geometry_type: 'Point',
      style_config: { mode: 'categorical', column: 'type' } as MapLayerResponse['style_config'],
      dataset_column_info: [{ name: 'count', type: 'numeric' }],
    });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('chat.suggestions.heatmap'))).toBe(false);
    expect(result.some((s) => s.includes('chat.suggestions.cluster'))).toBe(false);
    // Should still have sizeBy for numeric column
    expect(result.some((s) => s.includes('chat.suggestions.sizeBy'))).toBe(true);
  });
});
