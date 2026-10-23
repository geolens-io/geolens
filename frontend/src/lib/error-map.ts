import i18n from '@/i18n/i18n';

type TranslationValues = Record<string, string | number>;

interface ApiErrorDescriptor {
  key: `errors.${string}`;
  values?: TranslationValues;
}

/**
 * Backend messages with useful, stable domain meaning. The API's English
 * `detail` remains diagnostic data; this table is the compatibility boundary
 * that turns it into a locale key before it reaches UI code.
 */
const EXACT_ERROR_KEYS: Record<string, ApiErrorDescriptor['key']> = {
  'Dataset not found': 'errors.datasetNotFound',
  'Collection not found': 'errors.collectionNotFound',
  'Map not found': 'errors.mapNotFound',
  'Incorrect username or password': 'errors.incorrectCredentials',
  'Your account is awaiting approval': 'errors.awaitingApproval',
  'Account not active': 'errors.accountNotActive',
  'Insufficient permissions': 'errors.insufficientPermissions',
  'Not authorized to modify this map': 'errors.notAuthorized',
  'Not authorized to modify this record': 'errors.notAuthorizedResource',
  'Only the collection owner or an admin may modify this collection.':
    'errors.notAuthorizedResource',
  'Only the dataset owner or an admin may modify this dataset.':
    'errors.notAuthorizedResource',
  'Registration is disabled': 'errors.registrationDisabled',
  'Export failed': 'errors.exportFailed',
  'Job not found': 'errors.jobNotFound',
  'Feature not found': 'errors.featureNotFound',
  'Layer not found': 'errors.layerNotFound',
  'User not found': 'errors.userNotFound',
  'API key not found': 'errors.apiKeyNotFound',
  'This dataset already has 100 active keys. Revoke one to create another.':
    'errors.datasetKeyLimit',
  'Value labels for this dataset are over the 1 MB limit.':
    'errors.valueLabelsTooLarge',
  'Access denied': 'errors.accessDenied',
  'Could not validate credentials': 'errors.couldNotValidateCredentials',
  'Inactive user': 'errors.inactiveUser',
  'Authentication required': 'errors.authenticationRequired',
  'Not authenticated': 'errors.authenticationRequired',
  'Saved search not found': 'errors.savedSearchNotFound',
  'Record not found': 'errors.recordNotFound',
  'Record translation not found': 'errors.recordTranslationNotFound',
  'Shared map not found': 'errors.sharedMapNotFound',
  'Map must be public before sharing': 'errors.mapMustBePublic',
  'Job already processed': 'errors.jobAlreadyProcessed',
  'Job does not belong to this dataset': 'errors.jobNotBelongToDataset',
  'Not authorized to access this job': 'errors.notAuthorizedJob',
  'Not authorized to retry this job': 'errors.notAuthorizedRetry',
  'Not authorized to view this job': 'errors.notAuthorizedView',
  'Only failed jobs can be retried': 'errors.onlyFailedRetry',
  'Thumbnail too large (max 100KB)': 'errors.thumbnailTooLarge',
  'Body must be a data:image/ URI': 'errors.bodyMustBeDataImage',
  'Invalid target_crs: must match EPSG:<code> (e.g. EPSG:3857)':
    'errors.invalidTargetCrs',
  'Staging file no longer available. Please re-upload.':
    'errors.stagingFileUnavailable',
  'This service requires authentication. Provide an access token and try again.':
    'errors.serviceRequiresAuth',
  // The ArcGIS wording of the auth-required refusal (ArcGISTokenError in
  // sources/router.py); unmapped it falls to the generic 403 and hides that a
  // token is the fix.
  'This service requires authentication. Provide a valid ArcGIS token and try again.':
    'errors.serviceRequiresAuth',
  'Could not reach the service. Check the URL and try again.':
    'errors.couldNotReachService',
  "Service didn't respond in time. Check the URL and try again.":
    'errors.serviceTimeout',
  'Remote service returned an error': 'errors.remoteServiceError',
  'AI features are currently disabled': 'errors.aiDisabled',
  'AI features are disabled by administrator': 'errors.aiDisabled',
  'AI is not configured (missing API key)': 'errors.aiNotConfigured',
  'Selected LLM provider API key not configured': 'errors.aiNotConfigured',
  'AI map generation failed unexpectedly': 'errors.aiGenerationFailed',
  'Chat map editing failed unexpectedly': 'errors.chatEditingFailed',
  'Could not connect to LLM provider': 'errors.couldNotConnectLlm',
  'LLM provider returned an error': 'errors.remoteServiceError',
  'An unexpected error occurred during upload': 'errors.uploadError',
  'An unexpected error occurred while previewing the layer.': 'errors.previewError',
  'Failed to preview remote layer. The service may be unavailable or the layer format is unsupported.':
    'errors.remotePreviewError',
  'Dataset membership not found': 'errors.datasetMembershipNotFound',
  'This shared map link has expired or been revoked': 'errors.sharedMapExpired',
  'Not a raster dataset': 'errors.notRasterDataset',
  'No raster asset': 'errors.noRasterAsset',
  'Database temporarily unavailable.': 'errors.serviceUnavailable',
  'Tile service unavailable': 'errors.serviceUnavailable',
  'Export temporarily unavailable': 'errors.serviceUnavailable',
  'Task queue unavailable, please retry': 'errors.serviceUnavailable',
  // The sandbox advisory lock is shared between analysis previews and AI chat
  // data queries, so either can be the holder; the copy names both sides.
  'Another data query is already running for this user': 'errors.sharedQueryBusy',
  // The refresh door's refusal taxonomy (router_refresh.py). Each literal is
  // stable UX copy, so matching by exact text fits this table. Wordings for the
  // same taxonomy state collapse to one key: the Source panel shows one message per code.
  'This dataset has no remote service origin to refresh from. Replace its data through re-upload instead.':
    'errors.refreshNotApplicable',
  'This dataset is not backed by a registered table, so there is nothing to re-measure.':
    'errors.refreshNotApplicable',
  "This dataset's source binding is incomplete, so GeoLens cannot re-pull it without being told where from. Re-import the layer through the service import flow.":
    'errors.refreshOriginUnavailable',
  "This dataset's source binding records no layer, so GeoLens cannot tell which layer of the service to re-pull. Re-import the layer through the service import flow.":
    'errors.refreshOriginUnavailable',
  "This dataset's source binding does not record which table it was registered from, so GeoLens cannot tell what to re-measure. Register the table again.":
    'errors.refreshOriginUnavailable',
  'A refresh is already running for this dataset. Wait for it to finish, then try again.':
    'errors.refreshDatasetBusy',
  'The dataset changed after this replacement was held. Upload the file again.':
    'errors.refreshReviewSuperseded',
  "This dataset's source changed while the refresh was being queued, so it was not started. Check the new source and try again.":
    'errors.refreshOriginChanged',
  // The re-upload commit door's own `origin_changed`: a different window from
  // the refresh one (between staging and confirming), and it asks the user to
  // look at the source before replacing anything, not to retry.
  "This dataset's source changed after this replacement was staged, so nothing was queued. Re-check the dataset's source and start the replacement again.":
    'errors.reuploadOriginChanged',
  'This dataset is backed by a registered table in this instance, which needs no service credential. Send the request without a token.':
    'errors.refreshCredentialNotApplicable',
  // The STAC door's wordings of the same taxonomy states.
  'This dataset was not imported from a STAC item, so there is no item to re-resolve.':
    'errors.refreshNotApplicable',
  "This dataset's source binding does not record the STAC item its asset was published in, so GeoLens cannot ask the catalog where that asset is now. Re-import it from the STAC catalog to record one.":
    'errors.refreshOriginUnavailable',
  "GeoLens cannot tell this dataset's STAC item from another one its stored URL might serve: the binding predates item-identity tracking and the catalog's item URLs carry no identity of their own. Re-import it from the STAC catalog to record one.":
    'errors.refreshOriginUnavailable',
  'Refreshing a STAC dataset re-reads a public item document and needs no credential. Send the request without a token.':
    'errors.refreshCredentialNotApplicable',
  'Refreshing a protected service needs a shared credential store so the token can reach the worker without being written to disk. Set REDIS_URL and try again.':
    'errors.refreshCredentialStoreUnavailable',
  'Could not stage the service credential for this refresh. Check that the credential store is reachable and try again.':
    'errors.refreshCredentialStoreUnavailable',
};

