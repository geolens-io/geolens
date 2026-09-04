import i18n from '@/i18n/i18n';

type TranslationValues = Record<string, string | number>;

export interface ApiErrorDescriptor {
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
  // fix(#1746): the ArcGIS-specific wording of the same auth-required refusal
  // (ArcGISTokenError path in backend/app/modules/catalog/sources/router.py)
  // was unmapped and fell through to the generic 403 "Access denied", hiding
  // that a token was the fix.
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
  // fix(#790): the sandbox advisory lock (geolens:ai-sql:<user>) is SHARED
  // between analysis previews and AI chat data queries — one expensive read
  // per user across both, deliberately. Unmapped this 429 collapsed to the
  // generic rateLimited fallback, so a busy chat query refused an analysis
  // preview with no hint that another feature was holding the budget. The
  // locale copy names both sides, because either can be the holder.
  'Another data query is already running for this user': 'errors.sharedQueryBusy',
  // fix(#1285): the refresh door's refusal taxonomy (backend
  // router_refresh.py). Each literal below is stable, considered UX copy on
  // the backend side rather than diagnostic prose, so mapping by exact text
  // follows the table's existing convention. Distinct wordings that describe
  // the SAME taxonomy state (a service vs. a postgis dataset both missing
  // enough of their binding, for example) collapse to one key on purpose —
  // the Source panel renders one message per code, not per call site.
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
  "This dataset's source changed while the refresh was being queued, so it was not started. Check the new source and try again.":
    'errors.refreshOriginChanged',
  // fix(#1768): the re-upload commit door's own `origin_changed`. Same code,
  // different literal and a different key, because the two refusals describe
  // different windows: the refresh one is "between your click and the queue",
  // this one is "between the upload you staged and the commit you just
  // confirmed", and the action it asks for is to look at the source before
  // replacing anything, not to retry.
  "This dataset's source changed after this replacement was staged, so nothing was queued. Re-check the dataset's source and start the replacement again.":
    'errors.reuploadOriginChanged',
  'This dataset is backed by a registered table in this instance, which needs no service credential. Send the request without a token.':
    'errors.refreshCredentialNotApplicable',
  // fix(#1332): the STAC door's wordings of the same taxonomy states,
  // introduced by #1326 after this table was written.
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

// fix(#1390): the VRT source-compatibility 422 (`validate_sources` in
// backend/app/processing/raster/validation.py) returns an array of
// SourceValidationError objects (source_id/code/message/field/severity) —
// a different shape from the Pydantic loc/type/ctx array `validationDescriptor`
// below expects, so every VAL code fell through to the generic
// `errors.validationFailed` string. Keyed by the backend's stable `code`
// literal, mirroring the refresh-refusal taxonomy convention (#1285/#1332)
// of one user-facing key per backend code rather than per call site.
const SOURCE_VALIDATION_CODE_KEYS: Record<string, ApiErrorDescriptor['key']> = {
  crs_mismatch: 'errors.sourceValidationCrsMismatch', // VAL-01
  band_count_mismatch: 'errors.sourceValidationBandCountMismatch', // VAL-02
  single_band_required: 'errors.sourceValidationSingleBandRequired', // VAL-03
  dtype_mismatch: 'errors.sourceValidationDtypeMismatch', // VAL-04
  grid_misaligned: 'errors.sourceValidationGridMisaligned', // VAL-05
  nodata_inconsistent: 'errors.sourceValidationNodataInconsistent', // VAL-06
  rotated_raster: 'errors.sourceValidationRotatedRaster', // VAL-07
  unknown_pixel_geometry: 'errors.sourceValidationUnknownPixelGeometry', // VAL-08
};

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

  // The analysis blast-radius refusals (#693 mask cap, #694/#701 source caps)
  // and the CORS wildcard guard (#689) put the whole point of those changes in
  // the server's prose: the limit, and the way out. Unmapped they collapse to
  // the generic 422 string, so the user is told their input is invalid with no
  // hint that size is the problem. The limits arrive comma-grouped from
  // Python's `{n:,}`, so strip that before re-formatting for the active locale.
  // fix(#718): the operation name in the source-size message is deliberately
  // dropped rather than interpolated — translating it would mean reaching into
  // the builder namespace from here, and the user just picked the operation.
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

  // Anchored on the setting name and the first clause only: the server's
  // example origins are prose that may well be reworded.
  if (/^Validation error for 'cors_allowed_origins': Wildcard/i.test(message)) {
    return { key: 'errors.corsWildcardNotAllowed' };
  }

  // fix(#1548 review P2): the embed domain-lock refusal. Its whole value is the
  // remediation — which variable to set, and to what — and both compose files
  // ship PUBLIC_APP_URL defaulted to localhost, so this is the message an
  // operator hits on a stock install. Unmapped it collapses to the generic 422
  // and the domain lock goes back to failing silently, which is the bug the
  // refusal exists to surface. The wording is a contract with
  // assert_domain_lock_is_enforceable in backend/app/modules/embed_tokens/
  // service.py; backend/tests/test_embed_domain_lock_self_origin_1531.py reads
  // this matcher and asserts the real message still matches it.
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

