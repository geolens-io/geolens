import { apiFetch, ApiError, sendInSession } from './client';
import { uploadChunks } from './_presignedUpload';
import { API_BASE } from '@/lib/constants';
import { describeUploadRefusal, UPLOAD_REFUSAL_FALLBACK_KEYS } from '@/lib/error-map';
import i18n from '@/i18n/i18n';
import { reportNetworkError } from '@/lib/report';
import type {
  UploadResponse,
  JobCancelResponse,
  JobStatusResponse,
  FilePreviewResponse,
  RasterPreviewResponse,
  TilesetPreviewResponse,
  PointCloudPreviewResponse,
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
  UploadKind,
  UrlUploadKind,
  VrtCreateRequest,
  VrtCreateResponse,
  ArcgisSigninRequest,
  ArcgisSigninResponse,
  ServiceAuthRequest,
} from '@/types/api';

/** Byte-transfer progress callback (0–1). */
export type UploadProgress = (fraction: number) => void;

/** No upload progress within this window means a stalled connection while bytes are still being sent. */
const UPLOAD_INACTIVITY_TIMEOUT_MS = 120_000;
/**
 * Once the body is sent the server stages and validates it, which is not
 * bounded by transfer speed. Outlive the proxy's 600s read timeout so the
 * proxy's verdict reaches the caller instead of a client-side abort.
 */
const UPLOAD_RESPONSE_TIMEOUT_MS = 630_000;

/**
 * Rethrows err, rebuilding an ApiError's message through describeUploadRefusal
 * only when its status is a key of UPLOAD_REFUSAL_FALLBACK_KEYS and its body
 * is a string. A transport failure (no body) rethrows unchanged.
 */
export function rethrowAsUploadRefusal(err: unknown): never {
  if (
    err instanceof ApiError &&
    typeof err.body === 'string' &&
    UPLOAD_REFUSAL_FALLBACK_KEYS[err.status] !== undefined
  ) {
    const message = describeUploadRefusal(err.body, err.status);
    if (message !== err.message) {
      const rebuilt = new ApiError(message, err.status, err.body);
      rebuilt.unconfirmed = err.unconfirmed;
      throw rebuilt;
    }
  }
  throw err;
}

/**
 * XHR-based POST so we can report upload-byte progress — `fetch()` cannot.
 * Sent through sendInSession, so a first-after-idle upload refreshes a stale
 * JWT and an upload outliving its session never acts on the next one.
 * A 401 retry re-sends the whole body — acceptable, since the proactive refresh
 * makes it rare.
 */
