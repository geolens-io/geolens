// The ephemeral preview has two surfaces: the builder's non-persisting stack
// row (EphemeralPreviewRow) and the badge for surfaces with no layer stack
// (public viewer, <1100px builder rail). The count sentence lives here so the
// two can't drift.

import { useEffect, useState } from 'react';

type BuilderTranslator = (key: string, options?: Record<string, unknown>) => string;

export interface EphemeralCountInput {
  featureCount: number;
  /** Whether the result was truncated server-side. */
  truncated?: boolean;
  /** Total feature count before truncation. */
  totalCount?: number;
  /** totalCount was computed against the map's viewport, not the whole
   *  dataset; see the field of the same name on useEphemeralLayers' state. */
  viewportScoped?: boolean;
}

/**
 * Why the preview's "Save as dataset…" affordance is disabled. A closed union,
 * not a free string, so the copy stays in the component (and all five locales)
 * instead of at each call site.
 */
export type PreviewSaveDisabledReason = 'truncated';

/** What "Save as dataset…" does for the preview currently on screen. */
type PreviewSaveMode =
  /** Hand off to the Analysis panel, which re-runs the operation server-side. */
  | 'analysis'
  /** Snapshot the client's FeatureCollection through ingest. */
  | 'snapshot'
  /** Offered but not actionable — see `previewSaveMode`. */
  | 'truncated'
  /** Nothing to offer. */
  | 'none';

interface PreviewSaveInput {
  /** Set when an Analysis operation is behind this preview. */
  analysis?: unknown;
  /** Whether the server capped the result. */
  truncated?: boolean;
  /** How many features the client actually holds. */
  featureCount: number;
  /** The producer that stamped this preview, when not the chat (today only
   *  'analysis-panel'). */
  source?: string;
}

/**
 * Decide what the preview surfaces offer for "Save as dataset…".
 *
 * The truncation guard applies to the snapshot path only: a snapshot persists
 * the client's copy, so saving a capped one would file "first N of M" in the
 * catalog as if it were the whole answer, a misrepresentation that outlives the
 * session. The analysis handoff re-runs the operation server-side and
 * materializes the complete result, so a capped preview says nothing about what
 * it would save; blocking it would remove a working path for no reason.
 *
 * `canSaveDataset` gates the snapshot path only, for the same reason: it is
 * the one that turns client-held data into a dataset (POST /ingest/*).
 */
export function previewSaveMode(
  result: PreviewSaveInput | null | undefined,
  canSaveDataset: boolean,
): PreviewSaveMode {
  if (!result) return 'none';
  if (result.analysis) return 'analysis';
  // Only a preview the chat produced is snapshottable. A stamped source means
  // another surface drew this overlay and owns its save (the Analysis panel's
  // Create dataset materializes the whole operation server-side); its preview
  // is also bbox-scoped, so a snapshot would persist whatever the map happened
  // to be looking at. An allowlist, so a future producer is excluded by default.
  if (result.source) return 'none';
  // A snapshot of nothing is not a dataset; an empty result offers no save (the
  // ingest preview would 422).
  if (!canSaveDataset || result.featureCount < 1) return 'none';
  return result.truncated ? 'truncated' : 'snapshot';
}

/**
 * The preview's "how many features?" sentence.
 *
 * Three cases, not two. A clip filters rows, so the server can't report a
 * source total for it and the honest answer to "of how many?" is unknown;
 * falling back to the plain count would present a capped preview as complete.
 * Capped-with-a-total keeps its "N of M"; capped-without says so without
 * inventing one.
 */
export function ephemeralCountLabel(
  t: BuilderTranslator,
  { featureCount, truncated, totalCount, viewportScoped }: EphemeralCountInput,
): string {
  if (!truncated) return t('ephemeralBadge.featureCount', { count: featureCount });
  if (totalCount != null) {
    // A viewport-scoped total must say "of what": "180 of 22,324" would read
    // like a capped-in-ingest-order result, though the 180 is what was on
    // screen at the time of the request.
    //
    // "previewed extent", not "in view": this badge mounts alongside
    // useEphemeralLayers' fitBounds(), which re-fits the map to the result
    // geometry's bbox (a capped sample can be a much smaller extent than the
    // requested viewport), so the visible map has often moved on from the extent
    // the total was computed against. "Previewed extent" names what the number is
    // scoped to without claiming it matches the screen, and matches the toast
    // wording (AnalysisPanel's truncatedNoticeTotalScoped/
    // truncatedNoticeMatchedScoped).
    if (viewportScoped) {
      return t('ephemeralBadge.featureCountTruncatedScoped', {
        count: featureCount,
        total: totalCount,
        defaultValue: '{{count, number}} of {{total, number}} features in the previewed extent',
      });
    }
    return t('ephemeralBadge.featureCountTruncated', {
      count: featureCount,
      // Both numbers passed raw: the locale strings group them via
      // {{count, number}}/{{total, number}}, and count drives plural selection.
      total: totalCount,
      defaultValue: '{{count, number}} of {{total, number}} features',
    });
  }
  return t('ephemeralBadge.featureCountCapped', {
    count: featureCount,
    defaultValue: 'first {{count, number}} features',
  });
}

/**
 * The sentence assistive tech hears when a preview appears or its count
 * changes: "Result · 240 of 10,651 features". Shared so the row and the badge
 * announce the same thing.
 */
export function ephemeralStatusLabel(t: BuilderTranslator, input: EphemeralCountInput): string {
  return t('ephemeralBadge.statusLabel', {
    result: t('ephemeralBadge.queryResult'),
    summary: ephemeralCountLabel(t, input),
    defaultValue: '{{result}} · {{summary}}',
  });
}

/**
 * Live regions announce only mutations made while the region is already in the
 * accessibility tree, and both preview surfaces mount with their text, so
 * role="status" on the wrapper alone would stay silent. Mount the region empty
 * and populate it a frame later so the success (and later count changes)
 * arrives as a mutation assistive tech reads.
 */
export function useAnnouncedLabel(statusLabel: string): string {
  const [announcedLabel, setAnnouncedLabel] = useState('');
  useEffect(() => {
    const frame = requestAnimationFrame(() => setAnnouncedLabel(statusLabel));
    return () => cancelAnimationFrame(frame);
  }, [statusLabel]);
  return announcedLabel;
}