// The VRT source-compatibility 422 (validate_sources in
// processing/raster/validation.py) is an array of SourceValidationError objects,
// not the Pydantic loc/type/ctx shape `validationDescriptor` expects. Keyed by
// the backend's stable `code`, one key per code.
const SOURCE_VALIDATION_CODE_KEYS: Record<string, ApiErrorDescriptor['key']> = {
  crs_mismatch: 'errors.sourceValidationCrsMismatch',
  crs_unverified: 'errors.sourceValidationCrsUnverified',
  band_count_mismatch: 'errors.sourceValidationBandCountMismatch',
  single_band_required: 'errors.sourceValidationSingleBandRequired',
  dtype_mismatch: 'errors.sourceValidationDtypeMismatch',
  grid_misaligned: 'errors.sourceValidationGridMisaligned',
  nodata_inconsistent: 'errors.sourceValidationNodataInconsistent',
  rotated_raster: 'errors.sourceValidationRotatedRaster',
  unknown_pixel_geometry: 'errors.sourceValidationUnknownPixelGeometry',
};

/**
 * The upload, presigned, URL-import and re-upload doors' stable refusal
 * codes (`detail.code`), one key per code. `geometry_loss` keeps its own
 * branch below; it is listed here too so the backend registry test finds it
 * mapped. Checked against the backend's codes in both directions by
 * `backend/tests/test_upload_refusal_codes.py`.
 */