  // fix(#1285): the refresh door's SSRF refusal appends the validator's own
  // exception text after the colon, which is diagnostic detail (resolved IP,
  // blocked range) rather than something a non-admin reader should see.
  // Anchored on the fixed prefix only; the dynamic suffix is dropped.
  // fix(#1332): the STAC door words the same refusal around its item URL.
  if (/^This dataset's stored (?:source URL|STAC item URL) is not reachable:/i.test(message)) {
    return { key: 'errors.refreshSourceUrlBlocked' };
  }

  // fix(#774): the four analysis 4xx literals #718 didn't map. Without these
  // the 429 collapsed to generic rate-limit advice (wrong — it is the user's
  // OWN job holding the one-per-user slot) and the three 422s to "values are
  // invalid".
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

  // fix(#931): the backend names the offending maps precisely so a human can go
  // and fix them, and unmapped that list fell through to the generic 422 —
  // which drops exactly the part that makes the refusal actionable.
  // fix(#931 codex r5): `s` (dotAll) because a map name may legally contain a
  // newline — `MapCreate.name` is length-bounded and NFC-normalized, nothing
  // more — and without it `.` stops at the line terminator, the match fails,
  // and the actionable map list collapses to the generic 422. `$` is dropped
  // for the same reason: with `m` absent it anchors at the end of input, but
  // the trailing-newline allowance would still truncate.
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
    // fix(#1285): invalid_service_token's message is the token POLICY, not
    // the token — the backend names the allowed alphabet dynamically per
    // service type (base64url vs. the wider ArcGIS query-param vocabulary),
    // so it can't be a static key the way the other refresh refusals are.
    // Interpolating server prose here mirrors the existing duplicate_source
    // precedent below.
    if (value.code === 'invalid_service_token' && typeof value.message === 'string') {
      return {
        key: 'errors.refreshInvalidServiceToken',
        values: { message: value.message },
      };
    }
    // fix(service-auth wave, lane A2): POST /services/arcgis/signin/'s own
    // refusal taxonomy (plan 2026-09-01-service-auth-PLAN.md section 3.2).
    // arcgis_signin_rejected deliberately collapses "wrong password" and
    // "account locked" into one message. Telling the caller which of the
    // two happened would let a GeoLens user use this form as an oracle for
    // whether a colleague's ArcGIS account exists and is being guessed at.
    // arcgis_sso_account is the one deliberate exception: it names a real,
    // unfixable-by-retry cause (federated identity or MFA) and points at the
    // paste-a-token path, because collapsing it would leave that class of
    // user with an unexplainable rejection and no way forward. ssrf_refused
    // reuses the same code name a later probe-reason-code door (plan 3.6,
    // not built yet) may also emit; if that lands with different intended
    // copy for the same code, reconcile then rather than here.
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
    // fix(service-auth wave, lane A1 contract update, head 85c5fc282):
    // arcgis_signin_in_progress is a 409 for one ArcGIS sign-in already
    // running for that account. A real 429 rate_limited still happens
    // separately, from the attempt-count limiter (keyed on the ArcGIS
    // account itself, shared across every GeoLens user, plus a second
    // count per GeoLens user and portal); it is deliberately left
    // unmapped here, since the object branch falls through to its
    // message and then to the generic 429 status key, so a wording
    // change on that message needs no update in this file.
    if (value.code === 'arcgis_signin_in_progress') {
      return { key: 'errors.arcgisSigninInProgress' };
    }
    // arcgis_portal_not_https arrives as a 422 with this SAME structured
    // {code, message, field} shape, not FastAPI's list-shaped validation
    // 422 handled by validationDescriptor below, so it has to be checked
    // here rather than there.
    if (value.code === 'arcgis_portal_not_https') {
      return { key: 'errors.arcgisPortalNotHttps' };
    }
    // fix(service-auth wave, post-merge rebase onto #1758): arcgis_portal_host_invalid
    // is the sixth and last caller-facing code this endpoint returns
    // (backend/app/modules/catalog/sources/arcgis_signin.py, HOST_INVALID),
    // a 422 for a portal hostname that cannot be canonicalized. Same
    // structured-422 reasoning as arcgis_portal_not_https above, and same
    // field: 'url' anchor.
    if (value.code === 'arcgis_portal_host_invalid') {
      return { key: 'errors.arcgisPortalHostInvalid' };
    }
    if (Array.isArray(value.unknown_layers) && value.unknown_layers.length > 0) {
      return {
        key: 'errors.unknownLayers',
        values: { layers: value.unknown_layers.map(String).join(', ') },
      };
    }

    // --- Lane A3 (service-auth wave, #1755 item 4): appended as its own
    // block, ahead of the generic string-message fallback below rather than
    // interleaved with the codes above, so this merges cleanly onto lane
    // A2's changes elsewhere in this function. `service_token_required`'s
    // body carries an English diagnostic sentence aimed at an API client;
    // `SourceRefreshAction.tsx` intercepts the code before this module ever
    // sees it and renders its own inline credential prompt instead, but this
    // entry keeps the mapping correct for any other caller of
    // `classifyApiError` that reaches this code without that special case.
    if (value.code === 'service_token_required') {
      return { key: 'errors.refreshServiceTokenRequired' };
    }

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

/** Compatibility helper for call sites that already reduced detail to text. */
export function translateError(backendMessage: string, status = 0): string {
  return translateApiErrorDetail(backendMessage, status);
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
