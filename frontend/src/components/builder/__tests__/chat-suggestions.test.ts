import { getSmartSuggestions, type ViewportContext } from '../chat-suggestions';
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

  it('deduplicates repeated suggestions for duplicated layers', () => {
    const layers = [
      makeLayer({ id: 'l1', dataset_name: 'Duplicate Name', dataset_geometry_type: 'Point' }),
      makeLayer({ id: 'l2', dataset_name: 'Duplicate Name', dataset_geometry_type: 'Point' }),
    ];
    const result = getSmartSuggestions(layers, mockT as never);

    expect(result).toHaveLength(new Set(result).size);
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

describe('chat-suggestions — viewport-aware (Phase 1135 AI-05)', () => {
  const t = (key: string, options?: Record<string, unknown>) => {
    if (key === 'chat.suggestions.summarizeLayer') return `Summarize ${String(options?.name)} attributes`;
    if (key === 'chat.suggestions.nearbyFeatures') return 'Show nearby features in this area';
    if (key === 'chat.suggestions.colorByAttribute') return `Color ${String(options?.name)} by attribute`;
    if (key === 'chat.suggestions.areaLabels') return `Label ${String(options?.name)} areas`;
    if (key === 'chat.suggestions.adjustOpacity') return `Adjust ${String(options?.name)} opacity`;
    if (key === 'chat.suggestions.addDataset') return 'Add a dataset';
    return key;
  };

  function makeVPLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
    return {
      id: 'l-1',
      dataset_id: 'ds-1',
      dataset_name: 'Test',
      dataset_geometry_type: 'Polygon',
      dataset_table_name: 'test_table',
      dataset_extent_bbox: null,
      dataset_column_info: null,
      dataset_feature_count: null,
      dataset_sample_values: null,
      display_name: null,
      sort_order: 0,
      visible: true,
      opacity: 1,
      paint: {},
      layout: {},
      filter: null,
      ...overrides,
    } as MapLayerResponse;
  }

  it('backward compat: no viewport argument yields existing geometry-only behavior', () => {
    const layers = [makeVPLayer({ dataset_geometry_type: 'Point' })];
    const out = getSmartSuggestions(layers, t as never);
    expect(out.some((s) => s.includes('Color'))).toBe(true);
    expect(out.length).toBeLessThanOrEqual(4);
    expect(out.some((s) => s.startsWith('Summarize'))).toBe(false);
    expect(out).not.toContain('Show nearby features in this area');
  });

  it('selectedLayerName leads the list', () => {
    const layers = [makeVPLayer({ dataset_geometry_type: 'Point' })];
    const viewport: ViewportContext = { zoom: 5, bounds: [-180, -90, 180, 90], selectedLayerName: 'Counties' };
    const out = getSmartSuggestions(layers, t as never, viewport);
    expect(out[0]).toBe('Summarize @Counties attributes');
  });

  it('selectedLayerName with spaces uses bracket-mention syntax', () => {
    const layers = [makeVPLayer()];
    const viewport: ViewportContext = { zoom: 5, bounds: [-180, -90, 180, 90], selectedLayerName: 'NYC Subway' };
    const out = getSmartSuggestions(layers, t as never, viewport);
    expect(out[0]).toBe('Summarize @[NYC Subway] attributes');
  });

  it('zoom >= 12 + vector layer adds nearby features suggestion', () => {
    const layers = [makeVPLayer({ dataset_geometry_type: 'Point' })];
    const viewport: ViewportContext = { zoom: 14, bounds: [-74, 40, -73, 41] };
    const out = getSmartSuggestions(layers, t as never, viewport);
    expect(out).toContain('Show nearby features in this area');
  });

  it('zoom >= 12 but raster-only layers does NOT add nearby features suggestion', () => {
    const layers = [makeVPLayer({ dataset_geometry_type: null, layer_type: 'raster_geolens' as MapLayerResponse['layer_type'] })];
    const viewport: ViewportContext = { zoom: 14, bounds: [-74, 40, -73, 41] };
    const out = getSmartSuggestions(layers, t as never, viewport);
    expect(out).not.toContain('Show nearby features in this area');
  });

  it('zoom < 12 does NOT add nearby features suggestion', () => {
    const layers = [makeVPLayer({ dataset_geometry_type: 'Point' })];
    const viewport: ViewportContext = { zoom: 8, bounds: [-180, -90, 180, 90] };
    const out = getSmartSuggestions(layers, t as never, viewport);
    expect(out).not.toContain('Show nearby features in this area');
  });

  it('honors the 4-chip cap even when viewport adds two new priority items', () => {
    const layers = [
      makeVPLayer({ id: 'l-1', dataset_name: 'A', dataset_geometry_type: 'Point' }),
      makeVPLayer({ id: 'l-2', dataset_name: 'B', dataset_geometry_type: 'Polygon' }),
      makeVPLayer({ id: 'l-3', dataset_name: 'C', dataset_geometry_type: 'LineString' }),
    ];
    const viewport: ViewportContext = { zoom: 14, bounds: [-74, 40, -73, 41], selectedLayerName: 'Counties' };
    const out = getSmartSuggestions(layers, t as never, viewport);
    expect(out.length).toBe(4);
  });
});