export async function xhrUpload<T>(
  path: string,
  formData: FormData,
  onProgress?: UploadProgress,
  signal?: AbortSignal,
): Promise<T> {
  // uploadFile runs from a plain try/catch in UploadForm, not a TanStack
  // mutation, so the MutationCache.onError tap in main.tsx never sees it. Report
  // metadata only (status, error text, filename), never the multipart body.
  const uploadedFile = formData.get('file');
  const filename = uploadedFile instanceof File ? uploadedFile.name : undefined;
  const reportUrl = filename ? `${path} (${filename})` : path;

  const attempt = (jwt: string | null): Promise<{ status: number; body: string }> =>
    new Promise<{ status: number; body: string }>((resolve, reject) => {
      if (signal?.aborted) {
        reject(new DOMException('Aborted', 'AbortError'));
        return;
      }
      const xhr = new XMLHttpRequest();
      let settled = false;
      let inactivityTimer: ReturnType<typeof setTimeout>;

      const settle = (fn: () => void) => {
        if (settled) return;
        settled = true;
        clearTimeout(inactivityTimer);
        signal?.removeEventListener('abort', onAbort);
        fn();
      };
      // Reset on every byte of progress, so a slow upload that keeps moving is
      // never cut off.
      const armTimer = (ms: number) => {
        clearTimeout(inactivityTimer);
        inactivityTimer = setTimeout(() => {
          settle(() => {
            xhr.abort();
            reject(new ApiError(i18n.t('common:errors.requestTimeout'), 0));
          });
        }, ms);
      };
      const armInactivityTimer = () => armTimer(UPLOAD_INACTIVITY_TIMEOUT_MS);
      const onAbort = () => {
        settle(() => {
          xhr.abort();
          reject(new DOMException('Aborted', 'AbortError'));
        });
      };
      signal?.addEventListener('abort', onAbort, { once: true });

      xhr.open('POST', `${API_BASE}${path}`);
      if (jwt) xhr.setRequestHeader('Authorization', `Bearer ${jwt}`);
      xhr.upload.onprogress = (e) => {
        armInactivityTimer();
        if (onProgress && e.lengthComputable) onProgress(e.loaded / e.total);
      };
      xhr.upload.onload = () => armTimer(UPLOAD_RESPONSE_TIMEOUT_MS);
      xhr.onload = () => settle(() => resolve({ status: xhr.status, body: xhr.responseText }));
      xhr.onerror = () =>
        settle(() => reject(new ApiError(i18n.t('common:errors.networkUnavailable'), 0)));
      xhr.onabort = onAbort;
      xhr.ontimeout = () =>
        settle(() => reject(new ApiError(i18n.t('common:errors.requestTimeout'), 0)));
      armInactivityTimer();
      xhr.send(formData);
    }).catch((err: unknown) => {
      // A caller's own cancellation is not a failure worth reporting.
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        reportNetworkError({ status: 0, url: reportUrl, detail: err instanceof Error ? err.message : undefined });
      }
      throw err;
    });

  // sendInSession can wait on a shared token refresh before it sends anything;
  // a cancel during that wait settles here without cancelling the refresh.
  const sending = sendInSession(attempt);
  const { response: res, refresh } = await (signal
    ? Promise.race([
        sending,
        new Promise<never>((_, reject) => {
          const onAbort = () => reject(new DOMException('Aborted', 'AbortError'));
          if (signal.aborted) onAbort();
          else signal.addEventListener('abort', onAbort, { once: true });
          sending.then(
            () => signal.removeEventListener('abort', onAbort),
            () => signal.removeEventListener('abort', onAbort),
          );
        }),
      ])
    : sending);

  if (res.status < 200 || res.status >= 300) {
    let detail: unknown;
    try {
      const parsed = JSON.parse(res.body);
      detail = parsed?.detail;
    } catch {
      // Non-JSON failures use the localized status category below.
    }
    reportNetworkError({ status: res.status, url: reportUrl, detail });
    const failure = new ApiError(describeUploadRefusal(detail, res.status), res.status, detail);
    // Same flag as authenticatedRawFetch: only a 401 that ended the session is
    // evidence the credential was rejected.
    if (res.status === 401 && refresh !== 'rejected') failure.unconfirmed = true;
    throw failure;
  }

  // A 2xx body that isn't valid JSON (empty, truncated, an intermediary's HTML
  // error page) would throw a raw SyntaxError outside the status branch above.
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
  kind?: UploadKind | null,
  signal?: AbortSignal,
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  if (kind) formData.append('kind', kind);

  return xhrUpload<UploadResponse>('/ingest/upload', formData, onProgress, signal);
}

/**
 * The URL variant of upload. The backend fetches the file server-side
 * (SSRF-validated, size-capped) into staging; the returned job then flows
 * through the same preview → commit pipeline as a direct upload.
 *
 * This call only validates and queues; the job is `running` until the worker has
 * the file, so poll `getJobStatus` and preview once it reaches `pending`.
 *
 * It can still outlive apiFetch's 30s default. Two sequential server-side waits
 * each have a 30s ceiling: the auth phase can spend DB_POOL_TIMEOUT under pool
 * saturation, then the SSRF preflight is allowed PREFLIGHT_DNS_MAX_SECONDS of
 * DNS (url_fetch.py). 90s covers 30 + 30 plus the config and quota reads and
 * the response itself. Aborting early is costly: the server still queues the
 * download and the browser has discarded the only copy of the job id, so the
 * import is unreachable until the stale sweep.
 */
