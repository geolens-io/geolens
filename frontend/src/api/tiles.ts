import { apiFetch, safeFetch } from '@/api/client';
import { API_BASE } from '@/lib/constants';
import { translateApiErrorDetail } from '@/lib/error-map';

export type VectorTileToken = {
  kind: 'vector';
  sig: string;
  exp: number;
  scope: string;
  expires_in: number;
};

/** An exact mirror of the API's RasterTileToken. Every field is required,
 * because the response always carries all of them — `hand-typed-mirror-drift`
 * pins that against `openapi.json` in both directions. */
export type RasterTileToken = {
  kind: 'raster';
  /** fix(#688): arrives with `?sig=&exp=&scope=` already in it. MapLibre issues
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
 * fix(#688): `rasterTokenFromLayer` (map-sync.ts) assembles this from a saved
 * layer row, which has no signature and cannot have one — the in-app map
 * authenticates with a bearer token through `setTransformRequest` instead. It
 * is a separate type rather than four optional fields on `RasterTileToken`
 * because that type is a contract mirror: marking a field optional there would
 * claim the API might omit it, which is the silent-undefined seed the drift
 * test exists to catch. Consumers that accept either take the union. */
export type UnsignedRasterTileTemplate = Omit<
  RasterTileToken,
  'sig' | 'exp' | 'scope' | 'expires_in'
>;

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
    // fix(#438): DATA-11 — the API-key branch used a bare `fetch()`, so a
    // network failure surfaced as a raw `TypeError` while the JWT branch below
    // (via apiFetch → safeFetch) yielded a normalized status-0 ApiError.
    // safeFetch gives both branches the same error shape.
    return safeFetch(`${API_BASE}/tiles/tokens/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Api-Key': apiKey, ...embedHeader },
      body: JSON.stringify({ dataset_ids: datasetIds }),
    }).then(async (res) => {
      if (!res.ok) {
        let detail: unknown;
        try {
          const body = await res.json();
          detail = body.detail;
        } catch { /* not JSON */ }
        throw new Error(translateApiErrorDetail(detail, res.status));
      }
      return res.json() as Promise<TileTokenBatchResponse>;
    });
  }
  return apiFetch<TileTokenBatchResponse>('/tiles/tokens/', {
    method: 'POST',
    headers: embedHeader,
    body: JSON.stringify({ dataset_ids: datasetIds }),
  });
}
