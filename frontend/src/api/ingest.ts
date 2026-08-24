import { apiFetch, ApiError, notifySessionExpired, tryRefresh } from './client';
import { uploadChunks } from './_presignedUpload';
import { API_BASE } from '@/lib/constants';
import { translateApiErrorDetail } from '@/lib/error-map';
import i18n from '@/i18n/i18n';
import { useAuthStore } from '@/stores/auth-store';
import { reportNetworkError } from '@/lib/report';
import type {
  UploadResponse,
  JobStatusResponse,
  FilePreviewResponse,
  CommitImportRequest,
  CommitImportResponse,
  ProbeResponse,
  ServicePreviewRequest,
  ServicePreviewResponse,
  DiscoverResponse,
  BulkRegisterRequest,
  BulkRegisterResponse,
  UploadConfig,
  PresignedUploadResponse,
  VrtCreateRequest,
  VrtCreateResponse,
} from '@/types/api';

/** Byte-transfer progress callback (0–1). */
export type UploadProgress = (fraction: number) => void;

/**
 * XHR-based POST so we can report upload-byte progress — `fetch()` cannot.
 * Mirrors authenticatedRawFetch's proactive-refresh + single 401 retry so a
 * first-after-idle upload doesn't hard-fail on a stale JWT.
 * A 401 retry re-sends the whole body — acceptable, since the proactive refresh
 * makes it rare.
 */
