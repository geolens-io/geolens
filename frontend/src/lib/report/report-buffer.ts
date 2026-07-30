// In-memory ring buffer for the in-app problem reporter.
//
// A single app-wide buffer that capture sources (console, window errors,
// network/TanStack Query failures, MapLibre errors, React error boundaries)
// push into, and the ReportProblemHost UI reads from. Framework-agnostic on the
// write side (capture happens outside React, e.g. window.onerror) and exposed to
// React via useSyncExternalStore on the read side.
//
// Always-on: it starts buffering at app load so that when a user notices a bug
// and opens the reporter, the history that led up to it is already captured.
// Bounded to MAX_ENTRIES (oldest dropped) and in-memory only — nothing is
// persisted, so a reload clears it.

import { useSyncExternalStore } from 'react';
import { redact } from './redact';

export type ReportSeverity = 'error' | 'warning' | 'info';
export type ReportSource = 'console' | 'network' | 'maplibre' | 'react' | 'runtime';

export interface ReportEntry {
  id: string;
  ts: number;
  severity: ReportSeverity;
  source: ReportSource;
  message: string;
  detail?: string;
  /** True when the source deliberately hides this from the user (e.g. a
   * suppressed MapLibre tile error) — still captured because it's often the
   * actual bug, shown tagged in the technical-details view. */
  suppressed?: boolean;
  /** Number of consecutive identical occurrences collapsed into this entry. */
  count: number;
}

export interface ReportEntryInput {
  severity: ReportSeverity;
  source: ReportSource;
  message: string;
  detail?: string;
  suppressed?: boolean;
}

const MAX_ENTRIES = 200;
const DEDUP_WINDOW_MS = 15_000;
const MAX_MESSAGE_LEN = 2000;
const MAX_DETAIL_LEN = 8000;

let entries: ReportEntry[] = [];
let seq = 0;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

/**
 * Append an entry to the buffer (newest first). Redacts message + detail at
 * capture time, collapses consecutive duplicates, and trims to MAX_ENTRIES.
 * Swallows all errors — capture must never throw into the host code path.
 */
export function pushReportEntry(input: ReportEntryInput): void {
  try {
    const message = redact(input.message).slice(0, MAX_MESSAGE_LEN);
    const detail = input.detail ? redact(input.detail).slice(0, MAX_DETAIL_LEN) : undefined;
    const now = Date.now();

    const last = entries[0];
    if (
      last &&
      last.source === input.source &&
      last.severity === input.severity &&
      last.suppressed === input.suppressed &&
      last.message === message &&
      now - last.ts < DEDUP_WINDOW_MS
    ) {
      const merged: ReportEntry = {
        ...last,
        count: last.count + 1,
        ts: now,
        detail: detail ?? last.detail,
      };
      entries = [merged, ...entries.slice(1)];
      emit();
      return;
    }

    const entry: ReportEntry = {
      id: `${now}-${(seq += 1)}`,
      ts: now,
      severity: input.severity,
      source: input.source,
      message,
      detail,
      suppressed: input.suppressed,
      count: 1,
    };
    entries = [entry, ...entries].slice(0, MAX_ENTRIES);
    emit();
  } catch {
    // Capture is best-effort; never destabilize the app to log a problem.
  }
}

/** Convenience tap for network / TanStack Query failures. */
export function reportNetworkError(opts: {
  status: number;
  url?: string;
  detail?: unknown;
}): void {
  const { status, url, detail } = opts;
  const severity: ReportSeverity = status === 0 || status >= 500 ? 'error' : 'warning';
  const label = status === 0 ? 'Network unavailable' : `HTTP ${status}`;
  const where = url ? ` — ${url}` : '';
  pushReportEntry({
    severity,
    source: 'network',
    message: `${label}${where}`,
    detail: stringifyDetail(detail),
  });
}

