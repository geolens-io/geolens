import { API_BASE } from '@/lib/constants';
import { apiFetch } from './client';
import { useAuthStore } from '@/stores/auth-store';
import type {
  CreateDatasetRequest,
  DatasetResponse,
  DatasetRowsResponse,
  DatasetUpdateRequest,
  AuditLogListResponse,
  ReuploadResponse,
  ReuploadServicePreviewRequest,
  ReuploadPreviewResponse,
  ReuploadCommitRequest,
  ReuploadCommitResponse,
  DatasetVersionListResponse,
  AttributeMetadataListResponse,
  AttributeMetadataResponse,
  AttributeMetadataUpdate,
  ValidationResultResponse,
  PresignedUploadResponse,
  UploadResponse,
} from '@/types/api';

export async function createDataset(data: CreateDatasetRequest): Promise<DatasetResponse> {
  return apiFetch<DatasetResponse>('/datasets/create/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getDataset(id: string): Promise<DatasetResponse> {
  return apiFetch<DatasetResponse>(`/datasets/${id}`);
}

export async function getDatasetRows(
  id: string,
  params: { limit?: number; after?: number; filters?: Record<string, string> } = {},
): Promise<DatasetRowsResponse> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.after !== undefined) query.set('after', String(params.after));
  if (params.filters) {
    for (const [col, value] of Object.entries(params.filters)) {
      if (value) query.set(`filter[${col}]`, value);
    }
  }
  const qs = query.toString();
  return apiFetch<DatasetRowsResponse>(`/datasets/${id}/rows${qs ? `?${qs}` : ''}`);
}

export function getExportUrl(
  id: string,
  format: string,
  options: { target_crs?: string; bbox?: string; where?: string } = {},
): string {
  const query = new URLSearchParams({ format });
  if (options.target_crs) query.set('target_crs', options.target_crs);
  if (options.bbox) query.set('bbox', options.bbox);
  if (options.where) query.set('where', options.where);
  return `${API_BASE}/datasets/${id}/export?${query.toString()}`;
}

export async function downloadExport(
  id: string,
  format: string,
  filename: string,
): Promise<void> {
  const token = useAuthStore.getState().token;
  const url = getExportUrl(id, format);

  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url, { headers });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body.detail) {
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // body not JSON
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(objectUrl);
}

export async function updateDataset(
  id: string,
  data: DatasetUpdateRequest,
): Promise<DatasetResponse> {
  return apiFetch<DatasetResponse>(`/datasets/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function updatePublicationStatus(
  id: string,
  status: string,
): Promise<DatasetResponse> {
  return apiFetch<DatasetResponse>(`/datasets/${id}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
}

export async function deleteDataset(
  id: string,
  confirmName: string,
): Promise<void> {
  await apiFetch(`/datasets/${id}`, {
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
  return apiFetch<AuditLogListResponse>(`/datasets/${id}/history${qs ? `?${qs}` : ''}`);
}

export async function reuploadDataset(
  datasetId: string,
  file: File,
): Promise<ReuploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  return apiFetch<ReuploadResponse>(`/datasets/${datasetId}/reupload`, {
    method: 'POST',
    body: formData,
  });
}

export async function reuploadPreview(
  datasetId: string,
  jobId: string,
): Promise<ReuploadPreviewResponse> {
  return apiFetch<ReuploadPreviewResponse>(`/datasets/${datasetId}/reupload/${jobId}/preview`, {
    method: 'POST',
  });
}

export async function reuploadServicePreview(
  datasetId: string,
  request: ReuploadServicePreviewRequest,
): Promise<ReuploadPreviewResponse> {
  return apiFetch<ReuploadPreviewResponse>(`/datasets/${datasetId}/reupload/service/preview`, {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export async function reuploadCommit(
  datasetId: string,
  jobId: string,
  sridOverride?: number | null,
  token?: string,
): Promise<ReuploadCommitResponse> {
  const payload: ReuploadCommitRequest = {
    srid_override: sridOverride ?? null,
    ...(token ? { token } : {}),
  };

  return apiFetch<ReuploadCommitResponse>(`/datasets/${datasetId}/reupload/${jobId}/commit`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function addColumn(
  datasetId: string,
  column: { name: string; type: string },
): Promise<{ columns: { name: string; type: string }[] }> {
  return apiFetch<{ columns: { name: string; type: string }[] }>(
    `/layers/${datasetId}/columns/`,
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
    `/layers/${datasetId}/columns/${columnName}`,
    {
      method: 'DELETE',
    },
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
  return apiFetch<DatasetVersionListResponse>(`/datasets/${datasetId}/versions${qs ? `?${qs}` : ''}`);
}

export async function listAttributes(datasetId: string): Promise<AttributeMetadataListResponse> {
  return apiFetch<AttributeMetadataListResponse>(`/datasets/${datasetId}/attributes/`);
}

export async function updateAttribute(
  datasetId: string,
  attributeId: string,
  data: AttributeMetadataUpdate,
): Promise<AttributeMetadataResponse> {
  return apiFetch<AttributeMetadataResponse>(`/datasets/${datasetId}/attributes/${attributeId}/`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function validateDataset(datasetId: string): Promise<ValidationResultResponse> {
  return apiFetch<ValidationResultResponse>(`/datasets/${datasetId}/validate/`);
}

export async function requestPresignedReupload(
  datasetId: string,
  filename: string,
  fileSize: number,
  contentType?: string,
): Promise<PresignedUploadResponse> {
  return apiFetch<PresignedUploadResponse>(`/datasets/${datasetId}/reupload/presigned`, {
    method: 'POST',
    body: JSON.stringify({
      filename,
      file_size: fileSize,
      ...(contentType && { content_type: contentType }),
    }),
  });
}

export async function completePresignedReupload(
  datasetId: string,
  jobId: string,
  parts?: { etag: string; part_number: number }[],
): Promise<UploadResponse> {
  return apiFetch<UploadResponse>(`/datasets/${datasetId}/reupload/presigned/${jobId}/complete`, {
    method: 'POST',
    body: JSON.stringify({ parts: parts ?? [] }),
  });
}

/**
 * Reupload a file via presigned URL flow for an existing dataset.
 * Same pattern as uploadPresigned but uses reupload endpoints.
 */
// --- Related datasets ---

export interface RelatedDatasetItem {
  id: string;
  name: string;
  geometry_type: string | null;
  similarity: number;
  record_type: string | null;
  feature_count: number | null;
  band_count: number | null;
}

export interface RelatedDatasetsResponse {
  items: RelatedDatasetItem[];
  total: number;
}

export async function fetchRelatedDatasets(
  datasetId: string,
): Promise<RelatedDatasetsResponse> {
  return apiFetch<RelatedDatasetsResponse>(`/datasets/${datasetId}/related/`);
}

export async function reuploadPresigned(
  datasetId: string,
  file: File,
): Promise<UploadResponse> {
  const { job_id, urls, upload_id, part_size } = await requestPresignedReupload(
    datasetId,
    file.name,
    file.size,
    file.type || undefined,
  );

  if (urls.length === 1 && !upload_id) {
    const resp = await fetch(urls[0], { method: 'PUT', body: file });
    if (!resp.ok) throw new Error(`S3 upload failed: ${resp.status} ${resp.statusText}`);
    return completePresignedReupload(datasetId, job_id);
  }

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

  return completePresignedReupload(datasetId, job_id, completedParts);
}
