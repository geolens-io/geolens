import { apiFetch } from './client';
import { API_BASE } from '@/lib/constants';

export interface BoundedGeoJsonResponse {
  type: 'FeatureCollection';
  features: GeoJSON.Feature[];
  truncated: boolean;
  total_count: number;
}

export type GeoJsonZResponse = BoundedGeoJsonResponse;

function boundedGeoJsonPath(datasetId: string) {
  return `/datasets/${datasetId}/features.geojson`;
}

function directFetchPath(datasetId: string) {
  return `${API_BASE}${boundedGeoJsonPath(datasetId)}`;
}

export function asFeatureCollection(response: BoundedGeoJsonResponse): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: response.features.flatMap(flattenMultiPoint),
  };
}

/**
 * Explode MultiPoint features into one Point feature per coordinate.
 *
 * The backend serves point datasets as MultiPoint (GDAL PROMOTE_TO_MULTI), but
 * MapLibre's `cluster: true` GeoJSON sources are backed by Supercluster, which
 * only indexes `Point` geometry and silently drops MultiPoint — leaving clustered
 * layers blank. Flattening here fixes that for every bounded-GeoJSON consumer
 * (viewer + builder) and is a no-op for already-Point geometry.
 */
function flattenMultiPoint(feature: GeoJSON.Feature): GeoJSON.Feature[] {
  if (feature.geometry?.type !== 'MultiPoint') return [feature];
  return feature.geometry.coordinates.map((coordinates) => ({
    ...feature,
    geometry: { type: 'Point', coordinates },
  }));
}

/**
 * Fetch bounded GeoJSON for map renderers that need a client-side GeoJSON source.
 * Handles JWT auth (via apiFetch), API key, and embed token paths.
 */
export async function fetchBoundedGeoJson(
  datasetId: string,
  options?: { apiKey?: string; embedToken?: string },
): Promise<BoundedGeoJsonResponse> {
  if (options?.embedToken) {
    const res = await fetch(directFetchPath(datasetId), {
      headers: { 'X-Embed-Token': options.embedToken },
    });
    if (!res.ok) throw new Error(`Bounded GeoJSON fetch failed: ${res.status}`);
    return res.json() as Promise<BoundedGeoJsonResponse>;
  }

  if (options?.apiKey) {
    const res = await fetch(`${directFetchPath(datasetId)}?api_key=${encodeURIComponent(options.apiKey)}`);
    if (!res.ok) throw new Error(`Bounded GeoJSON fetch failed: ${res.status}`);
    return res.json() as Promise<BoundedGeoJsonResponse>;
  }

  // Default: JWT auth via apiFetch
  return apiFetch<BoundedGeoJsonResponse>(boundedGeoJsonPath(datasetId));
}

/**
 * Fetch GeoJSON with Z coordinates for a dataset.
 * Handles JWT auth (via apiFetch), API key, and embed token paths.
 */
export async function fetchGeoJsonZ(
  datasetId: string,
  options?: { apiKey?: string; embedToken?: string },
): Promise<GeoJsonZResponse> {
  return fetchBoundedGeoJson(datasetId, options);
}
