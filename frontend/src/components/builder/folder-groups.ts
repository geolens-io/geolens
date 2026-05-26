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