const UPLOAD_REFUSAL_CODE_KEYS: Record<string, ApiErrorDescriptor['key']> = {
  content_type_mismatch: 'errors.uploadContentTypeMismatch',
  corrupt_archive_member: 'errors.uploadCorruptArchiveMember',
  disallowed_extension: 'errors.uploadDisallowedExtension',
  driver_metadata_member: 'errors.uploadDriverMetadataMember',
  empty_upload: 'errors.uploadEmpty',
  file_size_exceeded: 'errors.uploadFileSizeExceeded',
  file_size_limit_exceeded: 'errors.uploadFileSizeLimitExceeded',
  filename_control_characters: 'errors.uploadFilenameControlCharacters',
  filename_missing_extension: 'errors.uploadFilenameMissingExtension',
  geometry_loss: 'errors.reuploadGeometryLoss',
  ingest_cell_limit_exceeded: 'errors.uploadIngestCellLimitExceeded',
  ingest_row_limit_exceeded: 'errors.uploadIngestRowLimitExceeded',
  invalid_flatgeobuf_file: 'errors.uploadInvalidFlatgeobuf',
  invalid_import_url: 'errors.uploadInvalidImportUrl',
  invalid_parquet_file: 'errors.uploadInvalidParquet',
  invalid_vrt_body: 'errors.uploadInvalidVrtBody',
  invalid_zip_container: 'errors.uploadInvalidZipContainer',
  missing_filename: 'errors.uploadMissingFilename',
  pointcloud_decode_failed: 'errors.uploadPointCloudDecodeFailed',
  pointcloud_invalid: 'errors.uploadPointCloudInvalid',
  pointcloud_kind_required: 'errors.uploadPointCloudKindRequired',
  pointcloud_no_crs: 'errors.uploadPointCloudNoCrs',
  pointcloud_not_copc: 'errors.uploadPointCloudNotCopc',
  pointcloud_reupload_unsupported: 'errors.reuploadPointCloudUnsupported',
  presigned_size_mismatch: 'errors.uploadPresignedSizeMismatch',
  preview_failed: 'errors.uploadPreviewFailed',
  raster_preview_failed: 'errors.uploadRasterPreviewFailed',
  reupload_unsupported: 'errors.reuploadUnsupported',
  service_preview_failed: 'errors.uploadServicePreviewFailed',
  sqlite_schema_too_large: 'errors.uploadSqliteSchemaTooLarge',
  sqlite_too_many_schema_objects: 'errors.uploadSqliteTooManySchemaObjects',
  sqlite_virtual_table: 'errors.uploadSqliteVirtualTable',
  standalone_vrt_not_supported: 'errors.uploadStandaloneVrtNotSupported',
  tileset_bounding_volume: 'errors.uploadTilesetBoundingVolume',
  tileset_content_uri: 'errors.uploadTilesetContentUri',
  tileset_entry_characters: 'errors.uploadTilesetEntryCharacters',
  tileset_entry_collision: 'errors.uploadTilesetEntryCollision',
  tileset_entry_length: 'errors.uploadTilesetEntryLength',
  tileset_entry_path: 'errors.uploadTilesetEntryPath',
  tileset_extension_mismatch: 'errors.uploadTilesetExtensionMismatch',
  tileset_geometric_error: 'errors.uploadTilesetGeometricError',
  tileset_json: 'errors.uploadTilesetJsonInvalid',
  tileset_json_depth: 'errors.uploadTilesetJsonTooDeep',
  tileset_json_size: 'errors.uploadTilesetJsonTooLarge',
  tileset_kind_required: 'errors.uploadTilesetKindRequired',
  tileset_layout: 'errors.uploadTilesetLayout',
  tileset_region: 'errors.uploadTilesetRegion',
  tileset_reupload_unsupported: 'errors.reuploadTilesetUnsupported',
  tileset_special_entry: 'errors.uploadTilesetSpecialEntry',
  tileset_unpacked_too_large: 'errors.uploadTilesetUnpackedTooLarge',
  tileset_unreadable_entry: 'errors.uploadTilesetUnreadableEntry',
  tileset_version: 'errors.uploadTilesetVersion',
  unreadable_database_file: 'errors.uploadUnreadableDatabase',
  unsafe_upload_content: 'errors.uploadRefused',
  unsafe_vrt_source: 'errors.uploadUnsafeVrtSource',
  unsupported_zip_compression: 'errors.uploadUnsupportedZipCompression',
  vrt_body_too_large: 'errors.uploadVrtBodyTooLarge',
  zip_bomb_ratio: 'errors.uploadZipBombRatio',
  zip_bomb_unpacked_size: 'errors.uploadZipBombUnpackedSize',
  zip_directory_too_large: 'errors.uploadZipDirectoryTooLarge',
  zip_entries_overlap: 'errors.uploadZipEntriesOverlap',
  zip_nested_archive: 'errors.uploadZipNestedArchive',
  zip_too_many_entries: 'errors.uploadZipTooManyEntries',
};

