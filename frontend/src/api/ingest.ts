import { apiFetch, ApiError, tryRefresh } from './client';
import { uploadChunks } from './_presignedUpload';
import { API_BASE } from '@/lib/constants';
import { translateError } from '@/lib/error-map';
import { useAuthStore } from '@/stores/auth-store';
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
 * ponytail: a 401 retry re-sends the whole body — acceptable, refresh makes it rare.
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
        reject(new ApiError('Network unavailable — check your connection', 0));
      xhr.send(formData);
    });

  let res = await attempt();
  if (res.status === 401 && (await tryRefresh())) {
    res = await attempt();
  }

  if (res.status < 200 || res.status >= 300) {
    let detail = `HTTP ${res.status}`;
    try {
      const parsed = JSON.parse(res.body);
      if (parsed?.detail !== undefined) {
        detail =
          typeof parsed.detail === 'string'
            ? parsed.detail
            : JSON.stringify(parsed.detail);
      }
    } catch {
      // non-JSON body — keep the HTTP status fallback
    }
    if (res.status === 401) useAuthStore.getState().logout();
    throw new ApiError(translateError(detail), res.status);
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
): Promise<JobStatusResponse> {
  return apiFetch<JobStatusResponse>(`/jobs/by-dataset/${datasetId}`);
}

export async function previewFile(jobId: string, layerName?: string): Promise<FilePreviewResponse> {
  const url = layerName
    ? `/ingest/preview/${jobId}?layer_name=${encodeURIComponent(layerName)}`
    : `/ingest/preview/${jobId}`;
  return apiFetch<FilePreviewResponse>(url, {
    method: 'POST',
  });
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

/**
 * Upload a file via presigned URL flow:
 * 1. Request presigned URL(s) from backend
 * 2. PUT file directly to S3
 * 3. Notify backend of completion
 * Returns the same UploadResponse as the regular upload endpoint.
 */
export async function uploadPresigned(
  file: File,
  onProgress?: UploadProgress,
): Promise<UploadResponse> {
  const { job_id, urls, upload_id, part_size } = await requestPresignedUpload(
    file.name,
    file.size,
    file.type || undefined,
  );

  if (urls.length === 1 && !upload_id) {
    // Simple PUT upload. ponytail: single-PUT is only used for small files —
    // coarse 0→1 instead of an extra XHR-with-progress path.
    onProgress?.(0);
    const resp = await fetch(urls[0], { method: 'PUT', body: file });
    if (!resp.ok) throw new Error(`S3 upload failed: ${resp.status} ${resp.statusText}`);
    onProgress?.(1);
    return completePresignedUpload(job_id);
  }

  // Multipart upload — progress reported per completed chunk.
  const etags = await uploadChunks(urls, file, part_size!, onProgress);
  const completedParts = etags.map((etag, i) => ({ etag, part_number: i + 1 }));

  return completePresignedUpload(job_id, completedParts);
}

export async function createVrt(request: VrtCreateRequest): Promise<VrtCreateResponse> {
  return apiFetch<VrtCreateResponse>('/ingest/vrt/create', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}
