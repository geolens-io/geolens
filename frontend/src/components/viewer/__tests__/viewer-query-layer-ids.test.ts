import { describe, expect, it } from 'vitest';
import type { SharedLayerResponse } from '@/types/api';
import { createViewerLayerEntries } from '../layer-identity';
import { viewerQueryLayerIds } from '../viewer-query-layer-ids';

function layer(id: string, renderMode?: 'heatmap'): SharedLayerResponse {
  return {
    id,
    dataset_id: `dataset-${id}`,
    dataset_name: id,
    display_name: id,
    table_name: id,
    geometry_type: 'POINT',
    column_info: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: renderMode ? { render_mode: renderMode } : null,
    tile_url: '',
  };
}

describe('viewerQueryLayerIds', () => {
  it('keeps heatmaps in the accessible query while excluding them from clicks', () => {
    const entries = createViewerLayerEntries([layer('points'), layer('density', 'heatmap')]);
    const visible = new Set(['points', 'density']);

    expect(viewerQueryLayerIds(entries, visible, { includeHeatmaps: false }))
      .toEqual(['viewer-layer-points']);
    expect(viewerQueryLayerIds(entries, visible, { includeHeatmaps: true }))
      .toEqual(['viewer-layer-points', 'viewer-layer-density']);
  });
});
