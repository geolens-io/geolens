const STORY_EMBED_PATH = /^\/stories\/[^/]+\/embed\/?$/;

/**
 * The path as React Router matches it: each segment percent-decoded, or the
 * raw path when a segment is malformed, compared without regard to case.
 */
function routedPath(pathname: string): string {
  let path = pathname;
  try {
    path = pathname
      .split('/')
      .map((segment) => decodeURIComponent(segment).replace(/\//g, '%2F'))
      .join('/');
  } catch {
    // The router falls back to the raw path too.
  }
  return path.toLowerCase();
}

/**
 * Is this document an embed: the embedded map viewer or a story's embed page?
 *
 * The embed snippets ship `sandbox="allow-scripts allow-same-origin"`, since
 * without it the frame has an opaque origin and cannot load its module graph.
 * That also restores the viewer's persisted session, but an embed authorizes
 * itself: a map's share token is the capability, and a story embed reads only
 * what any anonymous reader may. So the API client reads this and stays out of
 * the session entirely: no bearer token, no proactive refresh, and no logout on
 * a 401 (which would otherwise sign the viewer out of GeoLens in their other
 * tabs).
 *
 * Read from `window.location` because the API client is outside the React tree.
 * For a map both the path and the flag are required: `/m/` without
 * `embed=true` is an ordinary share link, and `embed=true` elsewhere is not an
 * embed. Tests pin `buildEmbedSrc()` and `storyEmbedSrc()`, the only producers
 * of these URL shapes, against this predicate.
 */
export function isEmbedViewer(): boolean {
  try {
    const path = routedPath(window.location.pathname);
    if (STORY_EMBED_PATH.test(path)) return true;
    return path.startsWith('/m/') && new URLSearchParams(window.location.search).get('embed') === 'true';
  } catch {
    return false;
  }
}