/** `RetentionRefused` codes (`backend/app/modules/catalog/features/retention.py`), from the retention setting and from column changes. */
const RETENTION_REFUSAL_CODE_KEYS: Record<string, ApiErrorDescriptor['key']> = {
  retention_column_in_use: 'errors.retentionColumnInUse',
  retention_column_missing: 'errors.retentionColumnMissing',
  retention_column_not_temporal: 'errors.retentionColumnNotTemporal',
  retention_delete_rule: 'errors.retentionDeleteRule',
  retention_delete_trigger: 'errors.retentionDeleteTrigger',
  retention_gid_unusable: 'errors.retentionGidUnusable',
  retention_has_children: 'errors.retentionHasChildren',
  retention_not_feature_dataset: 'errors.retentionNotFeatureDataset',
  retention_referenced: 'errors.retentionReferenced',
  retention_unsupported_relation: 'errors.retentionUnsupportedRelation',
};

/**
 * A coded refusal detail: `{code, message, ...values}`, matching
 * `refusal_detail()` in `backend/app/core/upload_errors.py`.
 */
function uploadRefusalDescriptor(value: Record<string, unknown>): ApiErrorDescriptor | undefined {
  if (typeof value.code !== 'string') return undefined;
  const key = UPLOAD_REFUSAL_CODE_KEYS[value.code] ?? RETENTION_REFUSAL_CODE_KEYS[value.code];
  if (!key) return undefined;
  const { code: _code, message: _message, ...values } = value;
  return { key, values: values as TranslationValues };
}

/**
 * Detects a `SourceValidationError` array entry by its `source_id`+`code`
 * signature, which a Pydantic validation-error entry never has (it carries
 * `loc`/`type` instead). An entry that matches the shape but carries a code
 * this table doesn't know (a future VAL check) still returns a descriptor —
 * the generic `validationFailed` one — so it never falls through to
 * `validationDescriptor` and renders a raw key.
 */
