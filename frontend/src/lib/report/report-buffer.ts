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
 * Only what is unambiguously per-TILE is dropped: numeric path segments (the
 * coordinates, in any layout) and the rotating credential params. Everything
 * that identifies the source survives — the rest of the path, the host, the
 * status, and the `cols`/`cluster_radius`/`cluster_max_zoom` params.
 *
 * Deliberately NOT the `{prefix}` shard, in the host or the path. A resolved
 * shard is indistinguishable from a meaningful short label in a single URL —
 * `a.tiles…` looks exactly like `ca.tiles…`, `/a3/` like `/de/` — and
 * collapsing it merged two genuinely different basemaps into one entry.
 * Between the two errors, keep the over-count: this is a problem REPORTER, and
 * hiding a broken source is worse than counting a sharded one more than once.
 *
 * A `maplibre` row keys on its source id as well and rarely needs any of this;
 * it matters for the `console` rows the viewer and dataset preview leave
 * behind, which carry no source at all.
 */
// Per-tile or rotating query params: the credential set, plus the coordinate
// names a tile template can use. A template may put the whole tile address in
// the query (`?z={z}&x={x}&y={y}`), which the custom-basemap validator accepts,
// so those are as per-tile as a path segment is. The `tile*`/`TileMatrix` names
// are WMTS's. Matched case-insensitively, since the same params appear
// upper-cased in WMS/WMTS-style templates.
//
// Names, not values. A parameter's VALUE being numeric does not make it a
// coordinate — `?layer=3` is source-defining — and collapsing on that would
// merge two different sources. A template using a name not on this list
// (`?column={x}`) therefore over-counts rather than under-counts, which is the
// same trade-off the host/path note below describes.
const VOLATILE_TILE_PARAMS = new Set([
  'sig', 'exp', 'scope', '_v',
  'z', 'x', 'y', 'zoom', 'level',
  'col', 'column', 'row',
  // WMTS: TileMatrix is the zoom and TileRow/TileCol the coordinates, but
  // TileMatrixSet names the GRID (EPSG:3857 vs EPSG:4326) and is therefore
  // source-defining — two basemaps can differ by nothing else.
  'tilecol', 'tilerow', 'tilematrix',
  'bbox', 'quadkey',
]);

function failureKey(message: string): string {
  return message
    // Every purely numeric path segment. That single rule covers each tile
    // layout MapLibre supports — `{z}/{x}/{y}` with or without a static suffix
    // (`/12/1205/1539/tile.png`), a leading numeric shard, and `{quadkey}`,
    // which is all digits too. Anchoring on "is a number" rather than on a
    // shape means a template this does not anticipate still normalizes.
    // It also tolerates `redact()` having already eaten a `@2x` suffix as an
    // email address (see the note above `pushReportEntry`): the surviving z/x
    // segments still collapse.
    .replace(/\/\d+(?=[/?.@\s]|$)/g, '/{n}')
    .replace(/\?(\S*)/g, (_match, query: string) => {
      const kept = query
        .split('&')
        .filter((pair) => pair && !VOLATILE_TILE_PARAMS.has(pair.split('=')[0].toLowerCase()));
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
