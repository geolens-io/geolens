import i18n from '@/i18n/i18n';

/**
 * fix(#1953): the code ADR-002 Decision 3 stores in place of a failure the
 * server did not compose (`backend/app/core/failure_reason.py`). Every surface
 * that renders a job or run reason maps it here, or the reader gets an
 * untranslated identifier where a sentence belongs.
 */
export const INTERNAL_FAILURE_REASON = 'internal_error';

/**
 * The locale key for each `error_code` the server stores beside a reason it
 * wrote as a fixed sentence (`FixedReason`). Checked against every backend
 * code by `backend/tests/test_job_failure_codes.py`.
 */
const FIXED_FAILURE_CODE_KEYS: Record<string, `errors.${string}`> = {
  abandoned: 'errors.jobFailureRefreshAbandoned',
  analysis_worker_shutdown: 'errors.jobFailureAnalysisWorkerShutdown',
  backfill_failed: 'errors.jobFailureBackfillFailed',
  backfill_not_queued: 'errors.jobFailureBackfillNotQueued',
  backfill_settle_failed: 'errors.jobFailureBackfillSettleFailed',
  backfill_start_failed: 'errors.jobFailureBackfillStartFailed',
  backfill_worker_shutdown: 'errors.jobFailureBackfillWorkerShutdown',
  dataset_deleted: 'errors.jobFailureDatasetDeleted',
  dispatch_interrupted: 'errors.jobFailureDispatchInterrupted',
  missing_crs: 'errors.jobFailureMissingCrs',
  missing_crs_raster: 'errors.jobFailureMissingCrsRaster',
  scheduled_claim_expired: 'errors.jobFailureScheduledClaimExpired',
  scheduled_execution_timeout: 'errors.jobFailureScheduledExecutionTimeout',
  scheduled_job_missing: 'errors.jobFailureScheduledJobMissing',
  stale_never_committed: 'errors.jobFailureStaleNeverCommitted',
  stale_never_queued: 'errors.jobFailureStaleNeverQueued',
  upload_abandoned: 'errors.jobFailureUploadAbandoned',
  user_cancelled: 'errors.jobFailureUserCancelled',
  worker_lost: 'errors.jobFailureWorkerLost',
};

/** A fixed reason's sentence in the reader's language, or undefined for any other code. */
export function fixedFailureReason(code: string | null | undefined): string | undefined {
  const key = code ? FIXED_FAILURE_CODE_KEYS[code] : undefined;
  return key ? (i18n.t(key, { ns: 'common' }) as string) : undefined;
}

/**
 * The reason in the reader's language when its code names a fixed sentence,
 * the localized fallback when the reason is only a code, or else the reason
 * as stored.
 */
export function describeFailureReason(
  reason: string,
  localizedFallback: string,
  code?: string | null,
): string {
  return (
    fixedFailureReason(code) ?? (reason === INTERNAL_FAILURE_REASON ? localizedFallback : reason)
  );
}
