import { useMemo } from 'react';
import type { MapLayerResponse } from '@/types/api';

export type BuilderEditorScene = 'default' | 'dem' | 'basemap-group' | 'basemap-sublayer' | 'settings';

export interface BuilderEditorBasemapGroup {
  id: string;
  presetName: string;
  sublayers: Array<{ id: string; name: string }>;
}

export function deriveBuilderEditorScene(
  expandedLayerId: string | null,
  editingLayer: Pick<MapLayerResponse, 'is_dem'> | null,
): BuilderEditorScene {
  if (!expandedLayerId) return 'default';
  if (expandedLayerId === 'settings') return 'settings';
  if (expandedLayerId === 'basemap-group') return 'basemap-group';
  if (expandedLayerId.startsWith('basemap:')) return 'basemap-sublayer';
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
  const editingLayer = useMemo(
    () => expandedLayerId ? localLayers.find((layer) => layer.id === expandedLayerId) ?? null : null,
    [expandedLayerId, localLayers],
  );

  const editingSavedLayer = useMemo(
    () => expandedLayerId
      ? savedLayerBaseline.find((layer) => layer.id === expandedLayerId)
      : undefined,
    [expandedLayerId, savedLayerBaseline],
  );

  const editorScene = useMemo(
    () => deriveBuilderEditorScene(expandedLayerId, editingLayer),
    [expandedLayerId, editingLayer],
  );

  const syntheticEditorLayer = useMemo(
    () => createSyntheticEditorLayer({ editorScene, expandedLayerId, basemapGroup }),
    [basemapGroup, editorScene, expandedLayerId],
  );

  const editorLayer = editingLayer ?? syntheticEditorLayer;
  const isEditorOpen = editorLayer !== null;

  return {
    editingLayer,
    editingSavedLayer,
    editorLayer,
    editorScene,
    isEditorOpen,
  };
}