function sourceValidationDescriptor(entry: unknown): ApiErrorDescriptor | undefined {
  if (!entry || typeof entry !== 'object') return undefined;
  const value = entry as Record<string, unknown>;
  if (typeof value.source_id !== 'string' || typeof value.code !== 'string') {
    return undefined;
  }
  const key = SOURCE_VALIDATION_CODE_KEYS[value.code];
  if (!key) return { key: 'errors.validationFailed' };
  return { key, values: { source: value.source_id } };
}

const STATUS_FALLBACK_KEYS: Record<number, ApiErrorDescriptor['key']> = {
  400: 'errors.badRequest',
  401: 'errors.unauthorized',
  403: 'errors.accessDenied',
  404: 'errors.resourceNotFound',
  408: 'errors.requestTimeout',
  409: 'errors.conflict',
  413: 'errors.payloadTooLarge',
  422: 'errors.validationFailed',
  429: 'errors.rateLimited',
};

function fallbackDescriptor(status: number): ApiErrorDescriptor {
  if (status >= 500) return { key: 'errors.serviceUnavailable' };
  return { key: STATUS_FALLBACK_KEYS[status] ?? 'errors.requestFailed' };
}

function formatInteger(raw: string): string {
  try {
    return new Intl.NumberFormat(i18n.language).format(BigInt(raw));
  } catch {
    // Preserve the server's digits if a future backend emits a non-integer.
    return raw;
  }
}

