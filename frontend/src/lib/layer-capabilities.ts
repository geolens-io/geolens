import type { MapLayerResponse } from '@/types/api';
import { classifyGeometry } from '@/components/builder/layer-adapters/shared';

type LayerKind = 'vector' | 'raster' | 'vrt';

/**
 * Returns true when a layer represents a folder group (layer_type starts with
 * 'group:folder'). Use this single predicate everywhere a folder-group check
 * is needed.
 */
export function isFolderGroupLayer(
  layer: { layer_type?: string | null },
): boolean {
  return ((layer.layer_type as string | null | undefined) ?? '').startsWith('group:folder');
}

interface LayerCapabilities {
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

  // Vector layer: derive map layer type from the canonical classifier. polygon
  // and `other` (e.g. GEOMETRYCOLLECTION) both map to fill/polygon.
  const family = classifyGeometry(layer.dataset_geometry_type);
  let mapLayerType: 'fill' | 'line' | 'circle';
  let iconVariant: 'point' | 'line' | 'polygon';

  if (family === 'point') {
    mapLayerType = 'circle';
    iconVariant = 'point';
  } else if (family === 'line') {
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

// Record types the rows endpoint refuses (no PostGIS feature table behind
// them): raster family plus the stored-file datasets. Mirrors the backend's
// capabilities().feature_table — a denylist so a record type arriving without
// the field on an older server keeps the action, like isAnalysableLayer.
const NO_DATA_TABLE_RECORD_TYPES = new Set([
  'raster_dataset',
  'vrt_dataset',
  'tiles3d_dataset',
  'pointcloud_dataset',
]);

/**
 * True when a layer can open the read-only attribute table drawer: a dataset
 * backed layer whose record type carries a feature table AND that renders as
 * a vector layer (add_layer lets the caller's layer_type override the
 * dataset-derived one, so the record type alone does not say what the layer
 * draws). Excludes the raster family, terrain (DEM), the stored-file
 * datasets, folder-group rows, basemaps (own rows, no kebab) and unsaved
 * previews (own row type).
 */
export function canOpenAttributeTable(layer: MapLayerResponse): boolean {
  return (
    !isFolderGroupLayer(layer) &&
    !!layer.dataset_id &&
    !layer.is_dem &&
    layer.layer_type !== 'raster_geolens' &&
    !NO_DATA_TABLE_RECORD_TYPES.has((layer.dataset_record_type ?? '').toLowerCase())
  );
}
