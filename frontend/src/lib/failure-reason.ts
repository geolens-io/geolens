/**
 * fix(#1953): the code ADR-002 Decision 3 stores in place of a failure the
 * server did not compose (`backend/app/core/failure_reason.py`). Every surface
 * that renders a job or run reason maps it here, or the reader gets an
 * untranslated identifier where a sentence belongs.
 */
export const INTERNAL_FAILURE_REASON = 'internal_error';

/** The stored reason, or a localized line when the reason is only a code. */
export function describeFailureReason(reason: string, localizedFallback: string): string {
  return reason === INTERNAL_FAILURE_REASON ? localizedFallback : reason;
}
