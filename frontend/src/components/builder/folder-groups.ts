import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

export type GroupedLayer = Omit<MapLayerResponse, 'layer_type'> & {
  layer_type?: string | null;
  parent_group_id?: string | null;
};

export interface FolderGroupMeta {
  expanded: boolean;
}

interface PersistedFolderGroup {
  id: string;
  name: string;
  expanded?: boolean;
}

const FOLDER_GROUP_BUILDER_KEYS = [
  'folderGroupId',
  'folderGroupName',
  'folderGroupExpanded',
] as const;

function getBuilder(styleConfig: StyleConfig | null | undefined): Record<string, unknown> {
  const builder = styleConfig?.builder;
  return builder && typeof builder === 'object' && !Array.isArray(builder)
    ? builder as Record<string, unknown>
    : {};
}

function compactStyleConfig(config: Record<string, unknown>): StyleConfig | null {
  if (Object.keys(config).length === 0) return null;
  return config as StyleConfig;
}

function withPersistedFolderGroup(
  styleConfig: StyleConfig | null | undefined,
  folderGroup: PersistedFolderGroup | null,
): StyleConfig | null {
  const next = { ...(styleConfig ?? {}) } as Record<string, unknown>;
  const builder = { ...getBuilder(styleConfig) };

  for (const key of FOLDER_GROUP_BUILDER_KEYS) {
    delete builder[key];
  }

  if (folderGroup) {
    builder.folderGroupId = folderGroup.id;
    builder.folderGroupName = folderGroup.name;
    if (folderGroup.expanded !== undefined) {
      builder.folderGroupExpanded = folderGroup.expanded;
    }
  }

  if (Object.keys(builder).length > 0) {
    next.builder = builder;
  } else {
    delete next.builder;
  }

  return compactStyleConfig(next);
}

export function getParentGroupId(layer: MapLayerResponse): string | null {
  return (layer as GroupedLayer).parent_group_id ?? null;
}

// The single grouping predicate, shared by StackRow's "Add to group…" menu and
// BulkActionBar's Group action. Drag-and-drop membership
// (resolveDropGroupMembership) never checks record type either: any non-group
// row can live in a group.
export function canJoinFolderGroup(layer: MapLayerResponse): boolean {
  return !isFolderGroupLayer(layer) && !getParentGroupId(layer);
}

// Membership rule for intra-stack drops. childrenByGroup renders by
// parent_group_id, not array position, so a drag that changes position without
// updating membership would snap back on render. A drop onto a group child
// adopts that child's group; onto a loose data row leaves any group; onto a
// group header row keeps the dragged row's current membership (header drops are
// ambiguous, so position-only).
export function resolveDropGroupMembership(
  activeLayer: MapLayerResponse,
  overLayer: MapLayerResponse,
): string | null {
  if (isFolderGroupLayer(overLayer)) return getParentGroupId(activeLayer);
  return getParentGroupId(overLayer);
}

// Ungroup and move-out must clear the persisted
// `style_config.builder.folderGroupId` as well as the frontend-only
// `parent_group_id`. buildDuplicateRenderingInput copies style_config verbatim,
// so duplicating a just-ungrouped layer before Save would carry the stale
// pointer to the backend, and the next resync would re-group it via
// hydrateFolderGroupLayers.
export function clearPersistedFolderGroup(
  styleConfig: StyleConfig | null | undefined,
): StyleConfig | null {
  return withPersistedFolderGroup(styleConfig, null);
}

export function getPersistedFolderGroup(layer: MapLayerResponse): PersistedFolderGroup | null {
  const builder = getBuilder(layer.style_config);
  const id = builder.folderGroupId;
  if (typeof id !== 'string' || id.trim() === '') return null;

  const name = builder.folderGroupName;
  const expanded = builder.folderGroupExpanded;
  return {
    id,
    name: typeof name === 'string' && name.trim() ? name : 'Group',
    ...(typeof expanded === 'boolean' ? { expanded } : {}),
  };
}

// Group identity is persisted only on children (the builder.folderGroup*
// markers written by prepareLayersForPersistence below), so a group row with no
// children has no carrier and can't survive save+reload; left alone it would
// keep rendering, accepting drops and dirtying the map, then vanish (with any
// rename) on the next hydrate. Prune the row the moment it empties so the UI and
// persisted state agree. Callers renumber sort_order; returns the input array
// (same identity) when there is nothing to prune.
export function pruneEmptyFolderGroups(layers: MapLayerResponse[]): MapLayerResponse[] {
  const parentIds = new Set<string>();
  for (const layer of layers) {
    const parentId = getParentGroupId(layer);
    if (parentId) parentIds.add(parentId);
  }
  const pruned = layers.filter((layer) => !isFolderGroupLayer(layer) || parentIds.has(layer.id));
  return pruned.length === layers.length ? layers : pruned;
}

