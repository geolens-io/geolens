import { enrichMessage } from '../chat-enrichment';
import type { MapLayerResponse } from '@/types/api';

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'TestLayer',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'test_table',
    dataset_extent_bbox: null,
    dataset_column_info: [
      { name: 'name', type: 'text' },
      { name: 'value', type: 'numeric' },
    ],
    dataset_feature_count: 1234,
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

describe('enrichMessage', () => {
  const layers = [makeLayer()];

  it('returns message unchanged when no mentions or commands', () => {
    expect(enrichMessage('hello world', layers)).toBe('hello world');
  });

  it('appends context block for plain @mention', () => {
    const result = enrichMessage('style @TestLayer red', layers);
    expect(result).toContain('[Context:');
    expect(result).toContain('layer_id:layer-1');
    expect(result).toContain('Polygon');
    expect(result).toContain('1,234 features');
    expect(result).toContain('name(text)');
  });

  it('appends context block for bracket @mention', () => {
    const layer = makeLayer({ display_name: 'My Layer', id: 'layer-2' });
    const result = enrichMessage('style @[My Layer] red', [layer]);
    expect(result).toContain('layer_id:layer-2');
    expect(result).toContain('My Layer');
  });

  it('deduplicates when same layer mentioned multiple times', () => {
    const result = enrichMessage('@TestLayer and @TestLayer again', layers);
    const matches = result.match(/layer_id:layer-1/g);
    expect(matches).toHaveLength(1);
  });

  it('leaves unresolvable mentions as-is', () => {
    const result = enrichMessage('style @UnknownLayer red', layers);
    expect(result).toBe('style @UnknownLayer red');
    expect(result).not.toContain('[Context:');
  });

  it('strips /style and prepends intent prefix', () => {
    const result = enrichMessage('/style make it blue', layers);
    expect(result.startsWith('[Intent: style] ')).toBe(true);
    expect(result).toContain('make it blue');
    expect(result).not.toContain('/style');
  });

  it('strips /filter and prepends intent prefix', () => {
    const result = enrichMessage('/filter value > 100', layers);
    expect(result.startsWith('[Intent: filter] ')).toBe(true);
  });

  it('strips /query and prepends intent prefix', () => {
    const result = enrichMessage('/query how many features', layers);
    expect(result.startsWith('[Intent: query] ')).toBe(true);
  });

  it('does not strip unknown slash commands', () => {
    const result = enrichMessage('/unknown do something', layers);
    expect(result).toBe('/unknown do something');
    expect(result).not.toContain('[Intent:');
  });

  it('combines slash command and @mention', () => {
    const result = enrichMessage('/style color @TestLayer red', layers);
    expect(result.startsWith('[Intent: style] ')).toBe(true);
    expect(result).toContain('[Context:');
    expect(result).toContain('layer_id:layer-1');
  });

  it('handles message with only a mention and no other text', () => {
    const result = enrichMessage('@TestLayer', layers);
    expect(result).toContain('@TestLayer');
    expect(result).toContain('[Context:');
  });

  it('limits context columns to 5', () => {
    const manyColumns = Array.from({ length: 10 }, (_, i) => ({
      name: `col${i}`,
      type: 'text',
    }));
    const layer = makeLayer({ dataset_column_info: manyColumns });
    const result = enrichMessage('@TestLayer', [layer]);
    // Should only have 5 columns in context
    const colMatches = result.match(/col\d+\(text\)/g);
    expect(colMatches).toHaveLength(5);
  });
});