/**
 * fix(#890): convenience tap for a tile-token re-mint. The reactive 403 burst
 * the proactive tab-return re-mint (#755 / #881) replaced at least left evidence
 * in this buffer that a recovery had happened; the visible-edge path is silent,
 * so a "tiles were briefly broken" report arrives with no trace of the token
 * rotation that fixed it. Called from `useTileAuthRecovery` only when a mint
 * actually starts, so one entry means one mint. Suppressed — routine
 * maintenance, never something to show the user — and both `surface` and
 * `trigger` are in the message so concurrent surfaces and the tab-return vs
 * tile-error paths stay separate entries instead of one deduped row.
 */
export function reportTileTokenRemint(surface: string, trigger: string): void {
  pushReportEntry({
    severity: 'info',
    source: 'maplibre',
    message: `Tile tokens re-minted (${surface}, ${trigger})`,
    suppressed: true,
  });
}

/**
 * fix(#908): how many distinct failures the buffer holds, not how many rows.
 * Every unrecovered map error writes TWO error rows — a `maplibre` row from the
 * surface handler (which carries the sourceId, so it cannot be dropped) and a
 * `console` row derived from `logUnhandledMapError`'s console.error (which is
 * the only trace the viewer and dataset preview leave at all). Both carry the
 * same AJAXError message, so the message is the correlation key the rows
 * already share, and counting distinct ones stops the badge reading "2 errors"
 * for one broken tile source.
 *
 * Recurrences of the same message count once: the badge answers "how many
 * things are wrong", and a tile source that fails again is the same thing.
 */
export function countDistinctFailures(list: ReportEntry[]): number {
  // A `maplibre` row keys on its SOURCE as well as its message: two cluster
  // layers over one dataset get their own MapLibre source (getSourceIdForLayer)
  // and can fail with byte-identical URLs, and those are two broken layers.
  const mapFailures = new Set<string>();
  // …and the messages those rows already account for, so the `console` row
  // derived from the same AJAXError is recognized as the other half of one
  // failure rather than counted again.
  const mapMessages = new Set<string>();
  const consoleOnly = new Set<string>();
  const others = new Set<string>();

  for (const entry of list) {
    if (entry.severity !== 'error') continue;
    const message = failureKey(entry.message);
    if (entry.source === 'maplibre') {
      // Source id AND normalized message, not either alone. The id separates
      // two cluster layers over one dataset, which fail with byte-identical
      // URLs; the message separates two custom basemaps, which `toMaplibreStyle`
      // both hands the fixed source id `basemap`. Neither is unique on its own.
      mapFailures.add(`${message}\u0000${sourceIdOf(entry)}`);
      mapMessages.add(message);
    } else if (entry.source === 'console') {
      consoleOnly.add(message);
    } else {
      // Every other source keys on its own identity too: two PanelErrorBoundary
      // instances can throw the same common message from different panels, and
      // those are two failures.
      others.add(`${entry.source}\u0000${entry.message}\u0000${entry.detail ?? ''}`);
    }
  }

  let count = mapFailures.size + others.size;
  for (const message of consoleOnly) {
    // Only a console row with no map row behind it is a failure of its own —
    // that is the viewer and the dataset preview, which push no row at all.
    if (!mapMessages.has(message)) count += 1;
  }
  return count;
}

/** The failing MapLibre source, as the surface handlers record it
 * (`detail: "source: <id>"`). Empty when the error carries none — style and
 * glyph errors do not. */
function sourceIdOf(entry: ReportEntry): string {
  const match = /(?:^|\s)source:\s*(\S+)/.exec(entry.detail ?? '');
  return match?.[1] ?? '';
}

