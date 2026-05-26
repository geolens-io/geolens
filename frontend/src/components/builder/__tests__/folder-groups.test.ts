import { describe, expect, it } from 'vitest';
import {
  hydrateFolderGroupLayers,
  prepareLayersForPersistence,
  type GroupedLayer,
} from '../folder-groups';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'dataset-1',
    dataset_name: overrides.dataset_name ?? 'Dataset',
    dataset_geometry_type: overrides.dataset_geometry_type ?? 'POINT',
    dataset_table_name: overrides.dataset_table_name ?? 'dataset_table',
    dataset_extent_bbox: overrides.dataset_extent_bbox ?? null,
    dataset_column_info: overrides.dataset_column_info ?? null,
    dataset_feature_count: overrides.dataset_feature_count ?? null,
    dataset_sample_values: overrides.dataset_sample_values ?? null,
    display_name: overrides.display_name ?? null,
    sort_order: overrides.sort_order ?? 0,
    visible: overrides.visible ?? true,
    opacity: overrides.opacity ?? 1,
    paint: overrides.paint ?? {},
    layout: overrides.layout ?? {},
    filter: overrides.filter ?? null,
    label_config: overrides.label_config ?? null,
    popup_config: overrides.popup_config ?? null,
    style_config: overrides.style_config ?? null,
    layer_type: overrides.layer_type ?? 'vector_geolens',
    dataset_record_type: overrides.dataset_record_type ?? 'vector_dataset',
    show_in_legend: overrides.show_in_legend ?? true,
    is_3d: overrides.is_3d ?? false,
    is_dem: overrides.is_dem ?? false,
    dem_vertical_units: overrides.dem_vertical_units ?? null,
  };
}

describe('folder group persistence helpers', () => {
  it('hydrates persisted child metadata into a virtual folder row and parent_group_id children', () => {
    const child = makeLayer({
      id: 'child-1',
      display_name: 'Peaks',
      style_config: {
        builder: {
          folderGroupId: 'group-1',
          folderGroupName: 'Field layers',
          folderGroupExpanded: false,
        },
      } as StyleConfig,
    });

    const hydrated = hydrateFolderGroupLayers([child]);

    expect(hydrated.groupMeta).toEqual({ 'group-1': { expanded: false } });
    expect(hydrated.layers).toHaveLength(2);
    expect(hydrated.layers[0]).toMatchObject({
      id: 'group-1',
      display_name: 'Field layers',
      layer_type: 'group:folder',
    });
    expect((hydrated.layers[1] as GroupedLayer).parent_group_id).toBe('group-1');
  });

  it('persists virtual folder membership on real child layers and omits group rows', () => {
    const group = {
      ...makeLayer({ id: 'group-1', display_name: 'Field layers' }),
      layer_type: 'group:folder',
    } as unknown as MapLayerResponse;
    const groupedChild = {
      ...makeLayer({
        id: 'child-1',
        sort_order: 1,
        style_config: { builder: { outlineColor: '#111111' } } as StyleConfig,
      }),
      parent_group_id: 'group-1',
    } as GroupedLayer as MapLayerResponse;
    const loose = makeLayer({
      id: 'loose-1',
      sort_order: 2,
      style_config: {
        builder: {
          folderGroupId: 'stale-group',
          folderGroupName: 'Stale',
          outlineWidth: 2,
        },
      } as StyleConfig,
    });

    const persisted = prepareLayersForPersistence(
      [group, groupedChild, loose],
      { 'group-1': { expanded: true } },
    );

    expect(persisted.map((layer) => layer.id)).toEqual(['child-1', 'loose-1']);
    expect(persisted[0].sort_order).toBe(0);
    expect(persisted[0].style_config?.builder).toMatchObject({
      outlineColor: '#111111',
      folderGroupId: 'group-1',
      folderGroupName: 'Field layers',
      folderGroupExpanded: true,
    });
    expect(persisted[1].style_config?.builder).toEqual({ outlineWidth: 2 });
  });
});
