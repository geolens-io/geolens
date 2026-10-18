/**
 * Whether a chat overlay holds the WHOLE answer.
 *
 * `truncated` on a show_query_result action is the SQL sandbox's row-cap flag,
 * not a statement about the FeatureCollection: when the model selects geometry
 * itself, `backend/app/processing/ai/chat_actions.py` runs at the sandbox's
 * 1000-row limit and then slices the overlay to a 50-row render budget, so a
 * 300-row answer arrives as 50 features with `truncated: false`. Trusting that
 * flag would label a clipped preview complete and let a snapshot save file 50
 * of 300 rows as the answer.
 *
 * `row_count` is the matched-row total the model narrates, so an overlay with
 * fewer features than that is clipped, whoever clipped it. A row whose geometry
 * is null counts as clipped too: this errs toward disclosure, which cannot
 * mislead.
 */

/** The truncation pair every preview surface consumes (see ephemeral-preview). */
interface ChatOverlayCompleteness {
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
  // The flag does not wait for the total: a clip filters rows, so the server
  // reports no source total, and the surface picks its wording from whether one arrived.
  return { truncated: true, ...(total != null ? { totalCount: total } : {}) };
}

/** Features in a payload the caller has already shaped as a FeatureCollection. */
export function overlayFeatureCount(geojson: GeoJSON.FeatureCollection): number {
  return Array.isArray(geojson.features) ? geojson.features.length : 0;
}
