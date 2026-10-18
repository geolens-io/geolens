/**
 * Is this document the embedded map viewer?
 *
 * The embed snippet ships `sandbox="allow-scripts allow-same-origin"`, since
 * without it the frame has an opaque origin and cannot load its module graph.
 * That also restores the viewer's persisted session, but the share token is the
 * capability and authorizes the map on its own. So the API client reads this and
 * stays out of the session entirely: no bearer token, no proactive refresh, and
 * no logout on a 401 (which would otherwise sign the viewer out of GeoLens in
 * their other tabs).
 *
 * Read from `window.location` because the API client is outside the React tree.
 * Both the path and the flag are required: `/m/` without `embed=true` is an
 * ordinary share link, and `embed=true` elsewhere is not an embed. A test pins
 * `buildEmbedSrc()`, the only producer of this URL shape, against this predicate.
 */
export function isEmbedViewer(): boolean {
  try {
    return (
      window.location.pathname.startsWith('/m/') &&
      new URLSearchParams(window.location.search).get('embed') === 'true'
    );
  } catch {
    return false;
  }
}
