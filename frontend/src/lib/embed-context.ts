/**
 * fix(#1515): is this document the embedded map viewer?
 *
 * The embed snippet now ships `sandbox="allow-scripts allow-same-origin"`,
 * because without it the frame has an opaque origin and cannot load its own
 * module graph. Restoring the origin also restores the viewer's persisted
 * session, and an embed running as whoever happens to be signed in is not what
 * an embed is for: the share token is the capability, and it authorizes the map
 * on its own. So the API client reads this and stays out of the session
 * entirely — no bearer token, no proactive refresh, and no logout on a 401.
 *
 * That last one is not a nicety. Before this change the frame was opaque and
 * had no session to spend; now a 401 from inside someone else's page would
 * otherwise run the refresh-then-logout path and sign the viewer out of GeoLens
 * in their other tabs.
 *
 * Read from `window.location` rather than router state because the API client
 * is not inside the React tree. Both the path and the flag are required: `/m/`
 * without `embed=true` is an ordinary share link opened directly, which should
 * behave like any other page, and `embed=true` on some other path is not an
 * embed at all. `buildEmbedSrc()` is the only producer of this URL shape and a
 * test pins its output against this predicate.
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