/**
 * fix(#908): collapse a message down to the failure it describes. MapLibre
 * builds an AJAXError message as `AJAXError: <status> (<code>): <url>`, so
 * without this every failing tile of ONE broken source is its own key and the
 * badge still runs to 9+.
 *
 * Only the parts that vary WITHIN one source are dropped: the tile address in
 * each of MapLibre's supported forms — `{z}/{x}/{y}`, `{quadkey}`, the
 * `{bbox-epsg-3857}` query param, the `{prefix}` shard label, and the `{ratio}`
 * suffix a retina display resolves to `@2x`, all reachable through an
 * admin-configured remote style — and the rotating credential params.
 * Everything that distinguishes one source from another stays — the rest of the
 * path, the status, and the `cols`/`cluster_radius`/`cluster_max_zoom` params.
 *
 * A `maplibre` row keys on its source id instead and never needs this; it
 * matters for the `console` rows the viewer and dataset preview leave behind,
 * which carry no source at all.
 */
const VOLATILE_TILE_PARAMS = new Set(['sig', 'exp', 'scope', '_v', 'bbox', 'BBOX']);

function failureKey(message: string): string {
  return message
    // MapLibre's `{prefix}` resolves to two hex characters derived from the
    // tile's x/y, and it may sit ANYWHERE in the template — a host label
    // (`//a3.tiles…`) or a path segment (`/tiles/{prefix}/{z}/…`). Either way
    // one sharded source otherwise yields a different URL per tile.
    .replace(/(https?:\/\/)[0-9a-f]{1,2}\./gi, '$1{prefix}.')
    // Tile coordinates, anchored to the end of the path — that is where z/x/y
    // always sit, and anchoring is what keeps an all-numeric `{prefix}` segment
    // (`/00/5/1/1.png`) from being mistaken for the zoom.
    // The `y` segment is an alternation because `redact()` runs FIRST, at
    // capture time, and a retina tile ending `/1539@2x.png` looks exactly like
    // an email address to it — so what actually reaches this function is
    // `/12/1205/[redacted-email]`, with the coordinate already gone.
    .replace(
      /\/\d+\/\d+\/(?:\d+(?:@\d+x)?(?:\.\w+)?|\[redacted-email\])(?=[?\s]|$)/g,
      '/{z}/{x}/{y}',
    )
    // A quadkey is the LAST path segment, one base-4 run whose length is the
    // zoom level — so it is anchored at the end rather than length-gated, or a
    // zoom-3 tile (`/031.png`) would stay a distinct key while a zoom-12 one
    // collapsed. Anchoring is what keeps a mid-path `/2/` from matching.
    .replace(/\/[0-3]+(@\d+x)?(\.\w+)?(?=[?\s]|$)/g, '/{quadkey}')
    // NOT the path-segment form of `{prefix}`. A resolved shard (`/a3/`) is
    // indistinguishable from a meaningful static segment (`/ca/`, `/de/`) in a
    // single URL — both are two hex-ish characters — so normalizing it merged
    // two genuinely different sources into one. Between the two errors, the
    // over-count is the safer one to keep: this is a problem REPORTER, and
    // hiding a broken source is worse than counting a sharded one twice.
    // A `{prefix}` in the HOST is still normalized above, where a one-or-two
    // character first label is overwhelmingly a shard rather than a distinct
    // host. Only console-only rows (viewer, dataset preview) are exposed at
    // all; anything with a source id keys on that instead.
    .replace(/\?(\S*)/g, (_match, query: string) => {
      const kept = query
        .split('&')
        .filter((pair) => pair && !VOLATILE_TILE_PARAMS.has(pair.split('=')[0]));
      return kept.length > 0 ? `?${kept.join('&')}` : '';
    });
}

function stringifyDetail(detail: unknown): string | undefined {
  if (detail == null) return undefined;
  if (typeof detail === 'string') return detail;
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

export function clearReportEntries(): void {
  entries = [];
  emit();
}

export function getReportEntries(): ReportEntry[] {
  return entries;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React hook: subscribe to the live buffer (newest first). */
export function useReportEntries(): ReportEntry[] {
  return useSyncExternalStore(subscribe, getReportEntries, getReportEntries);
}
