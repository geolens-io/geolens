import { authenticatedRawFetch } from '@/api/client';

/** The dataset file routes the viewer may read: 3D Tiles files and the COPC file. */
export type DatasetFiles = 'tiles3d' | 'copc';

/**
 * The URL a viewer request may reach, or null when it must be refused.
 *
 * Only this dataset's own `/api/datasets/{id}/{area}/` files on the app
 * origin qualify. The WHATWG URL parser resolves dot segments, percent-encoded
 * ones included, so the prefix test runs on the resolved path; an encoded
 * slash or backslash is refused outright because a server may decode it into
 * a separator after this check.
 */
export function resolveDatasetUrl(
  raw: string,
  datasetId: string,
  area: DatasetFiles,
  origin: string,
): URL | null {
  let url: URL;
  try {
    url = new URL(raw, origin);
  } catch {
    return null;
  }
  if (url.origin !== origin || url.username || url.password) return null;
  if (/%(?:2f|5c)/i.test(url.pathname)) return null;
  const prefix = `/api/datasets/${encodeURIComponent(datasetId)}/${area}/`;
  return url.pathname.startsWith(prefix) ? url : null;
}

export function requestUrl(input: RequestInfo | URL): string {
  return input instanceof Request ? input.url : String(input);
}

/**
 * A fetch for one dataset's tileset or COPC files. The session credential is
 * attached (and renewed on 401) by `authenticatedRawFetch`, but only for URLs
 * that pass `resolveDatasetUrl`; a tileset.json naming an absolute,
 * cross-origin or escaping URI is refused before any request is made.
 */
export function makeDatasetFetch(
  datasetId: string,
  area: DatasetFiles,
): (input: RequestInfo | URL, init?: RequestInit) => Promise<Response> {
  return async (input, init) => {
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const url = resolveDatasetUrl(requestUrl(input), datasetId, area, window.location.origin);
    if (!url || (method !== 'GET' && method !== 'HEAD')) {
      throw new Error('The 3D viewer refused a URL outside this dataset');
    }
    return authenticatedRawFetch(url.pathname + url.search, {
      ...init,
      method,
      credentials: 'same-origin',
      // A redirect would carry the session credential to wherever it points.
      redirect: 'error',
    });
  };
}
