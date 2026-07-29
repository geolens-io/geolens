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
    expect(result.some((s) => s.payload.includes('chat.suggestions.colorByAttribute'))).toBe(true);
  });

  it('generates polygon-specific suggestions (colorByAttribute, areaLabels)', () => {
    const layer = makeLayer({ dataset_geometry_type: 'Polygon', style_config: null });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.payload.includes('chat.suggestions.colorByAttribute'))).toBe(true);
    expect(result.some((s) => s.payload.includes('chat.suggestions.areaLabels'))).toBe(true);
  });

  it('generates line-specific suggestions (colorByAttribute)', () => {
    const layer = makeLayer({ dataset_geometry_type: 'LineString' });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.payload.includes('chat.suggestions.colorByAttribute'))).toBe(true);
  });

  it('generates raster suggestions (adjustOpacity)', () => {
    const layer = makeLayer({
      dataset_geometry_type: '',
      layer_type: 'raster' as MapLayerResponse['layer_type'],
    });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.payload.includes('chat.suggestions.adjustOpacity'))).toBe(true);
  });

  it('adds addDataset suggestion when room', () => {
    const result = getSmartSuggestions([], mockT as never);
    expect(result).toHaveLength(1);
    expect(result[0].payload).toContain('chat.suggestions.addDataset');
    expect(result[0].label).toBe(result[0].payload);
  });

  it('uses bracket syntax in the payload for layer names with spaces', () => {
    const layer = makeLayer({ display_name: 'My Layer', dataset_geometry_type: 'Point', style_config: null });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.payload.includes('@[My Layer]'))).toBe(true);
  });

  it('deduplicates repeated suggestions for duplicated layers', () => {
    const layers = [
      makeLayer({ id: 'l1', dataset_name: 'Duplicate Name', dataset_geometry_type: 'Point' }),
      makeLayer({ id: 'l2', dataset_name: 'Duplicate Name', dataset_geometry_type: 'Point' }),
    ];
    const result = getSmartSuggestions(layers, mockT as never);

    const payloads = result.map((s) => s.payload);
    expect(payloads).toHaveLength(new Set(payloads).size);
  });

  it('skips heatmap for already-styled point layers', () => {
    const layer = makeLayer({
      dataset_geometry_type: 'Point',
      style_config: { mode: 'categorical', column: 'type' } as MapLayerResponse['style_config'],
    });
    const result = getSmartSuggestions([layer], mockT as never);
    expect(result.some((s) => s.payload.includes('chat.suggestions.heatmap'))).toBe(false);
  });
});

describe('label/payload split (fix #832, PR #853 review)', () => {
  it('label uses the plain layer name while payload keeps mention markup', () => {
    const layer = makeLayer({ display_name: 'My Layer', dataset_geometry_type: 'Point', style_config: null });
    const result = getSmartSuggestions([layer], mockT as never);
    const suggestion = result.find((s) => s.payload.includes('colorByAttribute'));
    expect(suggestion).toBeDefined();
    expect(suggestion!.label).toContain('My Layer');
    expect(suggestion!.label).not.toContain('@[');
    expect(suggestion!.payload).toContain('@[My Layer]');
  });

  it('preserves a layer name containing "]" in the label', () => {
    // Regex-stripping the payload would corrupt this: "@[A] B]" -> "A B]".
    const layer = makeLayer({ display_name: 'A] B', dataset_geometry_type: 'Point', style_config: null });
    const result = getSmartSuggestions([layer], mockT as never);
    const suggestion = result.find((s) => s.payload.includes('colorByAttribute'));
    expect(suggestion).toBeDefined();
    expect(suggestion!.label).toContain('A] B');
    expect(suggestion!.label).not.toContain('@[');
    expect(suggestion!.payload).toContain('@[A] B]');
  });

  it('keeps the bare-@ mention form for names without spaces in the payload only', () => {
    const layer = makeLayer({ display_name: 'Counties', dataset_geometry_type: 'Point', style_config: null });
    const result = getSmartSuggestions([layer], mockT as never);
    const suggestion = result.find((s) => s.payload.includes('colorByAttribute'));
    expect(suggestion).toBeDefined();
    expect(suggestion!.label).toContain('name=Counties');
    expect(suggestion!.payload).toContain('@Counties');
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
    const payloads = out.map((s) => s.payload);
    expect(payloads.some((s) => s.includes('Color'))).toBe(true);
    expect(out.length).toBeLessThanOrEqual(4);
    expect(payloads.some((s) => s.startsWith('Summarize'))).toBe(false);
    expect(payloads).not.toContain('Show nearby features in this area');
  });

  it('selectedLayerName leads the list', () => {
    const layers = [makeVPLayer({ dataset_geometry_type: 'Point' })];
    const viewport: ViewportContext = { zoom: 5, bounds: [-180, -90, 180, 90], selectedLayerName: 'Counties' };
    const out = getSmartSuggestions(layers, t as never, viewport);
    expect(out[0].payload).toBe('Summarize @Counties attributes');
    expect(out[0].label).toBe('Summarize Counties attributes');
  });

  it('selectedLayerName with spaces uses bracket-mention syntax in the payload only', () => {
    const layers = [makeVPLayer()];
    const viewport: ViewportContext = { zoom: 5, bounds: [-180, -90, 180, 90], selectedLayerName: 'NYC Subway' };
    const out = getSmartSuggestions(layers, t as never, viewport);
    expect(out[0].payload).toBe('Summarize @[NYC Subway] attributes');
    expect(out[0].label).toBe('Summarize NYC Subway attributes');
  });

  it('zoom >= 12 + vector layer adds nearby features suggestion', () => {
    const layers = [makeVPLayer({ dataset_geometry_type: 'Point' })];
    const viewport: ViewportContext = { zoom: 14, bounds: [-74, 40, -73, 41] };
    const out = getSmartSuggestions(layers, t as never, viewport);
    expect(out.map((s) => s.payload)).toContain('Show nearby features in this area');
  });

  it('zoom >= 12 but raster-only layers does NOT add nearby features suggestion', () => {
    const layers = [makeVPLayer({ dataset_geometry_type: null, layer_type: 'raster_geolens' as MapLayerResponse['layer_type'] })];
    const viewport: ViewportContext = { zoom: 14, bounds: [-74, 40, -73, 41] };
    const out = getSmartSuggestions(layers, t as never, viewport);
    expect(out.map((s) => s.payload)).not.toContain('Show nearby features in this area');
  });

  it('zoom < 12 does NOT add nearby features suggestion', () => {
    const layers = [makeVPLayer({ dataset_geometry_type: 'Point' })];
    const viewport: ViewportContext = { zoom: 8, bounds: [-180, -90, 180, 90] };
    const out = getSmartSuggestions(layers, t as never, viewport);
    expect(out.map((s) => s.payload)).not.toContain('Show nearby features in this area');
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