const URL_SUBMIT_TIMEOUT_MS = 90_000;
export async function uploadFromUrl(
  url: string,
  filename?: string,
  kind?: UrlUploadKind | null,
): Promise<UploadResponse> {
  try {
    return await apiFetch<UploadResponse>('/ingest/upload/url', {
      method: 'POST',
      body: JSON.stringify({ url, ...(filename && { filename }), ...(kind && { kind }) }),
      timeoutMs: URL_SUBMIT_TIMEOUT_MS,
    });
  } catch (err) {
    // Direct call from UrlImportForm's try/catch (not a TanStack mutation),
    // so report here — metadata only, same reasoning as uploadFile above.
    reportApiCallFailure('/ingest/upload/url', err);
    rethrowAsUploadRefusal(err);
  }
}

export async function getJobStatus(
  jobId: string,
): Promise<JobStatusResponse> {
  return apiFetch<JobStatusResponse>(`/jobs/${encodeURIComponent(jobId)}`);
}

export async function getJobStatusByDataset(
  datasetId: string,
): Promise<JobStatusResponse | null> {
  // 200 + null means the dataset is visible but has no ingest job (remote, STAC
  // or registered dataset); a genuine 404 (not visible) still throws ApiError.
  // expected404 also covers older servers that 404 here.
  return apiFetch<JobStatusResponse | null>(`/jobs/by-dataset/${encodeURIComponent(datasetId)}`, {
    expected404: true,
  });
}

// run_ogrinfo_preview is bounded at OGRINFO_TIMEOUT_SECONDS = 300s, and its
// JSON-decode fallback can spawn ogrinfo twice more, exceeding even nginx's 600s
// read timeout. Outlive the proxy so whichever end fails first reaches the form
// as a real verdict rather than a client-side abort.
const PREVIEW_TIMEOUT_MS = 630_000;

export async function previewFile(jobId: string, layerName?: string): Promise<FilePreviewResponse | RasterPreviewResponse | TilesetPreviewResponse | PointCloudPreviewResponse> {
  const url = layerName
    ? `/ingest/preview/${encodeURIComponent(jobId)}?layer_name=${encodeURIComponent(layerName)}`
    : `/ingest/preview/${encodeURIComponent(jobId)}`;
  try {
    return await apiFetch<FilePreviewResponse | RasterPreviewResponse | TilesetPreviewResponse | PointCloudPreviewResponse>(url, {
      method: 'POST',
      timeoutMs: PREVIEW_TIMEOUT_MS,
    });
  } catch (err) {
    // Runs outside any TanStack mutation (UploadForm calls it directly), so report
    // here. Drop the job id from the reported path: an id isn't reliably
    // distinguishable from a secret by shape. Not gated on `instanceof ApiError`:
    // apiFetch throws a raw SyntaxError on a malformed 2xx body.
    reportApiCallFailure('/ingest/preview', err);
    rethrowAsUploadRefusal(err);
  }
}

export async function commitImport(
  jobId: string,
  request: CommitImportRequest,
): Promise<CommitImportResponse> {
  // Reached from UploadForm's commit handlers, which aren't TanStack mutations,
  // so a failure must be reported here.
  try {
    return await apiFetch<CommitImportResponse>(`/ingest/commit/${encodeURIComponent(jobId)}`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
  } catch (err) {
    reportApiCallFailure('/ingest/commit', err);
    rethrowAsUploadRefusal(err);
  }
}

export async function retryJob(jobId: string): Promise<UploadResponse> {
  return apiFetch<UploadResponse>(`/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: 'POST',
  });
}

// One-click cancel for a pending/running job. The backend CASes the job row
// (and its bound refresh run) to `cancelled` and commits before the best-effort
// queue abort, so a 200 is durable.
export async function cancelJob(jobId: string): Promise<JobCancelResponse> {
  return apiFetch<JobCancelResponse>(`/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
  });
}

