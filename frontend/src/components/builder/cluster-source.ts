import type { MapLayerType, RecordType, StyleConfig } from '@/types/api';

export const CLUSTER_GEOJSON_FEATURE_LIMIT = 5000;

export type ClusterSourceStatus =
  | 'eligible'
  | 'not-cluster'
  | 'not-vector'
  | 'not-point'
  | 'missing-count'
  | 'too-many-features'
  | 'unsupported-record-type';

export interface ClusterSourceEligibility {
  eligible: boolean;
  status: ClusterSourceStatus;
  featureCount: number | null;
  limit: number;
}

export interface ClusterSourceLayer {
  dataset_geometry_type?: string | null;
  geometry_type?: string | null;
  dataset_record_type?: RecordType | string | null;
  layer_type?: MapLayerType | string | null;
  is_dem?: boolean | null;
  dataset_feature_count?: number | null;
  feature_count?: number | null;
  style_config?: Pick<StyleConfig, 'render_mode'> | null;
}

function geometryType(layer: ClusterSourceLayer) {
  return layer.dataset_geometry_type ?? layer.geometry_type ?? null;
}

function featureCount(layer: ClusterSourceLayer) {
  const count = layer.dataset_feature_count ?? layer.feature_count ?? null;
  return typeof count === 'number' && Number.isFinite(count) ? count : null;
}

function isPointGeometry(layer: ClusterSourceLayer) {
  return (geometryType(layer) ?? '').toUpperCase().includes('POINT');
}

function isVectorLayer(layer: ClusterSourceLayer) {
  if (layer.is_dem === true) return false;
  if (layer.layer_type === 'raster_geolens') return false;
  if (layer.dataset_record_type && layer.dataset_record_type !== 'vector_dataset') return false;
  return layer.layer_type == null || layer.layer_type === 'vector_geolens' || layer.layer_type === 'geojson';
}

export function isClusterRenderMode(layer: ClusterSourceLayer) {
  return layer.style_config?.render_mode === 'cluster';
}

export function getClusterSourceEligibility(
  layer: ClusterSourceLayer,
  limit = CLUSTER_GEOJSON_FEATURE_LIMIT,
): ClusterSourceEligibility {
  const count = featureCount(layer);

  if (!isVectorLayer(layer)) {
    return { eligible: false, status: 'not-vector', featureCount: count, limit };
  }
  if (!isPointGeometry(layer)) {
    return { eligible: false, status: 'not-point', featureCount: count, limit };
  }
  if (count == null) {
    return { eligible: false, status: 'missing-count', featureCount: null, limit };
  }
  if (count > limit) {
    return { eligible: false, status: 'too-many-features', featureCount: count, limit };
  }
  return { eligible: true, status: 'eligible', featureCount: count, limit };
}

export function shouldFetchClusterGeoJson(layer: ClusterSourceLayer) {
  return isClusterRenderMode(layer) && getClusterSourceEligibility(layer).eligible;
}

export function clusterFallbackMessage(status: ClusterSourceStatus) {
  switch (status) {
    case 'missing-count':
      return 'Feature count is unavailable for bounded clustering.';
    case 'too-many-features':
      return 'Dataset is too large for bounded client-side clustering.';
    case 'not-point':
      return 'Only point datasets can be clustered.';
    case 'not-vector':
      return 'Only vector datasets can be clustered.';
    case 'unsupported-record-type':
      return 'Dataset type does not support clustering.';
    case 'not-cluster':
    case 'eligible':
    default:
      return null;
  }
}
