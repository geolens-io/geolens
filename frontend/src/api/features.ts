import { apiFetch } from './client';

export interface GeoJSONFeature {
  type: 'Feature';
  id: number;
  geometry: Record<string, unknown>;
  properties: Record<string, unknown>;
}

export async function createFeature(
  datasetId: string,
  geometry: Record<string, unknown>,
  properties?: Record<string, unknown>,
): Promise<GeoJSONFeature> {
  return apiFetch<GeoJSONFeature>(`/datasets/${datasetId}/features/`, {
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
  geometry?: Record<string, unknown>,
  properties?: Record<string, unknown>,
): Promise<GeoJSONFeature> {
  const body: Record<string, unknown> = {};
  if (geometry !== undefined) body.geometry = geometry;
  if (properties !== undefined) body.properties = properties;
  return apiFetch<GeoJSONFeature>(`/datasets/${datasetId}/features/${gid}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export async function deleteFeature(
  datasetId: string,
  gid: number,
): Promise<void> {
  await apiFetch<void>(`/datasets/${datasetId}/features/${gid}`, {
    method: 'DELETE',
  });
}
