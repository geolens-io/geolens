import i18n from '@/i18n/i18n';

/**
 * Maps backend API error detail strings to i18n translation keys
 * in the 'common' namespace under the 'errors' group.
 */
const ERROR_MAP: Record<string, string> = {
  'Dataset not found': 'errors.datasetNotFound',
  'Collection not found': 'errors.collectionNotFound',
  'Map not found': 'errors.mapNotFound',
  'Incorrect username or password': 'errors.incorrectCredentials',
  'Your account is awaiting approval': 'errors.awaitingApproval',
  'Account not active': 'errors.accountNotActive',
  'Insufficient permissions': 'errors.insufficientPermissions',
  'Not authorized to modify this map': 'errors.notAuthorized',
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
  'Saved search not found': 'errors.savedSearchNotFound',
  'Record not found': 'errors.recordNotFound',
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
  'Invalid target_crs: must match EPSG:<code> (e.g. EPSG:3857)': 'errors.invalidTargetCrs',
  'Staging file no longer available. Please re-upload.': 'errors.stagingFileUnavailable',
  'This service requires authentication. Provide an access token and try again.': 'errors.serviceRequiresAuth',
  'Could not reach the service. Check the URL and try again.': 'errors.couldNotReachService',
  "Service didn't respond in time. Check the URL and try again.": 'errors.serviceTimeout',
  'Remote service returned an error': 'errors.remoteServiceError',
  'AI features are currently disabled': 'errors.aiDisabled',
  'AI is not configured (missing API key)': 'errors.aiNotConfigured',
  'AI map generation failed unexpectedly': 'errors.aiGenerationFailed',
  'Chat map editing failed unexpectedly': 'errors.chatEditingFailed',
  'Could not connect to LLM provider': 'errors.couldNotConnectLlm',
  'An unexpected error occurred during upload': 'errors.uploadError',
  'An unexpected error occurred while previewing the layer.': 'errors.previewError',
  'Failed to preview remote layer. The service may be unavailable or the layer format is unsupported.': 'errors.remotePreviewError',
  'Dataset membership not found': 'errors.datasetMembershipNotFound',
  'This shared map link has expired or been revoked': 'errors.sharedMapExpired',
};

/**
 * Translates a backend error message to the user's current locale.
 *
 * Looks up the exact backend string in ERROR_MAP. If found, returns the
 * translated string via i18n.t(). If not found (unmapped or dynamic error),
 * returns the original English message unchanged (ERR-02 fallback).
 *
 * Quota errors (QUOTA-01/02) are dynamic (they include usage numbers), so
 * they are not in ERROR_MAP. They are passed through verbatim here because
 * the backend detail string is already readable English prose (e.g.
 * "Storage quota exceeded: used 5 MB of 1 MB (adding 100 bytes)"). If i18n
 * translations for quota strings are added in the future, add prefix-match
 * entries here (startsWith checks) before the exact-key lookup.
 */
export function translateError(backendMessage: string): string {
  // Prefix match for dynamic quota messages — backend detail is already
  // human-readable English with usage numbers (QUOTA-01/02 error shape).
  // Pass through verbatim so the user sees the exact numbers.
  if (backendMessage.startsWith('Storage quota exceeded')) {
    return backendMessage;
  }
  if (backendMessage.startsWith('Dataset quota exceeded')) {
    return backendMessage;
  }

  const key = ERROR_MAP[backendMessage];
  if (!key) return backendMessage;
  return i18n.t(key, { ns: 'common', defaultValue: backendMessage });
}

/**
 * Reduce a FastAPI `detail` payload to one human-readable line.
 *
 * fix(#435): UX-03 — seven call sites used to do
 * `typeof detail === 'string' ? detail : JSON.stringify(detail)`, so any
 * unintercepted 422 put a raw array of Pydantic error objects into a toast:
 * `[{"type":"missing","loc":["body","name"],"msg":"Field required",...}]`.
 *
 * FastAPI's validation shape is `detail: [{loc, msg, type, input}]`. We take the
 * first entry's `msg`. A bare object with a `msg` is handled too. Anything else
 * falls back to the caller's status text rather than leaking JSON.
 */
export function summarizeErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;

  const msgOf = (v: unknown): string | undefined => {
    if (v && typeof v === 'object' && 'msg' in v) {
      const msg = (v as { msg: unknown }).msg;
      if (typeof msg === 'string' && msg.length > 0) return msg;
    }
    return undefined;
  };

  if (Array.isArray(detail)) {
    for (const entry of detail) {
      const msg = msgOf(entry);
      if (msg) return msg;
    }
    return fallback;
  }

  return msgOf(detail) ?? fallback;
}

/**
 * Compose a mutation's error toast: a translated fallback, plus the backend's
 * specific reason when there is one.
 *
 * fix(#435): UX-07 — promoted out of `use-settings.ts`. Five mutations toasted
 * from the hook *and* from the caller, so a failed delete raised two toasts.
 * The hook is the right owner (it fires on every caller), but the callers were
 * the ones passing `err.message` through. This helper lets the hook do both, so
 * the caller-side toast can go away without losing the specific message.
 *
 * `ApiError.message` is already the translated backend `detail`, and `ApiError`
 * extends `Error`, so one branch covers both.
 */
export function formatMutationError(fallbackKey: string, err: unknown): string {
  const base = i18n.t(fallbackKey) as string;
  if (err instanceof Error && err.message) {
    return `${base}: ${err.message}`;
  }
  return base;
}
