import i18n from '@/i18n/i18n';
import { reportNetworkError } from '@/lib/report';

/**
 * Shared chunked-PUT helper for presigned S3 multipart uploads.
 *
 * XHR, not `fetch`, PUTs each part (see the per-part timeout comment below).
 * Presigned URLs are signed by the backend and must not carry the session JWT
 * (S3 rejects extra Authorization headers on V4-signed URLs), so no auth header
 * is ever attached here.
 */

interface UploadChunksOptions {
  /**
   * Cancel a runaway multi-GB upload. Aborting rejects the in-flight part's
   * XHR; the loop then throws the AbortError without starting the next part.
   */
  signal?: AbortSignal;
  /**
   * Retry a failed part instead of discarding the whole upload. Retries apply
   * per part, so earlier parts are never re-sent.
   */
  maxRetries?: number;
  /**
   * Called (best-effort, errors swallowed) before throwing on a missing ETag.
   * S3 already accepted this part, so without this the multipart upload is
   * never told to stop and keeps consuming storage. The caller supplies its
   * "complete with no parts" call (`completePresignedUpload(jobId)` /
   * `completePresignedReupload(datasetId, jobId)`); the backend treats an empty
   * parts list as abandonment and aborts the multipart upload.
   */
  onMissingEtag?: () => Promise<unknown>;
}

const DEFAULT_MAX_RETRIES = 3;

/**
 * `AbortSignal.timeout()` is a wall-clock deadline, not a stall detector, and
 * `fetch` has no upload-progress signal, so the per-part PUT uses XHR: its
 * `upload.onprogress` fires on every chunk sent and resets the timeout below on
 * real activity.
 *
 *  - INACTIVITY_TIMEOUT_MS: no progress event within this window means the
 *    connection is stalled. Reset on every progress event, so a slow but
 *    progressing part is never aborted by this alone.
 *
 *  - PART_CEILING_MS: an absolute bound while progress keeps resetting the timer
 *    above. Derived from the largest part (PART_SIZE_UPPER_BOUND_BYTES, matching
 *    the backend's multipart PART_SIZE) at the backend's credited minimum
 *    upload rate (MIN_UPLOAD_RATE_BYTES_PER_SEC): 10 MiB / 32 KiB/s = 320s,
 *    with a 1.5x margin (≈480s) for rate variance and retry backoff.
 */
const INACTIVITY_TIMEOUT_MS = 60_000;
const PART_SIZE_UPPER_BOUND_BYTES = 10 * 1024 * 1024; // 10 MiB — backend PART_SIZE
const MIN_UPLOAD_RATE_BYTES_PER_SEC = 32 * 1024; // 32 KiB/s — backend's credited minimum
const PART_CEILING_MS = Math.ceil(
  (PART_SIZE_UPPER_BOUND_BYTES / MIN_UPLOAD_RATE_BYTES_PER_SEC) * 1000 * 1.5,
);

class UploadHttpError extends Error {}

/**
 * A timeout abort (inactivity or ceiling). Deliberately NOT a DOMException
 * named 'AbortError': that name is reserved for a CALLER-initiated abort, which
 * the loop below treats as terminal. A stalled connection is retriable.
 */
class UploadTimeoutError extends Error {}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

/**
 * A part is worth retrying on a network error or a transient server status
 * (429, 5xx). A 4xx is permanent — a malformed or expired presigned URL will
 * fail identically on retry, so fail fast and let the caller re-request URLs.
 */
function isRetriableStatus(status: number): boolean {
  return status === 429 || status >= 500;
}

interface XhrPutResult {
  ok: boolean;
  status: number;
  etag: string | null;
}

/**
 * PUT one chunk via XHR, bounded by an inactivity timer (reset on every
 * `upload.onprogress`) and an absolute ceiling — see the constants above
 * for the derivation of both. Resolves for ANY completed HTTP response
 * (2xx or not — the caller classifies the status); rejects only for a
 * caller-initiated abort (`AbortError`), a timeout (`UploadTimeoutError`),
 * or a transport-level failure with no response at all.
 */
