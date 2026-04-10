import { apiFetch } from './client';
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

export async function uploadFile(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  return apiFetch<UploadResponse>('/ingest/upload', {
    method: 'POST',
    body: formData,
  });
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
export async function uploadPresigned(file: File): Promise<UploadResponse> {
  const { job_id, urls, upload_id, part_size } = await requestPresignedUpload(
    file.name,
    file.size,
    file.type || undefined,
  );

  if (urls.length === 1 && !upload_id) {
    // Simple PUT upload
    const resp = await fetch(urls[0], { method: 'PUT', body: file });
    if (!resp.ok) throw new Error(`S3 upload failed: ${resp.status} ${resp.statusText}`);
    return completePresignedUpload(job_id);
  }

  // Multipart upload
  const chunkSize = part_size!;
  const completedParts: { etag: string; part_number: number }[] = [];

  for (let i = 0; i < urls.length; i++) {
    const start = i * chunkSize;
    const end = Math.min(start + chunkSize, file.size);
    const chunk = file.slice(start, end);
    const resp = await fetch(urls[i], { method: 'PUT', body: chunk });
    if (!resp.ok) throw new Error(`S3 part ${i + 1} upload failed: ${resp.status}`);
    const etag = resp.headers.get('ETag') ?? '';
    completedParts.push({ etag, part_number: i + 1 });
  }

  return completePresignedUpload(job_id, completedParts);
}

export async function createVrt(request: VrtCreateRequest): Promise<VrtCreateResponse> {
  return apiFetch<VrtCreateResponse>('/ingest/vrt/create', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}
