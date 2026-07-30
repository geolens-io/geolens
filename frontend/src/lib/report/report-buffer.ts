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
 * fix(#890): convenience tap for the proactive tab-return tile-token re-mint
 * (#755 / #881). The reactive 403 burst that re-mint replaced at least left
 * evidence in this buffer that a recovery had happened; the visible-edge hook
 * is silent, so a "tiles were briefly broken" report arrives with no trace of
 * the token rotation. Suppressed — it is routine maintenance, never something
 * to show the user — and `surface` is part of the message so two map surfaces
 * re-minting at once don't collapse into one deduped entry.
 */
export function reportTileTokenRemint(surface: string): void {
  pushReportEntry({
    severity: 'info',
    source: 'maplibre',
    message: `Tile-token re-mint requested on tab return (${surface}, expiring signature)`,
    suppressed: true,
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
