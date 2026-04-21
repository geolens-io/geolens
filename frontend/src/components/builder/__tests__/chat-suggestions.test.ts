import { getSmartSuggestions } from '../chat-suggestions';
import type { MapLayerResponse } from '@/types/api';

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
    dataset_column_info: null,
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

  it('generates point-specific suggestions (colorByAttribute)', () => {
    const layer = makeLayer({ dataset_geometry_type: 'Point', style_config: null });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('chat.suggestions.colorByAttribute'))).toBe(true);
  });

  it('generates polygon-specific suggestions (colorByAttribute, areaLabels)', () => {
    const layer = makeLayer({ dataset_geometry_type: 'Polygon', style_config: null });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('chat.suggestions.colorByAttribute'))).toBe(true);
    expect(result.some((s) => s.includes('chat.suggestions.areaLabels'))).toBe(true);
  });

  it('generates line-specific suggestions (colorByAttribute)', () => {
    const layer = makeLayer({ dataset_geometry_type: 'LineString' });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('chat.suggestions.colorByAttribute'))).toBe(true);
  });

  it('generates raster suggestions (adjustOpacity)', () => {
    const layer = makeLayer({
      dataset_geometry_type: '',
      layer_type: 'raster' as MapLayerResponse['layer_type'],
    });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('chat.suggestions.adjustOpacity'))).toBe(true);
  });

  it('adds addDataset suggestion when room', () => {
    const result = getSmartSuggestions([], mockT as never);
    expect(result).toHaveLength(1);
    expect(result[0]).toContain('chat.suggestions.addDataset');
  });

  it('uses bracket syntax for layer names with spaces', () => {
    const layer = makeLayer({ display_name: 'My Layer', dataset_geometry_type: 'Point', style_config: null });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('@[My Layer]'))).toBe(true);
  });

  it('skips heatmap for already-styled point layers', () => {
    const layer = makeLayer({
      dataset_geometry_type: 'Point',
      style_config: { mode: 'categorical', column: 'type' } as MapLayerResponse['style_config'],
    });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.includes('chat.suggestions.heatmap'))).toBe(false);
  });
});