// `auth` is optional beside `token`: ReuploadDialog.tsx still calls the
// two-argument bearer-only form, and the backend refuses a body that sets both
// (`reject_service_auth_conflict`).
export async function probeService(
  url: string,
  token?: string,
  auth?: ServiceAuthRequest,
): Promise<ProbeResponse> {
  return apiFetch<ProbeResponse>('/services/probe/', {
    method: 'POST',
    body: JSON.stringify({ url, ...(auth ? { auth } : token ? { token } : {}) }),
  });
}

// A WFS namespace mismatch makes run_service_preview run twice server-side at
// 30s each, past apiFetch's 30s default.
const SERVICE_PREVIEW_TIMEOUT_MS = 90_000;

export async function previewServiceLayer(
  request: ServicePreviewRequest,
): Promise<ServicePreviewResponse> {
  return apiFetch<ServicePreviewResponse>('/services/preview/', {
    method: 'POST',
    body: JSON.stringify(request),
    timeoutMs: SERVICE_PREVIEW_TIMEOUT_MS,
  });
}

// open_portal_signin's discovery and PortalSignIn.mint's token mint run
// sequentially under their own deadlines (_DISCOVERY_DEADLINE_SECONDS = 20,
// _MINT_DEADLINE_SECONDS = 25 in sources/arcgis_signin.py), so a slow Enterprise
// portal can take 45s. 60s covers that with margin; aborting earlier would leave
// the backend processing and counting the attempt. Exported so arcgis-signin.ts
// shares the number.
export const ARCGIS_SIGNIN_TIMEOUT_MS = 60_000;

// Mints a short-lived (60 min) ArcGIS token so the wizard never holds the
// password longer than this request. Never retries: ArcGIS locks an account after
// five failed sign-ins in fifteen minutes.
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
  kind?: UploadKind | null,
): Promise<PresignedUploadResponse> {
  try {
    return await apiFetch<PresignedUploadResponse>('/ingest/upload/presigned', {
      method: 'POST',
      body: JSON.stringify({
        filename,
        file_size: fileSize,
        ...(contentType && { content_type: contentType }),
        ...(kind && { kind }),
      }),
    });
  } catch (err) {
    rethrowAsUploadRefusal(err);
  }
}

async function completePresignedUpload(
  jobId: string,
  parts?: { etag: string; part_number: number }[],
): Promise<UploadResponse> {
  try {
    return await apiFetch<UploadResponse>(`/ingest/upload/presigned/${encodeURIComponent(jobId)}/complete`, {
      method: 'POST',
      body: JSON.stringify({ parts: parts ?? [] }),
    });
  } catch (err) {
    rethrowAsUploadRefusal(err);
  }
}

/**
 * Metadata-only report for any apiFetch-driven failure: an ApiError or anything
 * else apiFetch can throw, notably a raw SyntaxError from `response.json()` on a
 * malformed 2xx body. `label` is a short static description, never a raw URL
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
 * The flow runs outside any TanStack mutation, so each step reports its own
 * failure through reportNetworkError; otherwise a job staged by step 1 and
 * abandoned by a step-2/3 failure would leave nothing to report. The exception
 * is a part that uploads without an exposed ETag: `uploadChunks` throws that
 * unreported.
 */
export async function uploadPresigned(
  file: File,
  onProgress?: UploadProgress,
  kind?: UploadKind | null,
): Promise<UploadResponse> {
  // The presigned PUT URL is signed for this content type, and fetch sends no
  // Content-Type for a Blob whose type is empty, so both sides name it.
  const contentType = file.type || 'application/octet-stream';
  let job_id: string, urls: string[], upload_id: string | null | undefined, part_size: number | null | undefined;
  try {
    ({ job_id, urls, upload_id, part_size } = await requestPresignedUpload(
      file.name,
      file.size,
      contentType,
      kind,
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
      resp = await fetch(urls[0], { method: 'PUT', headers: { 'Content-Type': contentType }, body: file });
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
  const etags = await uploadChunks(urls, file, part_size!, onProgress, {
    // Abort the multipart upload if a part comes back with no ETag; otherwise S3
    // keeps it open (consuming storage) with nothing left to complete it.
    onMissingEtag: () => completePresignedUpload(job_id),
  });
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
