// fix(#1009): the ephemeral preview now has two surfaces — the builder's
// non-persisting stack row (EphemeralPreviewRow) and the badge that covers the
// surfaces with no layer stack (public viewer, <1100px builder rail). The count
// sentence is identical on both, so it lives here instead of being copy-pasted
// into the second one and drifting.

import { useEffect, useState } from 'react';

type BuilderTranslator = (key: string, options?: Record<string, unknown>) => string;

export interface EphemeralCountInput {
  featureCount: number;
  /** Whether the result was truncated server-side. */
  truncated?: boolean;
  /** Total feature count before truncation. */
  totalCount?: number;
}

/**
 * The preview's "how many features?" sentence.
 *
 * fix(#1076): three cases, not two. A clip filters rows, so the server cannot
 * report a source total for it — the honest answer to "of how many?" is
 * unknown. Falling back to the plain count there presented a capped preview as
 * the complete result, which is #674's concern through a new door.
 * Capped-with-a-total keeps its "N of M"; capped-without says so without
 * inventing one.
 */
export function ephemeralCountLabel(
  t: BuilderTranslator,
  { featureCount, truncated, totalCount }: EphemeralCountInput,
): string {
  if (!truncated) return t('ephemeralBadge.featureCount', { count: featureCount });
  if (totalCount != null) {
    return t('ephemeralBadge.featureCountTruncated', {
      count: featureCount,
      // fix(#788): both numbers passed raw — the locale strings group them via
      // {{count, number}}/{{total, number}} (one sentence, one grouping), and
      // count keeps driving plural selection.
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
  return `${t('ephemeralBadge.queryResult')} · ${ephemeralCountLabel(t, input)}`;
}

/**
 * fix(#784): live regions only announce mutations made while the region is
 * already in the accessibility tree — both preview surfaces mount WITH their
 * text, so role="status" on the wrapper alone would stay silent. Mount the
 * region empty and populate it a frame later so the preview success (and any
 * later count change) arrives as a mutation assistive tech actually reads.
 */
export function useAnnouncedLabel(statusLabel: string): string {
  const [announcedLabel, setAnnouncedLabel] = useState('');
  useEffect(() => {
    const frame = requestAnimationFrame(() => setAnnouncedLabel(statusLabel));
    return () => cancelAnimationFrame(frame);
  }, [statusLabel]);
  return announcedLabel;
}
