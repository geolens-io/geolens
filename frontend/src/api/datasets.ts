import { API_BASE } from '@/lib/constants';
import { translateApiErrorDetail } from '@/lib/error-map';
import i18n from '@/i18n/i18n';
import { apiFetch, authenticatedRawFetch, ApiError } from './client';
import { uploadChunks } from './_presignedUpload';
import { rethrowAsUploadRefusal } from './ingest';
import { triggerDownload } from '@/lib/download';
import { pushReportEntry, reportNetworkError } from '@/lib/report';
import type {
  CreateDatasetRequest,
  DatasetOrigin,
  DatasetResponse,
  DatasetRowsResponse,
  DatasetUpdateRequest,
  DatasetRetention,
  DatasetRetentionResponse,
  AuditLogListResponse,
  ReuploadResponse,
  ReuploadServicePreviewRequest,
  ReuploadPreviewResponse,
  ReuploadCommitRequest,
  ReuploadCommitResponse,
  DatasetVersionListResponse,
  DatasetRefreshRequest,
  DatasetRefreshResponse,
  DatasetRefreshRunListResponse,
  RestorePreviousVersionResponse,
  AttributeMetadataListResponse,
  AttributeMetadataResponse,
  AttributeMetadataUpdate,
  ValidationResultResponse,
  PresignedUploadResponse,
  UploadResponse,
  StatusUpdateResponse,
  ServiceAuthRequest,
  DatasetRelationship,
  DatasetRelationshipListResponse,
  ApiKeyCreateResponse,
  DatasetApiKeyCreateRequest,
  DatasetApiKeyResponse,
} from '@/types/api';

export async function createDataset(data: CreateDatasetRequest): Promise<DatasetResponse> {
  return apiFetch<DatasetResponse>('/datasets/create/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getDataset(id: string): Promise<DatasetResponse> {
  return apiFetch<DatasetResponse>(`/datasets/${encodeURIComponent(id)}`);
}

export interface DatasetRowsSort {
  column: string;
  desc: boolean;
}

export async function getDatasetRows(
  id: string,
  params: {
    limit?: number;
    after?: number;
    filters?: Record<string, string>;
    sort?: DatasetRowsSort;
  } = {},
): Promise<DatasetRowsResponse> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.after !== undefined) query.set('after', String(params.after));
  if (params.sort) {
    query.set('sort', params.sort.column);
    query.set('order', params.sort.desc ? 'desc' : 'asc');
  }
  if (params.filters) {
    for (const [col, value] of Object.entries(params.filters)) {
      if (value) query.set(`filter[${col}]`, value);
    }
  }
  const qs = query.toString();
  return apiFetch<DatasetRowsResponse>(`/datasets/${encodeURIComponent(id)}/rows/${qs ? `?${qs}` : ''}`);
}

function getExportUrl(
  id: string,
  format: string,
  options: { target_crs?: string; bbox?: string; where?: string } = {},
): string {
  const query = new URLSearchParams({ format });
  if (options.target_crs) query.set('target_crs', options.target_crs);
  if (options.bbox) query.set('bbox', options.bbox);
  if (options.where) query.set('where', options.where);
  return `${API_BASE}/datasets/${encodeURIComponent(id)}/export?${query.toString()}`;
}

/** Path for the COG download endpoint. Centralised so `/download/cog` lives in one place. */
export function getCogDownloadUrl(id: string): string {
  return `${API_BASE}/datasets/${encodeURIComponent(id)}/download/cog`;
}

// Exported so any same-origin GeoLens API resource can be downloaded through
// the refresh-aware, bearer-authenticated flow: a plain <a href> navigation
// carries no Authorization header, so a private dataset's export rejects it.
export async function authenticatedDownload(
  url: string,
  filename: string,
  signal?: AbortSignal,
): Promise<void> {
  // Refresh-aware raw fetch so a download issued as the first request after a
  // long idle transparently refreshes the JWT instead of 401-ing.
  const response = await authenticatedRawFetch(url, { signal });

  if (!response.ok) {
    let detail: unknown;
    try {
      const body = await response.json();
      detail = body.detail;
    } catch {
      // Non-JSON failures use the localized status category below.
    }
    throw new Error(translateApiErrorDetail(detail, response.status));
  }

  const blob = await response.blob();
  triggerDownload(blob, filename);
}

