import { apiFetch } from './client';
import { API_BASE } from '@/lib/constants';
import { translateApiErrorDetail } from '@/lib/error-map';

export interface BoundedGeoJsonResponse {
  type: 'FeatureCollection';
  features: GeoJSON.Feature[];
  truncated: boolean;
  total_count: number;
}

const GEOJSON_TIMEOUT_MS = 30_000;

export interface GeoJsonFetchOptions {
  apiKey?: string;
  embedToken?: string;
  signal?: AbortSignal;
}

export type GeoJsonZResponse = BoundedGeoJsonResponse;

function boundedGeoJsonPath(datasetId: string) {
  return `/datasets/${datasetId}/features.geojson`;
}

function directFetchPath(datasetId: string) {
  return `${API_BASE}${boundedGeoJsonPath(datasetId)}`;
}

async function throwLocalizedResponseError(response: Response): Promise<never> {
  let detail: unknown;
  try {
    const body = await response.json();
    detail = body.detail;
  } catch { /* not JSON */ }
  throw new Error(translateApiErrorDetail(detail, response.status));
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
  options?: GeoJsonFetchOptions,
): Promise<BoundedGeoJsonResponse> {
  const signal = options?.signal
    ? AbortSignal.any([options.signal, AbortSignal.timeout(GEOJSON_TIMEOUT_MS)])
    : AbortSignal.timeout(GEOJSON_TIMEOUT_MS);

  if (options?.embedToken) {
    const res = await fetch(directFetchPath(datasetId), {
      headers: { 'X-Embed-Token': options.embedToken },
      signal,
    });
    if (!res.ok) await throwLocalizedResponseError(res);
    return res.json() as Promise<BoundedGeoJsonResponse>;
  }

  if (options?.apiKey) {
    // fix(#833): send the key in the X-Api-Key header (same form the embed
    // path uses above) — a query-string credential lands in server/proxy logs.
    const res = await fetch(directFetchPath(datasetId), {
      headers: { 'X-Api-Key': options.apiKey },
      signal,
    });
    if (!res.ok) await throwLocalizedResponseError(res);
    return res.json() as Promise<BoundedGeoJsonResponse>;
  }

  // Default: JWT auth via apiFetch
  return apiFetch<BoundedGeoJsonResponse>(boundedGeoJsonPath(datasetId), { signal });
}

/**
 * Fetch GeoJSON with Z coordinates for a dataset.
 * Handles JWT auth (via apiFetch), API key, and embed token paths.
 */
export async function fetchGeoJsonZ(
  datasetId: string,
  options?: GeoJsonFetchOptions,
): Promise<GeoJsonZResponse> {
  return fetchBoundedGeoJson(datasetId, options);
}
