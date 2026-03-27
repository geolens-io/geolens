import { apiFetch } from '@/api/client';
import { getEnvConfig } from '@/lib/env';

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

/**
 * Fetch a signed tile token using an API key (for ViewerMap / public embeds).
 * Uses direct fetch with X-Api-Key header instead of apiFetch JWT flow.
 */
export async function getTileTokenWithApiKey(
  datasetId: string,
  apiKey: string,
): Promise<TileToken> {
  const base = getEnvConfig().API_BASE_URL || '/api';
  const res = await fetch(`${base}/tiles/token/${datasetId}/`, {
    headers: { 'X-Api-Key': apiKey },
  });
  if (!res.ok) {
    throw new Error(`Tile token request failed: ${res.status}`);
  }
  return res.json() as Promise<TileToken>;
}
