import { apiFetch } from '@/api/client';
import { API_BASE } from '@/lib/constants';

export type VectorTileToken = {
  kind: 'vector';
  sig: string;
  exp: number;
  scope: string;
  expires_in: number;
};

export type RasterTileToken = {
  kind: 'raster';
  tile_url: string;
  bounds: number[] | null;
  minzoom: number;
  maxzoom: number;
  tile_size: number;
  format: string;
};

export type TileToken = VectorTileToken | RasterTileToken;

/**
 * Fetch a signed tile token for a dataset using JWT auth (via apiFetch).
 */
export function getTileToken(datasetId: string): Promise<TileToken> {
  return apiFetch<TileToken>(`/tiles/token/${datasetId}/`);
}

/** Error entry returned by the batch endpoint when a single dataset fails. */
export type TileTokenError = { error: string };

export type TileTokenBatchResponse = {
  tokens: Record<string, TileToken | TileTokenError>;
};

/**
 * Batch-fetch tile tokens for multiple datasets (PERF-N5). Replaces the
 * N+1 parallel requests the builder previously fired on every map load.
 * Errors for individual datasets are returned as ``{ error: string }``
 * values in the ``tokens`` map; the overall call still resolves.
 */
// fix(#394) SH-04: embed viewers pass their X-Embed-Token so scoped datasets
// mint the same tile/DEM descriptors an authenticated viewer would get.
export function getTileTokensBatch(datasetIds: string[], apiKey?: string, embedToken?: string): Promise<TileTokenBatchResponse> {
  const embedHeader: Record<string, string> = embedToken ? { 'X-Embed-Token': embedToken } : {};
  if (apiKey) {
    return fetch(`${API_BASE}/tiles/tokens/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Api-Key': apiKey, ...embedHeader },
      body: JSON.stringify({ dataset_ids: datasetIds }),
    }).then((res) => {
      if (!res.ok) throw new Error(`Batch token request failed: ${res.status}`);
      return res.json() as Promise<TileTokenBatchResponse>;
    });
  }
  return apiFetch<TileTokenBatchResponse>('/tiles/tokens/', {
    method: 'POST',
    headers: embedHeader,
    body: JSON.stringify({ dataset_ids: datasetIds }),
  });
}
