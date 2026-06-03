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
 */
export function translateError(backendMessage: string): string {
  const key = ERROR_MAP[backendMessage];
  if (!key) return backendMessage;
  return i18n.t(key, { ns: 'common', defaultValue: backendMessage });
}
