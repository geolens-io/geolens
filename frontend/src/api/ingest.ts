import { apiFetch, ApiError, notifySessionExpired, tryRefresh } from './client';
import { uploadChunks } from './_presignedUpload';
import { API_BASE } from '@/lib/constants';
import { translateApiErrorDetail } from '@/lib/error-map';
import i18n from '@/i18n/i18n';
import { useAuthStore } from '@/stores/auth-store';
import { reportNetworkError } from '@/lib/report';
import type {
  UploadResponse,
  JobCancelResponse,
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
  ArcgisSigninRequest,
  ArcgisSigninResponse,
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

  // codex on #1660: a 2xx response whose body isn't valid JSON (empty,
  // truncated, an HTML error page from an intermediary proxy) previously
  // threw a raw SyntaxError here, outside every reporting branch above —
  // the status-based `if (res.status < 200 || res.status >= 300)` block
  // never runs for a 2xx, so this failure had no capture path at all.
  try {
    return JSON.parse(res.body) as T;
  } catch (err) {
    reportNetworkError({
      status: res.status,
      url: reportUrl,
      detail: err instanceof Error ? `Malformed response body: ${err.message}` : undefined,
    });
    throw err;
  }
}

export async function uploadFile(
  file: File,
  onProgress?: UploadProgress,
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  return xhrUpload<UploadResponse>('/ingest/upload', formData, onProgress);
}

// fix(#1708 codex r2/r3): the backend holds this request open for the whole
// server-side download plus its post-work, all budgeted to fit inside the
// edge proxy's 600s `location /api/` read timeout (frontend/nginx.conf) —
// the fetch itself is bounded at FETCH_MAX_SECONDS = 480s in
// backend/app/processing/ingest/url_fetch.py. apiFetch's 30s default would
// abort the request (and lose the job id) long before either deadline.
// 630s deliberately OUTLIVES the proxy so whichever end fails first — the
// backend's own 4xx/502 or the proxy's 504 — reaches the form as a real
// verdict instead of a client-side abort.
const URL_IMPORT_TIMEOUT_MS = 630_000;

/**
 * feat(#1705): the URL variant of upload. The backend fetches the file
 * server-side (SSRF-validated, size-capped) into staging; the returned job
 * then flows through the same preview → commit pipeline as a direct upload.
 */
export async function uploadFromUrl(
  url: string,
  filename?: string,
): Promise<UploadResponse> {
  try {
    return await apiFetch<UploadResponse>('/ingest/upload/url', {
      method: 'POST',
      body: JSON.stringify({ url, ...(filename && { filename }) }),
      timeoutMs: URL_IMPORT_TIMEOUT_MS,
    });
  } catch (err) {
    // Direct call from UrlImportForm's try/catch (not a TanStack mutation),
    // so report here — metadata only, same reasoning as uploadFile above.
    reportApiCallFailure('/ingest/upload/url', err);
    throw err;
  }
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
    //
    // codex on #1660: gating this on `instanceof ApiError` skipped a real
    // failure class — apiFetch's own `response.json()` throws a raw
    // SyntaxError (not ApiError) on a malformed 2xx body, and that error type
    // silently fell through this guard uncaptured. reportApiCallFailure
    // handles every error shape uniformly.
    reportApiCallFailure('/ingest/preview', err);
    throw err;
  }
}

export async function commitImport(
  jobId: string,
  request: CommitImportRequest,
): Promise<CommitImportResponse> {
  // codex on #1660: commitImport is a direct apiFetch call reached from
  // UploadForm's handleCommitSingle/handleCommitAll, neither of which is a
  // TanStack mutation — a commit failure set the row to 'commit-failed' with
  // nothing written to the report buffer at all (a different gap from the
  // upload/preview one: no capture attempt existed here previously).
  try {
    return await apiFetch<CommitImportResponse>(`/ingest/commit/${jobId}`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
  } catch (err) {
    reportApiCallFailure('/ingest/commit', err);
    throw err;
  }
}

export async function retryJob(jobId: string): Promise<UploadResponse> {
  return apiFetch<UploadResponse>(`/jobs/${jobId}/retry`, {
    method: 'POST',
  });
}

// feat(#1677): one-click cancel for a pending/running job. The backend CASes
// the job row (and its bound refresh run) to `cancelled` and commits before
// the best-effort queue abort, so a 200 here is durable.
export async function cancelJob(jobId: string): Promise<JobCancelResponse> {
  return apiFetch<JobCancelResponse>(`/jobs/${jobId}/cancel`, {
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

// fix(#1757 codex): open_portal_signin's discovery phase and
// PortalSignIn.mint's token-mint phase run sequentially, each under its
// own asyncio.timeout in backend/app/modules/catalog/sources/
// arcgis_signin.py (_DISCOVERY_DEADLINE_SECONDS = 20,
// _MINT_DEADLINE_SECONDS = 25), so a slow Enterprise portal can
// legitimately take up to 45s end to end. apiFetch's 30s default would
// abort a valid slow sign-in in the browser while the backend keeps
// processing, and counting, the attempt. 60s covers the 45s backend
// bound with margin.
// codex #1759 post-#1757-merge dedupe: exported so lane A3's
// independent arcgis-signin.ts client (frontend/src/components/dataset/
// ArcgisCredentialBlock.tsx's refresh-door credential prompt) can share
// this exact number rather than declare its own -- the backend bound
// below is one fact and both callers need the same margin over it.
export const ARCGIS_SIGNIN_TIMEOUT_MS = 60_000;

// fix(service-auth wave, lane A2): mints a short-lived (60 min) ArcGIS token
// from a username and password so the import wizard never has to hold that
// password any longer than this one request. The caller clears its own
// password state as soon as this settles, success or failure alike; this
// function never retries, because ArcGIS locks an account after five failed
// sign-ins in fifteen minutes, and a retry loop here could do that to a
// real customer account.
export async function arcgisSignin(
  request: ArcgisSigninRequest,
): Promise<ArcgisSigninResponse> {
  return apiFetch<ArcgisSigninResponse>('/services/arcgis/signin/', {
    method: 'POST',
    body: JSON.stringify(request),
    timeoutMs: ARCGIS_SIGNIN_TIMEOUT_MS,
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
 * Metadata-only report for any apiFetch-driven failure: an ApiError (a real
 * HTTP error status) or anything else apiFetch can throw uncaught — notably
 * a raw SyntaxError from `response.json()` on a malformed 2xx body, which the
 * previous `instanceof ApiError` gates in this file silently swallowed
 * (codex on #1660). `label` is a short static description, never a raw URL
 * with an id or a presigned query string in it.
 */
function reportApiCallFailure(label: string, err: unknown): void {
  if (err instanceof ApiError) {
    reportNetworkError({ status: err.status, url: label, detail: err.body ?? err.message });
  } else {
    reportNetworkError({ status: 0, url: label, detail: err instanceof Error ? err.message : undefined });
  }
}

// Metadata-only report for a step in the presigned-upload handshake
// (request → PUT → complete). `stage` is a short static label, never the
// presigned URL itself, which carries a time-limited access signature.
function reportPresignFailure(stage: string, filename: string, err: unknown): void {
  reportApiCallFailure(`presigned:${stage} (${filename})`, err);
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