function descriptorForMessage(message: string, status: number): ApiErrorDescriptor {
  const exactKey = EXACT_ERROR_KEYS[message.trim()];
  if (exactKey) return { key: exactKey };

  const storageQuota = message.match(
    /^Storage quota exceeded:\s*used\s+(\d+)\s+of\s+(\d+)\s+bytes\s+\(adding\s+(\d+)\s+bytes\)$/i,
  );
  if (storageQuota) {
    return {
      key: 'errors.storageQuotaExceeded',
      values: {
        used: formatInteger(storageQuota[1]),
        limit: formatInteger(storageQuota[2]),
        adding: formatInteger(storageQuota[3]),
      },
    };
  }

  const datasetQuota = message.match(
    /^Dataset quota exceeded:\s*(\d+)\s+of\s+(\d+)\s+datasets used$/i,
  );
  if (datasetQuota) {
    return {
      key: 'errors.datasetQuotaExceeded',
      values: {
        used: formatInteger(datasetQuota[1]),
        limit: formatInteger(datasetQuota[2]),
      },
    };
  }

  // The analysis blast-radius refusals (mask cap, source caps) and the CORS
  // wildcard guard carry the limit and the way out in the server's prose.
  // Limits arrive comma-grouped from Python's `{n:,}`, so strip that before
  // re-formatting for the active locale. The operation name in the source-size
  // message is dropped: translating it would reach into the builder namespace.
  const sourceTooLarge = message.match(
    /^This dataset is too large for \w+ \(the limit is ([\d,]+) features?\)/i,
  );
  if (sourceTooLarge) {
    return {
      key: 'errors.analysisSourceTooLarge',
      values: { limit: formatInteger(sourceTooLarge[1].replace(/,/g, '')) },
    };
  }

  const maskTooLarge = message.match(
    /^The mask layer has too many features to clip with \(limit ([\d,]+)\)/i,
  );
  if (maskTooLarge) {
    return {
      key: 'errors.analysisMaskTooLarge',
      values: { limit: formatInteger(maskTooLarge[1].replace(/,/g, '')) },
    };
  }

  // The commit doors' srid_override refusal; the code the caller typed is the
  // whole message.
  const unknownSrid = message.match(
    /^srid_override (\d+) is not a known coordinate system/i,
  );
  if (unknownSrid) {
    return {
      key: 'errors.unknownSridOverride',
      values: { srid: unknownSrid[1] },
    };
  }

  // Anchored on the setting name and the first clause only: the server's
  // example origins are prose that may well be reworded.
  if (/^Validation error for 'cors_allowed_origins': Wildcard/i.test(message)) {
    return { key: 'errors.corsWildcardNotAllowed' };
  }

  // The embed domain-lock refusal. Its value is the remediation (which variable
  // to set), and both compose files default PUBLIC_APP_URL to localhost, so a
  // stock install hits it. The wording is a contract with
  // assert_domain_lock_is_enforceable (embed_tokens/service.py);
  // test_embed_domain_lock_self_origin_1531.py asserts the real message still matches.
  const domainLockUnenforceable = message.match(
    /^Domain locking cannot be enforced by this deployment: its public app URL resolves to (.+?), but this request reached it at (\S+)\./,
  );
  if (domainLockUnenforceable) {
    return {
      key: 'errors.embedDomainLockUnenforceable',
      values: {
        resolved: domainLockUnenforceable[1],
        origin: domainLockUnenforceable[2],
      },
    };
  }

  // The refresh door's SSRF refusal appends the validator's exception text
  // (resolved IP, blocked range), which a non-admin shouldn't see. Anchored on
  // the fixed prefix; the STAC door words the same refusal around its item URL.
  if (/^This dataset's stored (?:source URL|STAC item URL) is not reachable:/i.test(message)) {
    return { key: 'errors.refreshSourceUrlBlocked' };
  }

  // The four analysis 4xx literals not covered above. The 429 is the user's own
  // job holding the one-per-user slot, not generic rate-limit advice.
  if (/^An analysis job is already running/i.test(message)) {
    return { key: 'errors.analysisJobAlreadyRunning' };
  }
  if (/^Analysis requires a vector dataset/i.test(message)) {
    return { key: 'errors.analysisVectorRequired' };
  }
  if (/^mask_dataset_id must reference a polygon dataset/i.test(message)) {
    return { key: 'errors.analysisMaskPolygonRequired' };
  }
  const unknownDissolveColumn = message.match(
    /^Unknown dissolve column: '(.+)'$/i,
  );
  if (unknownDissolveColumn) {
    return {
      key: 'errors.analysisUnknownDissolveColumn',
      values: { column: unknownDissolveColumn[1] },
    };
  }

  // The backend names the offending maps so a human can fix them. `s` (dotAll)
  // because a map name may contain a newline; `$` is dropped so a trailing
  // newline can't truncate the list.
  const strandedMaps = message.match(
    /^Cannot restrict visibility: dataset is used in shared maps:\s*([\s\S]+)/i,
  );
  if (strandedMaps) {
    return {
      key: 'errors.datasetVisibilityBlockedByMaps',
      values: { maps: strandedMaps[1] },
    };
  }

  return fallbackDescriptor(status);
}

function fieldFromLocation(location: unknown): string | undefined {
  if (!Array.isArray(location)) return undefined;
  const parts = location
    .filter((part): part is string | number =>
      typeof part === 'string' || typeof part === 'number',
    )
    .filter((part) => !['body', 'query', 'path', 'header'].includes(String(part)));
  if (parts.length === 0) return undefined;
  // Preserve schema identifiers verbatim; they are useful context and are not
  // backend prose. Translating an identifier would make it harder to find the
  // corresponding field in an API payload or form report.
  return parts.map(String).join('.');
}

function contextValue(context: unknown, key: string): string | number | undefined {
  if (!context || typeof context !== 'object' || !(key in context)) return undefined;
  const value = (context as Record<string, unknown>)[key];
  return typeof value === 'string' || typeof value === 'number' ? value : undefined;
}