async function xhrUpload<T>(
  path: string,
  formData: FormData,
  onProgress?: UploadProgress,
): Promise<T> {
  const { token, expiresAt } = useAuthStore.getState();
  if (token && expiresAt && Date.now() > expiresAt - 30_000) {
    await tryRefresh();
  }

  // A direct-POST upload (uploadFile) previously bypassed the problem
  // reporter entirely: it's called from a plain try/catch in UploadForm, not
  // a TanStack mutation, so the shared MutationCache.onError tap in main.tsx
  // never sees it. Report here instead — metadata only (status, error text,
  // filename), never the multipart file body.
  const uploadedFile = formData.get('file');
  const filename = uploadedFile instanceof File ? uploadedFile.name : undefined;
  const reportUrl = filename ? `${path} (${filename})` : path;

  const attempt = (): Promise<{ status: number; body: string }> =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API_BASE}${path}`);
      const jwt = useAuthStore.getState().token;
      if (jwt) xhr.setRequestHeader('Authorization', `Bearer ${jwt}`);
      if (onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) onProgress(e.loaded / e.total);
        };
      }
      xhr.onload = () => resolve({ status: xhr.status, body: xhr.responseText });
      xhr.onerror = () =>
        reject(new ApiError(i18n.t('common:errors.networkUnavailable'), 0));
      xhr.send(formData);
    });

  let res: { status: number; body: string };
  try {
    res = await attempt();
  } catch (err) {
    reportNetworkError({ status: 0, url: reportUrl, detail: err instanceof Error ? err.message : undefined });
    throw err;
  }
  // fix(#1446): capture the dead session BEFORE refreshing, matching
  // authenticatedRawFetch — every concurrent failure then keys the
  // notification latch on the same value.
  let deadSessionKey: string | null = null;
  if (res.status === 401) {
    deadSessionKey = useAuthStore.getState().token;
    if (await tryRefresh()) {
      try {
        res = await attempt();
      } catch (err) {
        reportNetworkError({ status: 0, url: reportUrl, detail: err instanceof Error ? err.message : undefined });
        throw err;
      }
    }
  }

  if (res.status < 200 || res.status >= 300) {
    let detail: unknown;
    try {
      const parsed = JSON.parse(res.body);
      detail = parsed?.detail;
    } catch {
      // Non-JSON failures use the localized status category below.
    }
    reportNetworkError({ status: res.status, url: reportUrl, detail });
    // fix(#1446): route terminal auth failure through the shared path instead
    // of clearing the store directly. Since the refresh credential became an
    // httpOnly cookie, a store-only logout leaves it and its server-side row
    // alive; notifySessionExpired dispatches the revocation. It also gives
    // uploads the same single signed-out prompt every other surface shows
    // (fix(#628)), which this call site never had.
    if (res.status === 401) {
      if (deadSessionKey) {
        notifySessionExpired(deadSessionKey);
      } else {
        useAuthStore.getState().logout();
      }
    }
    throw new ApiError(translateApiErrorDetail(detail, res.status), res.status, detail);
  }

  return JSON.parse(res.body) as T;
}

export async function uploadFile(
  file: File,
  onProgress?: UploadProgress,
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  return xhrUpload<UploadResponse>('/ingest/upload', formData, onProgress);
}

export async function getJobStatus(
  jobId: string,
): Promise<JobStatusResponse> {
  return apiFetch<JobStatusResponse>(`/jobs/${jobId}`);
}

export async function getJobStatusByDataset(
  datasetId: string,
): Promise<JobStatusResponse | null> {
  // Backend returns 200 + null when the dataset is visible but has no ingest
  // job (remote/STAC/registered dataset); apiFetch resolves the null JSON body
  // to null. A genuine 404 (dataset not visible) still throws ApiError.
  // expected404 also keeps older servers (pre-200+null) from throwing here.
  return apiFetch<JobStatusResponse | null>(`/jobs/by-dataset/${datasetId}`, {
    expected404: true,
  });
}

export async function previewFile(jobId: string, layerName?: string): Promise<FilePreviewResponse> {
  const url = layerName
    ? `/ingest/preview/${jobId}?layer_name=${encodeURIComponent(layerName)}`
    : `/ingest/preview/${jobId}`;
  try {
    return await apiFetch<FilePreviewResponse>(url, {
      method: 'POST',
    });
  } catch (err) {
    // Detection/preview also runs outside any TanStack mutation (UploadForm
    // calls it directly to keep per-file state granular), so it was invisible
    // to the report buffer the same way uploadFile was. Drop the job id from
    // the reported path — same reasoning as reportQueryKey in main.tsx: an id
    // isn't reliably distinguishable from a secret by shape.
    if (err instanceof ApiError) {
      reportNetworkError({ status: err.status, url: '/ingest/preview', detail: err.body ?? err.message });
    }
    throw err;
  }
}

export async function commitImport(
  jobId: string,
  request: CommitImportRequest,
): Promise<CommitImportResponse> {
  return apiFetch<CommitImportResponse>(`/ingest/commit/${jobId}`, {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export async function retryJob(jobId: string): Promise<UploadResponse> {
  return apiFetch<UploadResponse>(`/jobs/${jobId}/retry`, {
    method: 'POST',
  });
}

export async function probeService(url: string, token?: string): Promise<ProbeResponse> {
  return apiFetch<ProbeResponse>('/services/probe/', {
    method: 'POST',
    body: JSON.stringify({ url, ...(token && { token }) }),
  });
}

export async function previewServiceLayer(
  request: ServicePreviewRequest,
): Promise<ServicePreviewResponse> {
  return apiFetch<ServicePreviewResponse>('/services/preview/', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export async function discoverTables(): Promise<DiscoverResponse> {
  return apiFetch<DiscoverResponse>('/ingest/discover/');
}

export async function bulkRegisterTables(
  request: BulkRegisterRequest,
): Promise<BulkRegisterResponse> {
  return apiFetch<BulkRegisterResponse>('/ingest/register/bulk/', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export async function getUploadConfig(): Promise<UploadConfig> {
  return apiFetch<UploadConfig>('/ingest/upload/config');
}

export async function requestPresignedUpload(
  filename: string,
  fileSize: number,
  contentType?: string,
): Promise<PresignedUploadResponse> {
  return apiFetch<PresignedUploadResponse>('/ingest/upload/presigned', {
    method: 'POST',
    body: JSON.stringify({
      filename,
      file_size: fileSize,
      ...(contentType && { content_type: contentType }),
    }),
  });
}

export async function completePresignedUpload(
  jobId: string,
  parts?: { etag: string; part_number: number }[],
): Promise<UploadResponse> {
  return apiFetch<UploadResponse>(`/ingest/upload/presigned/${jobId}/complete`, {
    method: 'POST',
    body: JSON.stringify({ parts: parts ?? [] }),
  });
}

// Metadata-only report for a step in the presigned-upload handshake
// (request → PUT → complete). `stage` is a short static label, never the
// presigned URL itself, which carries a time-limited access signature.
function reportPresignFailure(stage: string, filename: string, err: unknown): void {
  const url = `presigned:${stage} (${filename})`;
  if (err instanceof ApiError) {
    reportNetworkError({ status: err.status, url, detail: err.body ?? err.message });
  } else {
    reportNetworkError({ status: 0, url, detail: err instanceof Error ? err.message : undefined });
  }
}

/**
 * Upload a file via presigned URL flow:
 * 1. Request presigned URL(s) from backend
 * 2. PUT file directly to S3
 * 3. Notify backend of completion
 * Returns the same UploadResponse as the regular upload endpoint.
 *
 * This whole flow runs outside any TanStack mutation (UploadForm calls it
 * directly to keep per-file state granular), so none of its failures ever
 * reached the shared MutationCache.onError tap in main.tsx — a job could be
 * staged on the backend by step 1 and then abandoned by a step-2/3 failure
 * with nothing recorded anywhere the user could report. Each step below
 * reports its own failure through the existing reportNetworkError tap.
 */
export async function uploadPresigned(
  file: File,
  onProgress?: UploadProgress,
): Promise<UploadResponse> {
  let job_id: string, urls: string[], upload_id: string | null | undefined, part_size: number | null | undefined;
  try {
    ({ job_id, urls, upload_id, part_size } = await requestPresignedUpload(
      file.name,
      file.size,
      file.type || undefined,
    ));
  } catch (err) {
    reportPresignFailure('request', file.name, err);
    throw err;
  }

  if (urls.length === 1 && !upload_id) {
    // Simple PUT upload. Single-PUT is only used for small files, so progress
    // is a coarse 0→1 instead of an extra XHR-with-progress path.
    onProgress?.(0);
    let resp: Response;
    try {
      resp = await fetch(urls[0], { method: 'PUT', body: file });
    } catch (err) {
      reportPresignFailure('put', file.name, err);
      throw err;
    }
    if (!resp.ok) {
      reportNetworkError({ status: resp.status, url: `presigned:put (${file.name})` });
      throw new Error(
        i18n.t('common:errors.storageUploadFailed', { status: resp.status }),
      );
    }
    onProgress?.(1);
    try {
      return await completePresignedUpload(job_id);
    } catch (err) {
      reportPresignFailure('complete', file.name, err);
      throw err;
    }
  }

  // Multipart upload — progress reported per completed chunk. uploadChunks
  // reports its own per-part failures.
  const etags = await uploadChunks(urls, file, part_size!, onProgress);
  const completedParts = etags.map((etag, i) => ({ etag, part_number: i + 1 }));

  try {
    return await completePresignedUpload(job_id, completedParts);
  } catch (err) {
    reportPresignFailure('complete', file.name, err);
    throw err;
  }
}

export async function createVrt(request: VrtCreateRequest): Promise<VrtCreateResponse> {
  return apiFetch<VrtCreateResponse>('/ingest/vrt/create', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}
