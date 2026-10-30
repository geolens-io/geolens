import type { MapLayerType, RecordType, StyleConfig } from '@/types/api';
import type { Cql2Expression } from '@/lib/maplibre-filter-utils';

const CLUSTER_GEOJSON_FEATURE_LIMIT = 5000;
// The cluster tile route's limits on a filter: its length and its bind parameters.
const MAX_CLUSTER_FILTER_CHARS = 4096;
const MAX_CLUSTER_FILTER_VALUES = 1000;

function countValues(node: unknown): number {
  if (Array.isArray(node)) return node.reduce((sum: number, child) => sum + countValues(child), 0);
  if (node && typeof node === 'object') {
    return Object.entries(node).reduce((sum, [key, child]) => sum + (key === 'property' || key === 'op' ? 0 : countValues(child)), 0);
  }
  return 1;
}

/** Whether the cluster tile route takes `cql2` as a filter; past its limits the request leaves the filter off. */
export function fitsClusterFilterLimits(cql2: Cql2Expression): boolean {
  return JSON.stringify(cql2).length <= MAX_CLUSTER_FILTER_CHARS && countValues(cql2) <= MAX_CLUSTER_FILTER_VALUES;
}

export type ClusterSourceStatus =
  | 'eligible'
  | 'not-cluster'
  | 'not-vector'
  | 'not-point'
  | 'missing-count'
  | 'too-many-features'
  | 'unsupported-record-type';

interface ClusterSourceEligibility {
  eligible: boolean;
  status: ClusterSourceStatus;
  featureCount: number | null;
  limit: number;
}

export type ClusterSourceStrategyKind = 'bounded-geojson' | 'server-tile' | 'fallback';

interface ClusterSourceStrategy {
  kind: ClusterSourceStrategyKind;
  status: ClusterSourceStatus;
  featureCount: number | null;
  limit: number;
}

interface ClusterSourceLayer {
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

export function getClusterSourceStrategy(
  layer: ClusterSourceLayer,
  limit = CLUSTER_GEOJSON_FEATURE_LIMIT,
): ClusterSourceStrategy {
  const count = featureCount(layer);

  if (!isClusterRenderMode(layer)) {
    return { kind: 'fallback', status: 'not-cluster', featureCount: count, limit };
  }
  if (!isVectorLayer(layer)) {
    return { kind: 'fallback', status: 'not-vector', featureCount: count, limit };
  }
  if (!isPointGeometry(layer)) {
    return { kind: 'fallback', status: 'not-point', featureCount: count, limit };
  }
  if (count == null) {
    return { kind: 'fallback', status: 'missing-count', featureCount: null, limit };
  }
  if (count > limit) {
    return { kind: 'server-tile', status: 'too-many-features', featureCount: count, limit };
  }
  return { kind: 'bounded-geojson', status: 'eligible', featureCount: count, limit };
}

export function canUseClusterSource(layer: ClusterSourceLayer) {
  const count = featureCount(layer);
  return isVectorLayer(layer) && isPointGeometry(layer) && count != null;
}

export function shouldFetchClusterGeoJson(layer: ClusterSourceLayer) {
  return getClusterSourceStrategy(layer).kind === 'bounded-geojson';
}

// Structural identity key for the cluster-source fetch effect. Folds in only
// the fields that change which GeoJSON gets fetched (cluster membership,
// dataset, resolved strategy). Paint/opacity/filter edits replace the layers
// array identity on every tick; keying the effect on this string keeps them
// from re-issuing fetches for bounded-geojson cluster layers.
export function getClusterSourceKey(
  layers: Array<ClusterSourceLayer & { id?: string; dataset_id?: string | null }>,
): string {
  return layers
    .filter((layer) => isClusterRenderMode(layer))
    .map((layer) => `${layer.id ?? ''}|${layer.dataset_id ?? ''}|${getClusterSourceStrategy(layer).kind}`)
    .join(',');
}
