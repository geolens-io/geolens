import type { MapLayerResponse } from '@/types/api';

export type LayerKind = 'vector' | 'raster' | 'vrt';

/**
 * Returns true when a layer represents a folder group (layer_type starts with
 * 'group:folder'). Use this single predicate everywhere a folder-group check
 * is needed so all callers stay consistent if new group subtypes are added.
 *
 * If a future phase introduces a new group subtype (e.g. 'group:cluster') and
 * that subtype should have different render or menu behaviour, update this
 * predicate and document the intentional split with a comment at each call site.
 */
export function isFolderGroupLayer(
  layer: { layer_type?: string | null },
): boolean {
  return ((layer.layer_type as string | null | undefined) ?? '').startsWith('group:folder');
}

export interface LayerCapabilities {
  kind: LayerKind;
  supportsStyleEditor: boolean;
  supportsFilterEditor: boolean;
  supportsLabelEditor: boolean;
  supportsOpacity: boolean;
  mapLayerType: 'fill' | 'line' | 'circle' | 'raster';
  iconVariant: 'point' | 'line' | 'polygon' | 'raster' | 'vrt';
}

/**
 * Classify a map layer into its capability set based on layer_type,
 * dataset_record_type, and dataset_geometry_type.
 *
 * Consolidates the branching logic previously duplicated across
 * BuilderMap, StackRow, and MapBuilderPage.
 */
export function getLayerCapabilities(
  layer: Pick<MapLayerResponse, 'layer_type' | 'dataset_record_type' | 'dataset_geometry_type'>,
): LayerCapabilities {
  if (layer.layer_type === 'raster_geolens') {
    const isVrt = layer.dataset_record_type === 'vrt_dataset';
    return {
      kind: isVrt ? 'vrt' : 'raster',
      supportsStyleEditor: false,
      supportsFilterEditor: false,
      supportsLabelEditor: false,
      supportsOpacity: true,
      mapLayerType: 'raster',
      iconVariant: isVrt ? 'vrt' : 'raster',
    };
  }

  // Vector layer with no geometry — restrict capabilities
  if (!layer.dataset_geometry_type) {
    return {
      kind: 'vector',
      supportsStyleEditor: false,
      supportsFilterEditor: false,
      supportsLabelEditor: false,
      supportsOpacity: true,
      mapLayerType: 'fill',
      iconVariant: 'polygon',
    };
  }

  // Vector layer — derive map layer type from geometry
  const gt = (layer.dataset_geometry_type ?? '').toUpperCase();
  let mapLayerType: 'fill' | 'line' | 'circle';
  let iconVariant: 'point' | 'line' | 'polygon';

  if (gt.includes('POINT')) {
    mapLayerType = 'circle';
    iconVariant = 'point';
  } else if (gt.includes('LINE')) {
    mapLayerType = 'line';
    iconVariant = 'line';
  } else {
    mapLayerType = 'fill';
    iconVariant = 'polygon';
  }

  return {
    kind: 'vector',
    supportsStyleEditor: true,
    supportsFilterEditor: true,
    supportsLabelEditor: true,
    supportsOpacity: true,
    mapLayerType,
    iconVariant,
  };
}