export function hydrateFolderGroupLayers(
  layers: MapLayerResponse[],
): { layers: MapLayerResponse[]; groupMeta: Record<string, FolderGroupMeta> } {
  const hydrated: MapLayerResponse[] = [];
  const seenGroups = new Set<string>();
  const groupMeta: Record<string, FolderGroupMeta> = {};

  for (const layer of layers) {
    const persistedGroup = getPersistedFolderGroup(layer);
    if (!persistedGroup) {
      hydrated.push(layer);
      continue;
    }

    if (!seenGroups.has(persistedGroup.id)) {
      const groupRow: GroupedLayer = {
        ...(layer as GroupedLayer),
        id: persistedGroup.id,
        display_name: persistedGroup.name,
        layer_type: 'group:folder',
        parent_group_id: null,
        sort_order: hydrated.length,
      };
      hydrated.push(groupRow as MapLayerResponse);
      seenGroups.add(persistedGroup.id);
      groupMeta[persistedGroup.id] = {
        expanded: persistedGroup.expanded ?? true,
      };
    }

    hydrated.push({
      ...(layer as GroupedLayer),
      parent_group_id: persistedGroup.id,
      sort_order: hydrated.length,
    } as MapLayerResponse);
  }

  return {
    layers: hydrated.map((layer, index) => ({ ...layer, sort_order: index })),
    groupMeta,
  };
}

// Snapshot helper for the save-diff baseline. The baseline keeps the
// hydrated/local layer shape, but its persisted folderGroupExpanded markers must
// reflect the collapse state just saved (the live groupMeta), not the state the
// map loaded with: copying localLayers verbatim after a collapse→save would
// leave the baseline "expanded", so the next expand→save diffs empty and reload
// restores the stale collapse. Layers without persisted markers, and groups
// without a groupMeta entry, pass through as plain copies.
export function stampPersistedFolderGroupExpanded(
  layers: MapLayerResponse[],
  groupMeta: Record<string, FolderGroupMeta> = {},
): MapLayerResponse[] {
  // Children of a group created this session carry only parent_group_id, but
  // the save this baseline snapshots just wrote a marker
  // (prepareLayersForPersistence derives it from the group row + groupMeta).
  // Derive the same marker here, or every later save re-diffs those children
  // against a marker-less baseline and emits a redundant style_config PATCH each.
  const groups = new Map<string, PersistedFolderGroup>();
  for (const layer of layers) {
    if (!isFolderGroupLayer(layer)) continue;
    groups.set(layer.id, {
      id: layer.id,
      name: layer.display_name?.trim() || 'Group',
      expanded: groupMeta[layer.id]?.expanded,
    });
  }
  return layers.map((layer) => {
    const persisted = getPersistedFolderGroup(layer);
    if (persisted) {
      const expanded = groupMeta[persisted.id]?.expanded;
      if (expanded === undefined || persisted.expanded === expanded) {
        return { ...layer };
      }
      return {
        ...layer,
        style_config: withPersistedFolderGroup(layer.style_config, { ...persisted, expanded }),
      };
    }
    if (isFolderGroupLayer(layer)) return { ...layer };
    const parentGroupId = (layer as GroupedLayer).parent_group_id ?? null;
    const folderGroup = parentGroupId ? groups.get(parentGroupId) ?? null : null;
    if (!folderGroup) return { ...layer };
    return {
      ...layer,
      style_config: withPersistedFolderGroup(layer.style_config, folderGroup),
    };
  });
}

export function prepareLayersForPersistence(
  layers: MapLayerResponse[],
  groupMeta: Record<string, FolderGroupMeta> = {},
): MapLayerResponse[] {
  const groups = new Map<string, PersistedFolderGroup>();

  for (const layer of layers) {
    if (!isFolderGroupLayer(layer)) continue;
    groups.set(layer.id, {
      id: layer.id,
      name: layer.display_name?.trim() || 'Group',
      expanded: groupMeta[layer.id]?.expanded,
    });
  }

  return layers
    .filter((layer) => !isFolderGroupLayer(layer))
    .map((layer, index) => {
      const groupedLayer = layer as GroupedLayer;
      const parentGroupId = groupedLayer.parent_group_id ?? null;
      const folderGroup = parentGroupId ? groups.get(parentGroupId) ?? null : null;
      const { parent_group_id: _parentGroupId, ...rest } = groupedLayer;

      return {
        ...rest,
        sort_order: index,
        style_config: withPersistedFolderGroup(layer.style_config, folderGroup),
      } as MapLayerResponse;
    });
}
