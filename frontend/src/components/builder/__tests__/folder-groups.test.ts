import { describe, expect, it } from 'vitest';
import {
  hydrateFolderGroupLayers,
  prepareLayersForPersistence,
  pruneEmptyFolderGroups,
  stampPersistedFolderGroupExpanded,
  resolveDropGroupMembership,
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

  // fix(#833 codex round 6): a group created this session has children with
  // only parent_group_id — the post-save baseline must derive the marker the
  // save just wrote, or every later save re-diffs those children against a
  // marker-less baseline and emits a redundant style_config PATCH per child.
  it('stamps derived markers onto children of a session-created group', () => {
    const group = {
      ...makeLayer({ id: 'group-1', display_name: 'Field layers' }),
      layer_type: 'group:folder',
    } as unknown as MapLayerResponse;
    const newChild = {
      ...makeLayer({ id: 'child-1', sort_order: 1 }),
      parent_group_id: 'group-1',
    } as GroupedLayer as MapLayerResponse;
    const groupMeta = { 'group-1': { expanded: false } };

    const stamped = stampPersistedFolderGroupExpanded([group, newChild], groupMeta);

    const stampedChild = stamped.find((layer) => layer.id === 'child-1');
    expect(stampedChild?.style_config?.builder).toMatchObject({
      folderGroupId: 'group-1',
      folderGroupName: 'Field layers',
      folderGroupExpanded: false,
    });
    // The stamped marker must byte-match what prepareLayersForPersistence
    // sent, so the next diff of an untouched group is empty.
    const persisted = prepareLayersForPersistence([group, newChild], groupMeta);
    expect(stampedChild?.style_config).toEqual(persisted[0].style_config);
  });
});

// fix(#767): group identity is persisted only on children, so a childless group
// row cannot survive save+reload — it must be pruned the moment it empties.
describe('pruneEmptyFolderGroups', () => {
  const groupRow = (id: string, name = 'Group') =>
    ({
      ...makeLayer({ id, display_name: name }),
      layer_type: 'group:folder',
    }) as unknown as MapLayerResponse;
  const childOf = (id: string, groupId: string) =>
    ({ ...makeLayer({ id }), parent_group_id: groupId }) as unknown as MapLayerResponse;

  it('prunes a group row with no children', () => {
    const layers = [groupRow('group-1'), makeLayer({ id: 'loose-1' })];

    const pruned = pruneEmptyFolderGroups(layers);

    expect(pruned.map((l) => l.id)).toEqual(['loose-1']);
  });

  it('keeps group rows that still have children and prunes only the empty one', () => {
    const layers = [
      groupRow('group-1'),
      childOf('child-1', 'group-1'),
      groupRow('group-2'),
      makeLayer({ id: 'loose-1' }),
    ];

    const pruned = pruneEmptyFolderGroups(layers);

    expect(pruned.map((l) => l.id)).toEqual(['group-1', 'child-1', 'loose-1']);
  });

  it('returns the input array identity when there is nothing to prune', () => {
    const layers = [groupRow('group-1'), childOf('child-1', 'group-1'), makeLayer({ id: 'loose-1' })];

    expect(pruneEmptyFolderGroups(layers)).toBe(layers);
  });

  it('never touches non-folder rows even when they have no children pointing at them', () => {
    const basemapish = {
      ...makeLayer({ id: 'row-1' }),
      layer_type: 'group:basemap',
    } as unknown as MapLayerResponse;

    const pruned = pruneEmptyFolderGroups([basemapish, makeLayer({ id: 'loose-1' })]);

    expect(pruned.map((l) => l.id)).toEqual(['row-1', 'loose-1']);
  });
});

// fix(#525 B-040): membership rule for intra-stack drag drops — childrenByGroup
// renders by parent_group_id, not array position, so handleDragEnd must derive
// the target membership from the drop target instead of doing a bare arrayMove.
describe('resolveDropGroupMembership', () => {
  const groupRow = {
    ...makeLayer({ id: 'group-1', display_name: 'Group' }),
    layer_type: 'group:folder',
  } as unknown as MapLayerResponse;
  const childOfGroup = {
    ...makeLayer({ id: 'child-1' }),
    parent_group_id: 'group-1',
  } as unknown as MapLayerResponse;
  const childOfOther = {
    ...makeLayer({ id: 'child-2' }),
    parent_group_id: 'group-2',
  } as unknown as MapLayerResponse;
  const loose = makeLayer({ id: 'loose-1' });

  it('a grouped child dropped onto a loose row leaves its group', () => {
    expect(resolveDropGroupMembership(childOfGroup, loose)).toBeNull();
  });

  it('a loose layer dropped onto a group child adopts that group', () => {
    expect(resolveDropGroupMembership(loose, childOfGroup)).toBe('group-1');
  });

  it('a grouped child dropped onto another group\'s child adopts the new group', () => {
    expect(resolveDropGroupMembership(childOfGroup, childOfOther)).toBe('group-2');
  });

  it('dropping onto a group header row keeps the dragged row\'s membership', () => {
    expect(resolveDropGroupMembership(childOfGroup, groupRow)).toBe('group-1');
    expect(resolveDropGroupMembership(loose, groupRow)).toBeNull();
  });

  it('a loose layer dropped onto another loose row stays loose', () => {
    expect(resolveDropGroupMembership(loose, makeLayer({ id: 'loose-2' }))).toBeNull();
  });
});
