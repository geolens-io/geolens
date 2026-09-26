import type { Geometry } from 'geojson';
import { apiFetch } from './client';

export interface GeoJSONFeature {
  type: 'Feature';
  id: number;
  geometry: Geometry;
  properties: Record<string, unknown>;
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

/** Acknowledgement for a deleted feature; see GeoJSONFeatureWrite's field of the same name. */
export interface FeatureDeleteResult {
  tile_cache_version?: number | null;
}

export async function createFeature(
  datasetId: string,
  geometry: Geometry,
  properties?: Record<string, unknown>,
): Promise<GeoJSONFeatureWrite> {
  return apiFetch<GeoJSONFeatureWrite>(`/datasets/${datasetId}/features/`, {
    method: 'POST',
    body: JSON.stringify({ geometry, properties: properties ?? {} }),
  });
}

export async function getFeature(
  datasetId: string,
  gid: number,
): Promise<GeoJSONFeature> {
  return apiFetch<GeoJSONFeature>(`/datasets/${datasetId}/features/${gid}`);
}

export async function updateFeature(
  datasetId: string,
  gid: number,
  geometry?: Geometry,
  properties?: Record<string, unknown>,
): Promise<GeoJSONFeatureWrite> {
  const body: Record<string, unknown> = {};
  if (geometry !== undefined) body.geometry = geometry;
  if (properties !== undefined) body.properties = properties;
  return apiFetch<GeoJSONFeatureWrite>(`/datasets/${datasetId}/features/${gid}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export async function deleteFeature(
  datasetId: string,
  gid: number,
): Promise<FeatureDeleteResult> {
  return apiFetch<FeatureDeleteResult>(`/datasets/${datasetId}/features/${gid}`, {
    method: 'DELETE',
  });
}