function validationDescriptor(entry: unknown): ApiErrorDescriptor | undefined {
  if (!entry || typeof entry !== 'object') return undefined;
  const value = entry as Record<string, unknown>;
  const type = typeof value.type === 'string' ? value.type : '';
  const field = fieldFromLocation(value.loc);
  if (!field) return { key: 'errors.validationFailed' };

  if (type === 'missing') {
    return { key: 'errors.validationRequired', values: { field } };
  }
  if (type === 'string_too_short') {
    const limit = contextValue(value.ctx, 'min_length');
    return limit === undefined
      ? { key: 'errors.validationInvalidField', values: { field } }
      : { key: 'errors.validationMinLength', values: { field, limit } };
  }
  if (type === 'string_too_long') {
    const limit = contextValue(value.ctx, 'max_length');
    return limit === undefined
      ? { key: 'errors.validationInvalidField', values: { field } }
      : { key: 'errors.validationMaxLength', values: { field, limit } };
  }

  const comparisonKeys: Record<string, [ApiErrorDescriptor['key'], string]> = {
    greater_than: ['errors.validationGreaterThan', 'gt'],
    greater_than_equal: ['errors.validationGreaterThanOrEqual', 'ge'],
    less_than: ['errors.validationLessThan', 'lt'],
    less_than_equal: ['errors.validationLessThanOrEqual', 'le'],
  };
  const comparison = comparisonKeys[type];
  if (comparison) {
    const limit = contextValue(value.ctx, comparison[1]);
    if (limit !== undefined) {
      return { key: comparison[0], values: { field, limit } };
    }
  }

  if (type === 'literal_error' || type === 'enum') {
    return { key: 'errors.validationInvalidChoice', values: { field } };
  }
  // pydantic's own HttpUrl parsing inside a field validator (STAC's
  // `_validate_stac_http_url`, among others) yields pydantic-core's error type
  // rather than `value_error`; without this branch the URL scheme problem is hidden.
  if (type === 'url_scheme') {
    return { key: 'errors.validationUrlSchemeInvalid', values: { field } };
  }
  return { key: 'errors.validationInvalidField', values: { field } };
}

/**
 * Classify any FastAPI `detail` payload without using server prose as display
 * text. This supports plain strings, RFC 7807 objects, custom structured
 * details, and FastAPI/Pydantic validation arrays.
 */
