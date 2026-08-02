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
};

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
      const descriptor = validationDescriptor(entry);
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
    if (Array.isArray(value.unknown_layers) && value.unknown_layers.length > 0) {
      return {
        key: 'errors.unknownLayers',
        values: { layers: value.unknown_layers.map(String).join(', ') },
      };
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
