import { useMemo } from 'react';
import type { MapLayerResponse } from '@/types/api';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';

export type BuilderEditorScene = 'default' | 'dem' | 'basemap-group' | 'basemap-sublayer' | 'settings' | 'group';

export interface BuilderEditorBasemapGroup {
  id: string;
  presetName: string;
  sublayers: Array<{ id: string; name: string }>;
}

export function deriveBuilderEditorScene(
  expandedLayerId: string | null,
  editingLayer: Pick<MapLayerResponse, 'is_dem' | 'layer_type'> | null,
): BuilderEditorScene {
  if (!expandedLayerId) return 'default';
  if (expandedLayerId === 'settings') return 'settings';
  if (expandedLayerId === 'basemap-group') return 'basemap-group';
  if (expandedLayerId.startsWith('basemap:')) return 'basemap-sublayer';
  // fix(#392): folder groups are structural containers, not
  // stylable layers; never fall through to a real editing scene for them. (audit B-004a/LM-01)
  if (editingLayer && isFolderGroupLayer(editingLayer)) return 'group';
  if (editingLayer?.is_dem === true) return 'dem';
  return 'default';
}

function syntheticLayerBase({
  id,
  name,
  tableName,
}: {
  id: string;
  name: string;
  tableName: string;
}): MapLayerResponse {
  return {
    id,
    dataset_id: tableName,
    dataset_name: name,
    dataset_geometry_type: null,
    dataset_table_name: tableName,
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: name,
    sort_order: -1,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: null,
    layer_type: null,
    dataset_record_type: 'vector_dataset',
    show_in_legend: false,
    is_dem: false,
    dem_vertical_units: null,
  };
}

export function createSyntheticEditorLayer({
  editorScene,
  expandedLayerId,
  basemapGroup,
}: {
  editorScene: BuilderEditorScene;
  expandedLayerId: string | null;
  basemapGroup: BuilderEditorBasemapGroup | null;
}): MapLayerResponse | null {
  if (editorScene === 'settings') {
    return syntheticLayerBase({
      id: 'settings',
      name: 'Settings',
      tableName: 'settings',
    });
  }

  if (editorScene === 'basemap-sublayer') {
    const sublayerName = basemapGroup?.sublayers.find((s) => s.id === expandedLayerId)?.name ?? 'Sublayer';
    return syntheticLayerBase({
      id: expandedLayerId ?? 'basemap-group',
      name: sublayerName,
      tableName: 'basemap',
    });
  }

  if (editorScene === 'basemap-group') {
    return syntheticLayerBase({
      id: expandedLayerId ?? basemapGroup?.id ?? 'basemap-group',
      name: `Basemap · ${basemapGroup?.presetName ?? 'Untitled'}`,
      tableName: 'basemap',
    });
  }

  return null;
}

export function useBuilderEditorScene({
  expandedLayerId,
  localLayers,
  savedLayerBaseline,
  basemapGroup,
}: {
  expandedLayerId: string | null;
  localLayers: MapLayerResponse[];
  savedLayerBaseline: MapLayerResponse[];
  basemapGroup: BuilderEditorBasemapGroup | null;
}) {
  const matchedLayer = useMemo(
    () => expandedLayerId ? localLayers.find((layer) => layer.id === expandedLayerId) ?? null : null,
    [expandedLayerId, localLayers],
  );

  // fix(#392): a group:folder row IS a member of localLayers,
  // so without this guard editingLayer would resolve to the group row and bind
  // the editor to its inherited (phantom) geometry. Treat it as non-editable. (audit B-004a/LM-01)
  const editingLayer = matchedLayer && isFolderGroupLayer(matchedLayer) ? null : matchedLayer;

  const editingSavedLayer = useMemo(
    () => expandedLayerId && !(matchedLayer && isFolderGroupLayer(matchedLayer))
      ? savedLayerBaseline.find((layer) => layer.id === expandedLayerId)
      : undefined,
    [expandedLayerId, matchedLayer, savedLayerBaseline],
  );

  const editorScene = useMemo(
    () => deriveBuilderEditorScene(expandedLayerId, matchedLayer),
    [expandedLayerId, matchedLayer],
  );

  const syntheticEditorLayer = useMemo(
    () => createSyntheticEditorLayer({ editorScene, expandedLayerId, basemapGroup }),
    [basemapGroup, editorScene, expandedLayerId],
  );

  const editorLayer = editorScene === 'group' ? null : (editingLayer ?? syntheticEditorLayer);
  const isEditorOpen = editorLayer !== null;

  return {
    editingLayer,
    editingSavedLayer,
    editorLayer,
    editorScene,
    isEditorOpen,
  };
}