export function classifyApiError(detail: unknown, status = 0): ApiErrorDescriptor {
  if (typeof detail === 'string') return descriptorForMessage(detail, status);

  if (Array.isArray(detail)) {
    for (const entry of detail) {
      const descriptor = sourceValidationDescriptor(entry) ?? validationDescriptor(entry);
      if (descriptor) return descriptor;
    }
    return fallbackDescriptor(status);
  }

  if (detail && typeof detail === 'object') {
    const value = detail as Record<string, unknown>;
    // The workflow seam names the refused edge and the steps this actor may
    // take instead as fields, so a stage name can hold any text.
    if (
      value.code === 'workflow_transition_denied' &&
      typeof value.current_stage === 'string' &&
      typeof value.requested_stage === 'string'
    ) {
      const values = { from: value.current_stage, to: value.requested_stage };
      const allowed = Array.isArray(value.allowed_stages)
        ? value.allowed_stages.filter((stage): stage is string => typeof stage === 'string')
        : [];
      return allowed.length > 0
        ? {
            key: 'errors.workflowTransitionDenied',
            values: { ...values, allowed: allowed.join(', ') },
          }
        : { key: 'errors.workflowTransitionDeniedNoneAllowed', values };
    }
    if (value.code === 'duplicate_source') {
      return {
        key: 'errors.duplicateSource',
        values: {
          title:
            typeof value.existing_title === 'string'
              ? value.existing_title
              : i18n.t('common:notAvailable'),
        },
      };
    }
    // invalid_service_token's message is the token policy, whose allowed alphabet
    // varies by service type, so it can't be a static key; interpolating server
    // prose mirrors duplicate_source below.
    if (value.code === 'invalid_service_token' && typeof value.message === 'string') {
      return {
        key: 'errors.refreshInvalidServiceToken',
        values: { message: value.message },
      };
    }
    // POST /services/arcgis/signin/ refusals. arcgis_signin_rejected collapses
    // "wrong password" and "account locked" so the form can't be an oracle for
    // whether a colleague's ArcGIS account exists. arcgis_sso_account is the one
    // exception: federated identity or MFA is unfixable by retry, so it points at
    // the paste-a-token path.
    if (value.code === 'login_throttled') {
      return { key: 'errors.loginThrottled' };
    }
    if (value.code === 'device_trust_link_invalid') {
      return { key: 'errors.deviceTrustLinkInvalid' };
    }
    if (value.code === 'device_trust_browser_full') {
      return { key: 'errors.deviceTrustBrowserFull' };
    }
    if (value.code === 'device_trust_unavailable') {
      return { key: 'errors.deviceTrustUnavailable' };
    }
    if (value.code === 'arcgis_signin_rejected') {
      return { key: 'errors.arcgisSigninRejected' };
    }
    if (value.code === 'arcgis_sso_account') {
      return { key: 'errors.arcgisSsoAccount' };
    }
    if (value.code === 'ssrf_refused') {
      return { key: 'errors.arcgisPortalUnreachable' };
    }
    if (value.code === 'network_error') {
      return { key: 'errors.couldNotReachService' };
    }
    // arcgis_signin_in_progress is a 409 for a sign-in already running for that
    // account. The attempt-count 429 is left unmapped: it falls to the generic 429
    // status key.
    if (value.code === 'arcgis_signin_in_progress') {
      return { key: 'errors.arcgisSigninInProgress' };
    }
    // arcgis_portal_not_https is a structured {code, message, field} 422, not the
    // list-shaped one `validationDescriptor` handles, so it is checked here.
    if (value.code === 'arcgis_portal_not_https') {
      return { key: 'errors.arcgisPortalNotHttps' };
    }
    if (value.code === 'credential_over_http') {
      return { key: 'errors.credentialOverHttp' };
    }
    // arcgis_portal_host_invalid (sources/arcgis_signin.py HOST_INVALID): a 422 for
    // a portal hostname that can't be canonicalized; same shape as above.
    if (value.code === 'arcgis_portal_host_invalid') {
      return { key: 'errors.arcgisPortalHostInvalid' };
    }
    if (Array.isArray(value.unknown_layers) && value.unknown_layers.length > 0) {
      return {
        key: 'errors.unknownLayers',
        values: { layers: value.unknown_layers.map(String).join(', ') },
      };
    }

    // Keyed on the code so rewording the server's sentence can't surface raw English.
    if (value.code === 'geometry_loss') {
      return { key: 'errors.reuploadGeometryLoss' };
    }

    // service_token_required's body is an English diagnostic for API clients.
    // SourceRefreshAction.tsx intercepts the code first; this keeps the mapping
    // correct for any other caller of `classifyApiError`.
    if (value.code === 'service_token_required') {
      return { key: 'errors.refreshServiceTokenRequired' };
    }

    // Checked after the specific codes so it never shadows one; `geometry_loss`
    // wins first.
    const uploadRefusal = uploadRefusalDescriptor(value);
    if (uploadRefusal) return uploadRefusal;

    if (typeof value.message === 'string') {
      return descriptorForMessage(value.message, status);
    }
    const validation = validationDescriptor(value);
    if (validation) return validation;
  }

  return fallbackDescriptor(status);
}

export function translateApiErrorDetail(detail: unknown, status = 0): string {
  const descriptor = classifyApiError(detail, status);
  return i18n.t(descriptor.key, {
    ns: 'common',
    ...(descriptor.values ?? {}),
  }) as string;
}

/** The statuses describeUploadRefusal treats as a real refusal, each mapped to its generic fallback key. */
export const UPLOAD_REFUSAL_FALLBACK_KEYS: Record<number, ApiErrorDescriptor['key']> = {
  400: 'errors.badRequest',
  422: 'errors.validationFailed',
};

/**
 * Like translateApiErrorDetail, except that a 400 or 422 whose string detail
 * the table doesn't recognize is returned as the server wrote it. Arrays,
 * objects and recognized strings translate as usual.
 */
export function describeUploadRefusal(detail: unknown, status: number): string {
  const descriptor = classifyApiError(detail, status);
  if (typeof detail === 'string' && descriptor.key === UPLOAD_REFUSAL_FALLBACK_KEYS[status]) {
    return detail;
  }
  return i18n.t(descriptor.key, {
    ns: 'common',
    ...(descriptor.values ?? {}),
  }) as string;
}

/**
 * Compose a mutation's error toast: a translated fallback, plus the already
 * localized message carried by ApiError/Error when one exists.
 */
export function formatMutationError(fallbackKey: string, err: unknown): string {
  const base = i18n.t(fallbackKey) as string;
  if (err instanceof Error && err.message) {
    return `${base}: ${err.message}`;
  }
  return base;
}