function putChunkXHR(
  url: string,
  chunk: Blob,
  signal: AbortSignal | undefined,
): Promise<XhrPutResult> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }

    const xhr = new XMLHttpRequest();
    let inactivityTimer: ReturnType<typeof setTimeout>;
    let settled = false;

    const cleanup = () => {
      clearTimeout(inactivityTimer);
      clearTimeout(ceilingTimer);
      signal?.removeEventListener('abort', onAbort);
    };

    const settle = (fn: () => void) => {
      if (settled) return;
      settled = true;
      cleanup();
      fn();
    };

    const resetInactivityTimer = () => {
      clearTimeout(inactivityTimer);
      inactivityTimer = setTimeout(() => {
        settle(() => {
          xhr.abort();
          reject(new UploadTimeoutError('Upload part stalled: no progress'));
        });
      }, INACTIVITY_TIMEOUT_MS);
    };

    const onAbort = () => {
      settle(() => {
        xhr.abort();
        reject(new DOMException('Aborted', 'AbortError'));
      });
    };
    signal?.addEventListener('abort', onAbort, { once: true });

    const ceilingTimer = setTimeout(() => {
      settle(() => {
        xhr.abort();
        reject(new UploadTimeoutError('Upload part exceeded its absolute ceiling'));
      });
    }, PART_CEILING_MS);

    xhr.upload.onprogress = () => {
      resetInactivityTimer();
    };

    xhr.onload = () => {
      settle(() => {
        resolve({
          ok: xhr.status >= 200 && xhr.status < 300,
          status: xhr.status,
          etag: xhr.getResponseHeader('ETag'),
        });
      });
    };

    xhr.onerror = () => {
      settle(() => {
        reject(new TypeError('Network error during upload'));
      });
    };

    xhr.open('PUT', url, true);
    resetInactivityTimer();
    xhr.send(chunk);
  });
}

/**
 * Upload a File/Blob in order to N presigned URLs as PUT chunks.
 *
 * @param urls     Ordered list of presigned PUT URLs (one per part).
 * @param file     The File or Blob to slice and upload.
 * @param partSize Byte size of each chunk; the final part may be shorter.
 * @param onProgress Optional callback invoked with the cumulative fraction
 *                 (0–1) after each chunk completes. Coarse (per-chunk).
 * @param options  Optional abort signal, per-part retry count, and a
 *                 best-effort missing-ETag cleanup hook.
 * @returns        ETag header values in the same order as `urls`.
 * @throws Error on a part that fails after all retries (with the 1-indexed
 *               part number and status), or AbortError if the signal fires.
 */
export async function uploadChunks(
  urls: string[],
  file: File | Blob,
  partSize: number,
  onProgress?: (fraction: number) => void,
  options: UploadChunksOptions = {},
): Promise<string[]> {
  const { signal, maxRetries = DEFAULT_MAX_RETRIES, onMissingEtag } = options;
  const etags: string[] = [];
  // Metadata only for the report buffer: filename (only known when the
  // caller passed a File, not a bare Blob) and the part index — never the
  // presigned URL itself (bearer-equivalent; unlike an Authorization header
  // it can't be scrubbed by key name) or the chunk body.
  const filename = file instanceof File ? file.name : undefined;
  const partLabel = (i: number) =>
    `presigned:put (part ${i + 1}/${urls.length})${filename ? ` — ${filename}` : ''}`;

  for (let i = 0; i < urls.length; i++) {
    const start = i * partSize;
    const end = Math.min(start + partSize, file.size);
    const chunk = file.slice(start, end);

    let attempt = 0;
    // Retry this part in place; earlier parts stay uploaded.
    for (;;) {
      if (signal?.aborted) {
        throw new DOMException('Aborted', 'AbortError');
      }
      try {
        const result = await putChunkXHR(urls[i], chunk, signal);
        if (result.ok) {
          const etag = result.etag;
          // A cross-origin PUT only exposes ETag when the bucket's CORS policy
          // lists it (ExposeHeaders). Pushing '' would reach S3 as an empty
          // part ETag, which the backend maps to a "session may have expired"
          // 502 that retrying cannot fix. Fail with the real cause instead.
          if (etag === null) {
            if (onMissingEtag) {
              // S3 already accepted this part: best-effort tell the backend to
              // abort the multipart upload so it is not left open consuming
              // storage. The missing-ETag error below is what the caller needs.
              await onMissingEtag().catch(() => {});
            }
            throw new UploadHttpError(
              i18n.t('common:errors.storageUploadMissingEtag', { part: i + 1 }),
            );
          }
          etags.push(etag);
          onProgress?.(end / file.size);
          break;
        }
        if (!isRetriableStatus(result.status) || attempt >= maxRetries) {
          reportNetworkError({ status: result.status, url: partLabel(i) });
          throw new UploadHttpError(
            i18n.t('common:errors.storageUploadPartFailed', {
              part: i + 1,
              status: result.status,
            }),
          );
        }
      } catch (err) {
        // A caller-initiated abort is terminal and not worth reporting.
        if (err instanceof DOMException && err.name === 'AbortError') throw err;
        // Already reported above; re-throw once retries are out.
        if (err instanceof UploadHttpError) throw err;
        // A network-layer error (TypeError) or timeout (UploadTimeoutError) is
        // retriable.
        if (attempt >= maxRetries) {
          reportNetworkError({ status: 0, url: partLabel(i) });
          throw new Error(
            i18n.t('common:errors.storageUploadPartRetriesFailed', {
              part: i + 1,
              attempts: maxRetries + 1,
            }),
          );
        }
      }
      attempt += 1;
      await delay(500 * 2 ** (attempt - 1), signal); // 500ms, 1s, 2s
    }
  }

  return etags;
}
