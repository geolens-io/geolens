import type { Geometry } from 'geojson';
import { apiFetch, apiFetchHeader } from './client';

/** Must match TILE_CACHE_VERSION_HEADER in backend/app/modules/catalog/features/schemas.py. */
const TILE_CACHE_VERSION_HEADER = 'X-GeoLens-Tile-Cache-Version';

export interface GeoJSONFeature {
  type: 'Feature';
  id: number;
  geometry: Geometry;
  properties: Record<string, unknown>;
  /**
   * The data table the feature was read from or written to. Pass it to
   * updateFeature or deleteFeature to have the write refused with a 409
   * `dataset_replaced` once a reupload or overwrite has replaced that table,
   * which can give the feature's id to another row. Absent from a server that
   * predates this field.
   */
  table_id?: string | null;
}

/**
 * A written feature, plus the dataset's tile_cache_version after commit.
 * Send it back as the tile routes' `_v` param when reloading tiles, so a
 * request that reaches a different API worker is forced to re-read the
 * dataset instead of serving that worker's own cached snapshot. Absent
 * from a server that predates this field.
 */
export interface GeoJSONFeatureWrite extends GeoJSONFeature {
  tile_cache_version?: number | null;
}

/**
 * Acknowledgement for a deleted feature; see GeoJSONFeatureWrite's field of
 * the same name. The delete endpoint stays 204 (compatibility with existing
 * callers), so this rides a response header rather than a JSON body.
 */
export interface FeatureDeleteResult {
  tile_cache_version?: number | null;
}

/**
 * Create a feature. Send the same `idempotencyKey` on every attempt to create
 * one feature, with an `attempt` number that grows by one each time the body
 * is sent again: a retry after a lost response then updates the feature that
 * was created, with the newest body, instead of inserting another.
 */
export async function createFeature(
  datasetId: string,
  geometry: Geometry,
  properties?: Record<string, unknown>,
  idempotencyKey?: string,
  attempt?: number,
): Promise<GeoJSONFeatureWrite> {
  const headers: Record<string, string> = {};
  if (idempotencyKey) {
    headers['Idempotency-Key'] = idempotencyKey;
    if (attempt !== undefined) headers['Idempotency-Attempt'] = String(attempt);
  }
  return apiFetch<GeoJSONFeatureWrite>(`/datasets/${datasetId}/features/`, {
    method: 'POST',
    headers: Object.keys(headers).length > 0 ? headers : undefined,
    body: JSON.stringify({ geometry, properties: properties ?? {} }),
  });
}

export async function getFeature(
  datasetId: string,
  gid: number,
): Promise<GeoJSONFeature> {
  return apiFetch<GeoJSONFeature>(`/datasets/${datasetId}/features/${gid}`);
}

function featurePath(datasetId: string, gid: number, tableId?: string | null): string {
  const path = `/datasets/${datasetId}/features/${gid}`;
  return tableId ? `${path}?table_id=${encodeURIComponent(tableId)}` : path;
}

export async function updateFeature(
  datasetId: string,
  gid: number,
  geometry?: Geometry,
  properties?: Record<string, unknown>,
  tableId?: string | null,
): Promise<GeoJSONFeatureWrite> {
  const body: Record<string, unknown> = {};
  if (geometry !== undefined) body.geometry = geometry;
  if (properties !== undefined) body.properties = properties;
  return apiFetch<GeoJSONFeatureWrite>(featurePath(datasetId, gid, tableId), {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export async function deleteFeature(
  datasetId: string,
  gid: number,
  tableId?: string | null,
): Promise<FeatureDeleteResult> {
  const version = await apiFetchHeader(
    featurePath(datasetId, gid, tableId),
    TILE_CACHE_VERSION_HEADER,
    { method: 'DELETE' },
  );
  // A server that predates this header (or an unparseable value) leaves
  // tile_cache_version null; the caller falls back to a timestamp.
  const parsed = version != null ? Number(version) : NaN;
  return { tile_cache_version: Number.isFinite(parsed) ? parsed : null };
}
