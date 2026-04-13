import { apiFetch } from './client';

export interface GeoJsonZResponse {
  type: 'FeatureCollection';
  features: GeoJSON.Feature[];
  truncated: boolean;
  total_count: number;
}

/**
 * Fetch GeoJSON with Z coordinates for a dataset.
 * Handles JWT auth (via apiFetch), API key, and embed token paths.
 */
export async function fetchGeoJsonZ(
  datasetId: string,
  options?: { apiKey?: string; embedToken?: string },
): Promise<GeoJsonZResponse> {
  const relativePath = `/datasets/${datasetId}/features.geojson`;
  const fullPath = `/api${relativePath}`;

  if (options?.embedToken) {
    const res = await fetch(fullPath, {
      headers: { 'X-Embed-Token': options.embedToken },
    });
    if (!res.ok) throw new Error(`GeoJSON-Z fetch failed: ${res.status}`);
    return res.json() as Promise<GeoJsonZResponse>;
  }

  if (options?.apiKey) {
    const res = await fetch(`${fullPath}?api_key=${encodeURIComponent(options.apiKey)}`);
    if (!res.ok) throw new Error(`GeoJSON-Z fetch failed: ${res.status}`);
    return res.json() as Promise<GeoJsonZResponse>;
  }

  // Default: JWT auth via apiFetch (prepends /api automatically)
  return apiFetch<GeoJsonZResponse>(relativePath);
}
