/**
 * feat(#1241 codex r1): whether a chat overlay holds the WHOLE answer.
 *
 * `truncated` on a show_query_result action is the SQL sandbox's row-cap flag,
 * and it is not a statement about the FeatureCollection. When the model selects
 * geometry itself, `backend/app/processing/ai/chat_actions.py` executes at the
 * sandbox's default 1000-row limit and then slices the overlay to its own
 * 50-row render budget, so a 300-row answer arrives as 50 features with
 * `truncated: false`. Read that flag alone and a clipped preview looks
 * complete: the count label says "50 features" (the #674/#1076
 * misrepresentation, reached through a producer those fixes did not cover) and
 * a snapshot save would file 50 of 300 rows in the catalog as the answer.
 *
 * The client can tell without any server change. `row_count` is the matched-row
 * total the model narrates, so an overlay carrying fewer features than that is
 * clipped, whoever clipped it. A row whose geometry is null counts as clipped
 * too, which is deliberate: this errs toward disclosure, and disclosure is the
 * direction that cannot mislead.
 */

/** The truncation pair every preview surface consumes (see ephemeral-preview). */
export interface ChatOverlayCompleteness {
  truncated?: true;
  totalCount?: number;
}

export function chatOverlayCompleteness(
  action: { truncated?: unknown; row_count?: unknown },
  featureCount: number,
): ChatOverlayCompleteness {
  const total = typeof action.row_count === 'number' ? action.row_count : undefined;
  const clipped = action.truncated === true || (total != null && featureCount < total);
  if (!clipped) return {};
  // fix(#1076): the flag does not wait for the total. A clip filters rows, so
  // the server reports no source total for it; the surface picks its wording
  // from whether one arrived.
  return { truncated: true, ...(total != null ? { totalCount: total } : {}) };
}

/** Features in a payload the caller has already shaped as a FeatureCollection. */
export function overlayFeatureCount(geojson: GeoJSON.FeatureCollection): number {
  return Array.isArray(geojson.features) ? geojson.features.length : 0;
}
