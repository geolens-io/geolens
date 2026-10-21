import { apiFetch } from '@/api/client';

export type VectorTileToken = {
  kind: 'vector';
  sig: string;
  exp: number;
  scope: string;
  expires_in: number;
  tile_url_template: string;
};

/** An exact mirror of the API's RasterTileToken. Every field is required,
 * because the response always carries all of them — `hand-typed-mirror-drift`
 * pins that against `openapi.json` in both directions. */
export type RasterTileToken = {
  kind: 'raster';
  /** Arrives with `?sig=&exp=&scope=` already in it. MapLibre issues
   * the tile image requests itself and attaches no header, so the template has
   * to be self-sufficient for a client that cannot use `setTransformRequest`. */
  tile_url: string;
  sig: string;
  exp: number;
  scope: string;
  expires_in: number;
  bounds: number[] | null;
  minzoom: number;
  maxzoom: number;
  tile_size: number;
  format: string;
};

/** The same shape MINUS the signature, built locally rather than fetched.
 *
 * `rasterTokenFromLayer` (layer-description.ts) assembles this from a saved
 * layer row, which has no signature; the in-app map authenticates with a bearer
 * token through `setTransformRequest`. It is a separate type because
 * `RasterTileToken` is a contract mirror: an optional field there would claim
 * the API might omit it. Consumers that accept either take the union. */
export type UnsignedRasterTileTemplate = Omit<
  RasterTileToken,
  'sig' | 'exp' | 'scope' | 'expires_in'
>;

export type TileToken = VectorTileToken | RasterTileToken;

/** Fetch a signed tile token for a dataset using JWT auth (via apiFetch). */
export function getTileToken(datasetId: string): Promise<TileToken> {
  return apiFetch<TileToken>(`/tiles/token/${encodeURIComponent(datasetId)}/`);
}

/** Error entry returned by the batch endpoint when a single dataset fails. */
export type TileTokenError = { error: string };

export type TileTokenBatchResponse = {
  tokens: Record<string, TileToken | TileTokenError>;
};

/**
 * Batch-fetch tile tokens for multiple datasets. Errors for individual datasets
 * are returned as `{ error: string }` values in the `tokens` map; the overall
 * call still resolves. Embed viewers pass their X-Embed-Token so scoped datasets
 * mint the same tile/DEM descriptors an authenticated viewer would get.
 */
export function getTileTokensBatch(datasetIds: string[], embedToken?: string): Promise<TileTokenBatchResponse> {
  const embedHeader: Record<string, string> = embedToken ? { 'X-Embed-Token': embedToken } : {};
  return apiFetch<TileTokenBatchResponse>('/tiles/tokens/', {
    method: 'POST',
    headers: embedHeader,
    body: JSON.stringify({ dataset_ids: datasetIds }),
  });
}
