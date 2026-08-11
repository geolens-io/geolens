/**
 * feat(#531 follow-up): session-scoped handoff of a chat query result into
 * the map builder.
 *
 * DatasetChatPanel has no map, so "Open in builder" creates a map and
 * navigates with `?add_dataset=<id>&chat_result=1`. The spatial result
 * payload (too large for a URL) rides sessionStorage under a single key;
 * MapBuilderPage takes it exactly once after the map instance exists and
 * renders it through the existing ephemeral-layer mechanism
 * (use-ephemeral-layers.ts).
 *
 * Exception-safe: private-mode Safari / disabled storage / quota overflow on
 * a large FeatureCollection must degrade to "open without the result", never
 * block the navigation.
 */

export interface ChatResultHandoff {
  geojson: GeoJSON.FeatureCollection;
  bbox: [number, number, number, number];
  /** feat(#1241 codex r1): whether the overlay holds the whole answer, and of
   *  how many. Geometry alone was enough while the builder could only draw and
   *  dismiss a carried result; now it can also be saved as a dataset, and a
   *  handoff that drops the completeness pair arrives looking complete. */
  truncated?: true;
  totalCount?: number;
  /** feat(#1241): the question this result answers, so the builder can suggest
   *  a name for it. Absent handoffs fall back to a generic title. */
  prompt?: string;
}

const KEY = 'geolens-chat-result';

/**
 * Validate a show_query_result-style geojson/bbox pair. Mirrors
 * ViewerChatPanel's flyover guard: finite, WGS84-bounded, non-inverted bbox
 * (fix(#527 B-054/C-06) — NaN/inverted bounds throw in fitBounds).
 *
 * Geometry only: the completeness pair and the prompt are added by the caller
 * that has them, so this stays the one place that decides whether a payload is
 * drawable at all.
 */
export function toChatResultHandoff(geojson: unknown, bbox: unknown): ChatResultHandoff | null {
  if (
    !geojson ||
    typeof geojson !== 'object' ||
    !('type' in geojson) ||
    geojson.type !== 'FeatureCollection' ||
    !Array.isArray(bbox) ||
    bbox.length !== 4 ||
    !bbox.every((n: unknown) => Number.isFinite(n))
  ) {
    return null;
  }
  const [minX, minY, maxX, maxY] = bbox as [number, number, number, number];
  if (minX < -180 || minY < -90 || maxX > 180 || maxY > 90 || minX > maxX || minY > maxY) {
    return null;
  }
  return { geojson: geojson as GeoJSON.FeatureCollection, bbox: [minX, minY, maxX, maxY] };
}

/** Stash a result for the builder to pick up. False = storage unavailable/full. */
export function stashChatResult(result: ChatResultHandoff): boolean {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(result));
    return true;
  } catch {
    return false;
  }
}

/** Take (read + clear) the stashed result. Null on absence or malformed payload. */
export function takeChatResult(): ChatResultHandoff | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const { geojson, bbox, truncated, totalCount, prompt } = parsed as {
      geojson?: unknown;
      bbox?: unknown;
      truncated?: unknown;
      totalCount?: unknown;
      prompt?: unknown;
    };
    const carried = toChatResultHandoff(geojson, bbox);
    if (!carried) return null;
    // The stash is same-session and self-written, but it is still parsed
    // input: type-check each field rather than trust it, so a malformed entry
    // cannot hand the builder a bogus total (or a truthy non-true `truncated`).
    return {
      ...carried,
      ...(truncated === true ? { truncated: true as const } : {}),
      ...(typeof totalCount === 'number' && Number.isFinite(totalCount) ? { totalCount } : {}),
      ...(typeof prompt === 'string' ? { prompt } : {}),
    };
  } catch {
    return null;
  }
}
