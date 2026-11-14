import i18n from '@/i18n/i18n';

/**
 * The code ADR-002 Decision 3 stores in place of a failure the server did not
 * compose (`backend/app/core/failure_reason.py`). Every surface that renders a
 * job or run reason maps it here, or the reader gets an untranslated identifier.
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
  arcgis_wfs_count_unavailable: 'errors.jobFailureArcgisWfsCountUnavailable',
  arcgis_wfs_repeated: 'errors.jobFailureArcgisWfsRepeated',
  arcgis_wfs_short: 'errors.jobFailureArcgisWfsShort',
  backfill_failed: 'errors.jobFailureBackfillFailed',
  backfill_not_queued: 'errors.jobFailureBackfillNotQueued',
  backfill_settle_failed: 'errors.jobFailureBackfillSettleFailed',
  backfill_start_failed: 'errors.jobFailureBackfillStartFailed',
  backfill_worker_shutdown: 'errors.jobFailureBackfillWorkerShutdown',
  credential_over_http: 'errors.jobFailureCredentialOverHttp',
  dataset_deleted: 'errors.jobFailureDatasetDeleted',
  dispatch_interrupted: 'errors.jobFailureDispatchInterrupted',
  duplicate_source: 'errors.jobFailureDuplicateSource',
  geometry_columns_missing: 'errors.reuploadGeometryColumnsMissing',
  missing_crs: 'errors.jobFailureMissingCrs',
  missing_crs_database: 'errors.jobFailureMissingCrsDatabase',
  missing_crs_raster: 'errors.jobFailureMissingCrsRaster',
  missing_crs_reupload: 'errors.jobFailureMissingCrsReupload',
  mixed_srid_database: 'errors.jobFailureMixedSridDatabase',
  pointcloud_decode_failed: 'errors.uploadPointCloudDecodeFailed',
  pointcloud_invalid: 'errors.uploadPointCloudInvalid',
  pointcloud_no_crs: 'errors.uploadPointCloudNoCrs',
  pointcloud_not_copc: 'errors.uploadPointCloudNotCopc',
  refresh_origin_unsupported: 'errors.jobFailureRefreshOriginUnsupported',
  review_required: 'errors.jobFailureReviewRequired',
  scheduled_claim_expired: 'errors.jobFailureScheduledClaimExpired',
  scheduled_execution_timeout: 'errors.jobFailureScheduledExecutionTimeout',
  scheduled_job_missing: 'errors.jobFailureScheduledJobMissing',
  service_auth_refused: 'errors.serviceAuthRefused',
  service_empty_page: 'errors.serviceEmptyPage',
  service_error: 'errors.serviceAnsweredError',
  stale_never_committed: 'errors.jobFailureStaleNeverCommitted',
  stale_never_queued: 'errors.jobFailureStaleNeverQueued',
  upload_abandoned: 'errors.jobFailureUploadAbandoned',
  user_cancelled: 'errors.jobFailureUserCancelled',
  worker_lost: 'errors.jobFailureWorkerLost',
};

// The server's sentence for `geometry_columns_missing`
// (`geometry_columns_missing_refusal` in backend/app/core/upload_errors.py),
// split around the column names it interpolates.
const GEOMETRY_COLUMNS_MISSING_PREFIX =
  "The replacement lacks the columns this dataset's geometry is built from (";
const GEOMETRY_COLUMNS_MISSING_SUFFIX =
  '), so nothing was changed. Add them to the file, or import the file as a new dataset instead.';

/** The values a fixed sentence names, read back out of the stored reason. */
const FIXED_FAILURE_VALUES: Record<string, (reason: string) => Record<string, string> | undefined> = {
  geometry_columns_missing: (reason) =>
    reason.startsWith(GEOMETRY_COLUMNS_MISSING_PREFIX) && reason.endsWith(GEOMETRY_COLUMNS_MISSING_SUFFIX)
      ? {
          columns: reason.slice(
            GEOMETRY_COLUMNS_MISSING_PREFIX.length,
            reason.length - GEOMETRY_COLUMNS_MISSING_SUFFIX.length,
          ),
        }
      : undefined,
};

/**
 * A fixed reason's sentence in the reader's language, or undefined for any
 * other code and for a sentence whose values can't be read from ``reason``.
 */
export function fixedFailureReason(
  code: string | null | undefined,
  reason?: string,
): string | undefined {
  const key = code ? FIXED_FAILURE_CODE_KEYS[code] : undefined;
  if (!key || !code) return undefined;
  const readValues = FIXED_FAILURE_VALUES[code];
  if (!readValues) return i18n.t(key, { ns: 'common' }) as string;
  const values = reason === undefined ? undefined : readValues(reason);
  return values ? (i18n.t(key, { ns: 'common', ...values }) as string) : undefined;
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
    fixedFailureReason(code, reason) ??
    (reason === INTERNAL_FAILURE_REASON ? localizedFallback : reason)
  );
}
