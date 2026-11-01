import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerType, RecordType, StyleConfig } from '@/types/api';
import {
  filterConditions,
  isCql2LiteralCompatible,
  maplibreFilterToCql2,
  type Cql2Expression,
} from '@/lib/maplibre-filter-utils';

const CLUSTER_GEOJSON_FEATURE_LIMIT = 5000;
// The server caps each vector tile at this many features (_TILE_FEATURE_LIMIT in backend/app/processing/tiles/service.py).
export const TILE_FEATURE_LIMIT = 50_000;
// The server's limits on a CQL2 filter, as compact JSON counted in characters.
// The cluster tile route caps its `filter` query parameter (max_length in
// processing/tiles/router.py).
const MAX_CLUSTER_FILTER_CHARS = 4096;
// nginx reads a request line into one `large_client_header_buffers` buffer, 8k
// by its default of `4 8k`, which frontend/nginx.conf leaves unset. The margin
// holds the method, the HTTP version and the tile numbers for {z}/{x}/{y}.
const MAX_TILE_URL_CHARS = 8 * 1024 - 128;
// Every route that compiles a filter: MAX_FEATURE_FILTER_LENGTH and
// MAX_FEATURE_FILTER_BINDS (one bind per value) in standards/ogc/filtering.py.
const MAX_FEATURE_FILTER_CHARS = 10_000;
const MAX_FILTER_VALUES = 1000;
// _MAX_FILTER_DEPTH in datasets/domain/aggregate.py, counting each object, list and value.
const MAX_AGGREGATE_FILTER_DEPTH = 64;

function countValues(node: unknown): number {
  if (Array.isArray(node)) return node.reduce((sum: number, child) => sum + countValues(child), 0);
  if (node && typeof node === 'object') {
    return Object.entries(node).reduce((sum, [key, child]) => sum + (key === 'property' || key === 'op' ? 0 : countValues(child)), 0);
  }
  return 1;
}

function depth(node: unknown): number {
  const children = Array.isArray(node) ? node : node && typeof node === 'object' ? Object.values(node) : null;
  return children ? 1 + Math.max(0, ...children.map(depth)) : 1;
}

const jsonChars = (cql2: Cql2Expression) => [...JSON.stringify(cql2)].length;

function fitsClusterFilterLimits(cql2: Cql2Expression): boolean {
  return jsonChars(cql2) <= MAX_CLUSTER_FILTER_CHARS && countValues(cql2) <= MAX_FILTER_VALUES;
}

/** Whether a tile URL fits the request line nginx accepts. */
export function fitsTileRequestLine(url: string): boolean {
  return url.length <= MAX_TILE_URL_CHARS;
}

/**
 * A layer filter as the cluster tile route's CQL2-JSON `filter`, or why it is
 * left off: there is none, it has no CQL2 form, a literal mismatches a known
 * column type, it reads a property outside an explicit tile allowlist
 * (`unsupported`), or it exceeds the route's limits (`too-large`). Unlisted
 * column types are left to the server. Left off, the bubbles count every
 * point while loose points keep the filter.
 */
export function serverClusterFilter(
  filter: FilterSpecification | null | undefined,
  columns: readonly { name: string; type?: string | null }[] | null | undefined,
  tileColumns: readonly string[] | null | undefined,
): { json: string } | { omitted: 'none' | 'unsupported' | 'too-large' } {
  const cql2 = maplibreFilterToCql2(filter, columns);
  if (!cql2) return { omitted: 'none' };
  if (cql2 === 'unsupported') return { omitted: 'unsupported' };
  const types = new Map(
    (columns ?? []).filter((col) => col.type).map((col) => [col.name, String(col.type).toLowerCase()]),
  );
  const unreadable = (filterConditions(filter) ?? []).some((condition) => {
    if (tileColumns != null && !tileColumns.includes(condition.field)) return true;
    const values = condition.listValues ?? (condition.rawValue == null ? [] : [condition.rawValue]);
    return values.some((value) => !isCql2LiteralCompatible(value, types.get(condition.field)));
  });
  if (unreadable) return { omitted: 'unsupported' };
  return fitsClusterFilterLimits(cql2) ? { json: JSON.stringify(cql2) } : { omitted: 'too-large' };
}

/** Whether the aggregate endpoint takes `cql2` as a filter; past its limits it refuses the request. */
export function fitsAggregateFilterLimits(cql2: Cql2Expression): boolean {
  return (
    jsonChars(cql2) <= MAX_FEATURE_FILTER_CHARS &&
    countValues(cql2) <= MAX_FILTER_VALUES &&
    depth(cql2) <= MAX_AGGREGATE_FILTER_DEPTH
  );
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

/** A point layer too big for one tile: zoomed out, its tiles hold only a sample. */
export function exceedsTileFeatureLimit(layer: ClusterSourceLayer) {
  const count = featureCount(layer);
  return count != null && count > TILE_FEATURE_LIMIT && isVectorLayer(layer) && isPointGeometry(layer);
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