export async function downloadExport(
  id: string,
  format: string,
  filename: string,
): Promise<void> {
  return authenticatedDownload(getExportUrl(id, format), filename);
}

/**
 * Mint a short-lived download-scoped JWT for a single dataset.
 *
 * The COG download URL requires a typ='download' JWT on ?token=; the backend
 * rejects session JWTs there. This helper calls POST /auth/download-token/{id}
 * to obtain the right token.
 */
async function mintDownloadToken(id: string): Promise<string> {
  const data = await apiFetch<{ token: string; expires_in: number }>(
    `/auth/download-token/${encodeURIComponent(id)}`,
    { method: 'POST' }
  );
  return data.token;
}

/**
 * Open the COG download URL in a new tab.
 *
 * Mints a fresh download token first — never places the session JWT on the URL.
 * Callers must handle errors (e.g. via toast.error) since this is async.
 */
export async function downloadCog(id: string): Promise<void> {
  const downloadToken = await mintDownloadToken(id);
  const url = new URL(`${API_BASE}/datasets/${encodeURIComponent(id)}/download/cog`, window.location.origin);
  url.searchParams.set('token', downloadToken);
  window.open(url.toString(), '_blank');
}

export async function updateDataset(
  id: string,
  data: DatasetUpdateRequest,
): Promise<DatasetResponse> {
  return apiFetch<DatasetResponse>(`/datasets/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

/** Set or clear (null) a feature dataset's retention; a dry run only counts the rows it would delete. */
export async function setDatasetRetention(
  id: string,
  retention: DatasetRetention | null,
  { dryRun = false }: { dryRun?: boolean } = {},
): Promise<DatasetRetentionResponse> {
  const query = dryRun ? '?dry_run=true' : '';
  return apiFetch<DatasetRetentionResponse>(`/datasets/${encodeURIComponent(id)}/retention/${query}`, {
    method: 'PUT',
    body: JSON.stringify({ retention }),
  });
}

/** Walk the full transition chain server-side in a single request.
 *  This target-status endpoint is the only publication-status transition
 *  the app uses. */
export async function setTargetStatus(
  id: string,
  status: string,
): Promise<StatusUpdateResponse> {
  return apiFetch<StatusUpdateResponse>(`/datasets/${encodeURIComponent(id)}/target-status/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
}

export async function deleteDataset(
  id: string,
  confirmName: string,
): Promise<void> {
  await apiFetch(`/datasets/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirm_title: confirmName }),
  });
}

export async function getDatasetHistory(
  id: string,
  params: { skip?: number; limit?: number } = {},
): Promise<AuditLogListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch<AuditLogListResponse>(`/datasets/${encodeURIComponent(id)}/history${qs ? `?${qs}` : ''}`);
}

// apiFetch's 30s default would abort a large (up to 500 MB) re-upload body
// before the transfer completes, losing the staged job. This timeout holds the
// request open and outlives the edge proxy deliberately.
const REUPLOAD_TIMEOUT_MS = 630_000;

export async function reuploadDataset(
  datasetId: string,
  file: File,
): Promise<ReuploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  try {
    return await apiFetch<ReuploadResponse>(`/datasets/${encodeURIComponent(datasetId)}/reupload`, {
      method: 'POST',
      body: formData,
      timeoutMs: REUPLOAD_TIMEOUT_MS,
    });
  } catch (err) {
    rethrowAsUploadRefusal(err);
  }
}

export async function reuploadPreview(
  datasetId: string,
  jobId: string,
  // Layer to preview for multi-layer file sources.
  layerName?: string,
): Promise<ReuploadPreviewResponse> {
  const body = layerName !== undefined ? JSON.stringify({ layer_name: layerName }) : undefined;
  try {
    return await apiFetch<ReuploadPreviewResponse>(`/datasets/${encodeURIComponent(datasetId)}/reupload/${encodeURIComponent(jobId)}/preview`, {
      method: 'POST',
      ...(body ? { body } : {}),
    });
  } catch (err) {
    rethrowAsUploadRefusal(err);
  }
}

export async function reuploadServicePreview(
  datasetId: string,
  request: ReuploadServicePreviewRequest,
): Promise<ReuploadPreviewResponse> {
  try {
    return await apiFetch<ReuploadPreviewResponse>(`/datasets/${encodeURIComponent(datasetId)}/reupload/service/preview`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
  } catch (err) {
    rethrowAsUploadRefusal(err);
  }
}

export async function reuploadCommit(
  datasetId: string,
  jobId: string,
  sridOverride?: number | null,
  token?: string,
  // User-chosen layer for multi-layer GPKG files.
  layerName?: string,
  // The dataset origin the dialog saw when it staged this replacement. The commit
  // door refuses with 409 `origin_changed` if the dataset was rebound to a
  // service, STAC or registered-table source meanwhile. Omitting it skips the check.
  expectedOriginKind?: DatasetOrigin | null,
  // The preview's fingerprint of the changes the person was shown. Without
  // it a replacement that needs review ends blocked.
  reviewFingerprint?: string | null,
): Promise<ReuploadCommitResponse> {
  const payload: ReuploadCommitRequest = {
    srid_override: sridOverride ?? null,
    ...(token ? { token } : {}),
    ...(layerName !== undefined ? { layer_name: layerName } : {}),
    ...(expectedOriginKind ? { expected_origin_kind: expectedOriginKind } : {}),
    ...(reviewFingerprint ? { review_fingerprint: reviewFingerprint } : {}),
  };

  try {
    return await apiFetch<ReuploadCommitResponse>(`/datasets/${encodeURIComponent(datasetId)}/reupload/${encodeURIComponent(jobId)}/commit`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  } catch (err) {
    rethrowAsUploadRefusal(err);
  }
}

export async function addColumn(
  datasetId: string,
  column: { name: string; type: string },
): Promise<{ columns: { name: string; type: string }[] }> {
  return apiFetch<{ columns: { name: string; type: string }[] }>(
    `/layers/${encodeURIComponent(datasetId)}/columns/`,
    {
      method: 'POST',
      body: JSON.stringify({ column }),
    },
  );
}

export async function dropColumn(
  datasetId: string,
  columnName: string,
): Promise<{ columns: { name: string; type: string }[] }> {
  return apiFetch<{ columns: { name: string; type: string }[] }>(
    `/layers/${encodeURIComponent(datasetId)}/columns/${encodeURIComponent(columnName)}`,
    {
      method: 'DELETE',
    },
  );
}

export async function getColumnReferences(
  datasetId: string,
  columnName: string,
): Promise<{ map_count: number }> {
  return apiFetch<{ map_count: number }>(
    `/layers/${encodeURIComponent(datasetId)}/columns/${encodeURIComponent(columnName)}/references`,
  );
}

export async function getDatasetVersions(
  datasetId: string,
  params: { skip?: number; limit?: number } = {},
): Promise<DatasetVersionListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch<DatasetVersionListResponse>(`/datasets/${encodeURIComponent(datasetId)}/versions/${qs ? `?${qs}` : ''}`);
}

export async function refreshDataset(
  datasetId: string,
  token?: string,
  auth?: ServiceAuthRequest,
  acceptBlockedRunId?: string,
  verificationPolicy?: DatasetRefreshRequest['verification_policy'],
): Promise<DatasetRefreshResponse> {
  // The door refuses a body naming both spellings
  // (reject_service_auth_conflict), so send at most one.
  const credentialPayload: DatasetRefreshRequest = auth
    ? { auth }
    : { token: token ?? null };
  const payload = {
    ...credentialPayload,
    ...(acceptBlockedRunId ? { accept_blocked_run_id: acceptBlockedRunId } : {}),
    ...(verificationPolicy ? { verification_policy: verificationPolicy } : {}),
  };
  return apiFetch<DatasetRefreshResponse>(`/datasets/${encodeURIComponent(datasetId)}/refresh`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function restorePreviousVersion(
  datasetId: string,
  versionNumber: number,
): Promise<RestorePreviousVersionResponse> {
  return apiFetch<RestorePreviousVersionResponse>(
    `/datasets/${encodeURIComponent(datasetId)}/previous-versions/${versionNumber}/restore`,
    { method: 'POST' },
  );
}

export async function getDatasetRefreshRuns(
  datasetId: string,
  params: { skip?: number; limit?: number } = {},
): Promise<DatasetRefreshRunListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch<DatasetRefreshRunListResponse>(`/datasets/${encodeURIComponent(datasetId)}/refresh-runs${qs ? `?${qs}` : ''}`);
}

export async function listAttributes(datasetId: string): Promise<AttributeMetadataListResponse> {
  return apiFetch<AttributeMetadataListResponse>(`/datasets/${encodeURIComponent(datasetId)}/attributes/`);
}

export async function updateAttribute(
  datasetId: string,
  attributeId: string,
  data: AttributeMetadataUpdate,
): Promise<AttributeMetadataResponse> {
  return apiFetch<AttributeMetadataResponse>(`/datasets/${encodeURIComponent(datasetId)}/attributes/${encodeURIComponent(attributeId)}/`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function validateDataset(datasetId: string): Promise<ValidationResultResponse> {
  return apiFetch<ValidationResultResponse>(`/datasets/${encodeURIComponent(datasetId)}/validate/`);
}

export async function requestPresignedReupload(
  datasetId: string,
  filename: string,
  fileSize: number,
  contentType?: string,
): Promise<PresignedUploadResponse> {
  try {
    return await apiFetch<PresignedUploadResponse>(`/datasets/${encodeURIComponent(datasetId)}/reupload/presigned`, {
      method: 'POST',
      body: JSON.stringify({
        filename,
        file_size: fileSize,
        ...(contentType && { content_type: contentType }),
      }),
    });
  } catch (err) {
    rethrowAsUploadRefusal(err);
  }
}

async function completePresignedReupload(
  datasetId: string,
  jobId: string,
  parts?: { etag: string; part_number: number }[],
): Promise<UploadResponse> {
  try {
    return await apiFetch<UploadResponse>(`/datasets/${encodeURIComponent(datasetId)}/reupload/presigned/${encodeURIComponent(jobId)}/complete`, {
      method: 'POST',
      body: JSON.stringify({ parts: parts ?? [] }),
    });
  } catch (err) {
    rethrowAsUploadRefusal(err);
  }
}

// --- Related datasets ---

interface RelatedDatasetItem {
  id: string;
  name: string;
  geometry_type: string | null;
  similarity: number;
  record_type: string | null;
  feature_count: number | null;
  band_count: number | null;
}

interface RelatedDatasetsResponse {
  items: RelatedDatasetItem[];
  total: number;
}

export async function fetchRelatedDatasets(
  datasetId: string,
): Promise<RelatedDatasetsResponse> {
  return apiFetch<RelatedDatasetsResponse>(`/datasets/${encodeURIComponent(datasetId)}/related/`);
}

/** Reupload a file via the presigned URL flow for an existing dataset. */
export async function reuploadPresigned(
  datasetId: string,
  file: File,
): Promise<UploadResponse> {
  // The presigned PUT URL is signed for this content type, and fetch sends no
  // Content-Type for a Blob whose type is empty, so both sides name it.
  const contentType = file.type || 'application/octet-stream';
  const { job_id, urls, upload_id, part_size } = await requestPresignedReupload(
    datasetId,
    file.name,
    file.size,
    contentType,
  );

  if (urls.length === 1 && !upload_id) {
    const resp = await fetch(urls[0], { method: 'PUT', headers: { 'Content-Type': contentType }, body: file });
    if (!resp.ok) {
      throw new Error(
        i18n.t('common:errors.storageUploadFailed', { status: resp.status }),
      );
    }
    return completePresignedReupload(datasetId, job_id);
  }

  const etags = await uploadChunks(urls, file, part_size!, undefined, {
    // Tell the backend to abort the multipart upload if a part comes back with
    // no ETag; otherwise S3 keeps it open, consuming storage, with nothing left
    // to complete it.
    onMissingEtag: () => completePresignedReupload(datasetId, job_id),
  });
  const completedParts = etags.map((etag, i) => ({ etag, part_number: i + 1 }));

  return completePresignedReupload(datasetId, job_id, completedParts);
}

export async function listRelationships(datasetId: string): Promise<DatasetRelationship[]> {
  // The endpoint returns the standard list envelope ({ relationships, total });
  // unwrap to keep this helper's array contract.
  const res = await apiFetch<DatasetRelationshipListResponse>(
    `/datasets/${encodeURIComponent(datasetId)}/relationships/`,
  );
  return res.relationships;
}

export async function getRelatedRecords(
  datasetId: string,
  featureGid: number,
  relationshipId: string,
  params?: { limit?: number; after?: number },
): Promise<import('@/types/api').DatasetRowsResponse> {
  const query = new URLSearchParams();
  if (params?.limit !== undefined) query.set('limit', String(params.limit));
  if (params?.after !== undefined) query.set('after', String(params.after));
  const qs = query.toString();
  return apiFetch<import('@/types/api').DatasetRowsResponse>(
    `/datasets/${encodeURIComponent(datasetId)}/features/${encodeURIComponent(featureGid)}/related/${encodeURIComponent(relationshipId)}/${qs ? `?${qs}` : ''}`,
  );
}

/** Per-layer outcome from POST /ingest/commit-fan-out/{job_id}. */
interface FanOutLayerResult {
  layer_name: string;
  new_job_id: string | null;
  dataset_id: string | null;
  status: 'queued' | 'failed';
  error: string | null;
}

/** Response from POST /ingest/commit-fan-out/{job_id}. */
interface FanOutCommitResponse {
  fan_out_id: string;
  results: FanOutLayerResult[];
}

/**
 * Fan out a single uploaded file into N independent ingest tasks — one per
 * requested layer. The backend rejects N separate commits for one upload.
 *
 * @param jobId   The original pending IngestJob ID (returned by upload)
 * @param layers  Array of {layer_name, title?} objects to ingest
 */
export async function commitFanOut(
  jobId: string,
  layers: { layer_name: string; title?: string }[],
): Promise<FanOutCommitResponse> {
  // A direct apiFetch call rather than a TanStack mutation, so network and HTTP
  // failures are captured for the report buffer here.
  try {
    const response = await apiFetch<FanOutCommitResponse>(`/ingest/commit-fan-out/${encodeURIComponent(jobId)}`, {
      method: 'POST',
      body: JSON.stringify({ layers }),
    });
    // A 200 can still carry per-layer failures (results[].status === 'failed').
    // UploadForm shows them as commit-failed rows with a report CTA, so the buffer
    // needs one entry per failed layer: it dedups on message text alone, which
    // would merge layers failing with identical text.
    for (const result of response.results) {
      if (result.status === 'failed') {
        pushReportEntry({
          severity: 'error',
          source: 'network',
          message: `Layer import failed: ${result.layer_name}`,
          detail: result.error ?? undefined,
        });
      }
    }
    return response;
  } catch (err) {
    if (err instanceof ApiError) {
      reportNetworkError({ status: err.status, url: '/ingest/commit-fan-out', detail: err.body ?? err.message });
    } else {
      reportNetworkError({
        status: 0,
        url: '/ingest/commit-fan-out',
        detail: err instanceof Error ? err.message : undefined,
      });
    }
    throw err;
  }
}

/** Active write keys bound to this dataset: every one for its owner or an admin. */
export async function listDatasetApiKeys(datasetId: string): Promise<DatasetApiKeyResponse[]> {
  // One page covers the list: minting stops at 100 unrevoked keys per dataset.
  const data = await apiFetch<{ items: DatasetApiKeyResponse[]; total: number }>(
    `/datasets/${encodeURIComponent(datasetId)}/api-keys?limit=200`,
  );
  return data.items;
}

export async function createDatasetApiKey(
  datasetId: string,
  body: DatasetApiKeyCreateRequest,
): Promise<ApiKeyCreateResponse> {
  return apiFetch<ApiKeyCreateResponse>(`/datasets/${encodeURIComponent(datasetId)}/api-keys`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function revokeDatasetApiKey(datasetId: string, keyId: string): Promise<void> {
  await apiFetch(
    `/datasets/${encodeURIComponent(datasetId)}/api-keys/${encodeURIComponent(keyId)}`,
    { method: 'DELETE' },
  );
}
