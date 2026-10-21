import { authenticatedRawFetch } from '@/api/client';

/**
 * The URL a tileset request may reach, or null when it must be refused.
 *
 * Only this dataset's own `/api/datasets/{id}/tiles3d/` files on the app
 * origin qualify. The WHATWG URL parser resolves dot segments, percent-encoded
 * ones included, so the prefix test runs on the resolved path; an encoded
 * slash or backslash is refused outright because a server may decode it into
 * a separator after this check.
 */
export function resolveTilesetUrl(raw: string, datasetId: string, origin: string): URL | null {
  let url: URL;
  try {
    url = new URL(raw, origin);
  } catch {
    return null;
  }
  if (url.origin !== origin || url.username || url.password) return null;
  if (/%(?:2f|5c)/i.test(url.pathname)) return null;
  const prefix = `/api/datasets/${encodeURIComponent(datasetId)}/tiles3d/`;
  return url.pathname.startsWith(prefix) ? url : null;
}

/**
 * A fetch for one dataset's tileset files. The session credential is attached
 * (and renewed on 401) by `authenticatedRawFetch`, but only for URLs that pass
 * `resolveTilesetUrl`; a tileset.json naming an absolute, cross-origin or
 * escaping URI is refused before any request is made.
 */
export function makeTilesetFetch(
  datasetId: string,
): (input: RequestInfo | URL, init?: RequestInit) => Promise<Response> {
  return async (input, init) => {
    const raw = input instanceof Request ? input.url : String(input);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const url = resolveTilesetUrl(raw, datasetId, window.location.origin);
    if (!url || (method !== 'GET' && method !== 'HEAD')) {
      throw new Error('The 3D viewer refused a URL outside this dataset');
    }
    return authenticatedRawFetch(url.pathname + url.search, {
      ...init,
      method,
      credentials: 'same-origin',
    });
  };
}
