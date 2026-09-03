import i18n from '@/i18n/i18n';
import { reportNetworkError } from '@/lib/report';

/**
 * Shared chunked-PUT helper for presigned S3 multipart uploads.
 *
 * Extracted from the identical loops previously duplicated in
 * `ingest.ts` and `datasets.ts` (INGEST-AUDIT P2-05).
 *
 * XHR, not `fetch`, is what PUTs each part — see the per-part timeout
 * comment below for why. Presigned URLs are pre-signed by the backend and
 * must not carry the session JWT (S3 rejects extra Authorization headers
 * on V4-signed URLs), so no auth header is ever attached here.
 */

export interface UploadChunksOptions {
  /**
   * fix(#438): DATA-02 — cancel a runaway multi-GB upload. Aborting rejects the
   * in-flight part's XHR; the loop then throws the AbortError without starting
   * the next part.
   */
  signal?: AbortSignal;
  /**
   * fix(#438): DATA-02 — retry a failed part instead of discarding the whole
   * upload. One transient blip on part k of n used to throw and lose every part
   * already uploaded. Retries apply per part, so earlier parts are never re-sent.
   */
  maxRetries?: number;
  /**
   * fix(review #1800 P2 round 3): called (best-effort, errors swallowed)
   * before throwing on a missing ETag. S3 already accepted this part — and
   * possibly earlier ones — so without this the multipart upload is never
   * told to stop, leaving it open and consuming storage on every retry.
   * The caller supplies whatever "complete with no parts" call its own
   * completion endpoint expects (`completePresignedUpload(jobId)` /
   * `completePresignedReupload(datasetId, jobId)`, both defaulting `parts`
   * to `[]`); the backend's existing failed-completion path (the same one
   * a genuine completion failure already goes through) treats an empty
   * parts list as abandonment and aborts the multipart upload from it.
   */
  onMissingEtag?: () => Promise<unknown>;
}

const DEFAULT_MAX_RETRIES = 3;

/**
 * fix(review #1800 P2 round 3): `AbortSignal.timeout()` is a WALL-CLOCK
 * deadline, not a stall detector — it fires at a fixed elapsed time
 * regardless of whether bytes are still moving. A part at the backend's
 * credited minimum upload rate can legitimately take longer than that
 * fixed deadline while actively progressing the whole time, so the old
 * `PART_STALL_TIMEOUT_MS` (a flat 300s) aborted a live, working upload on
 * every attempt, forever, before it could ever finish. `fetch` also has no
 * upload-progress signal to tell a genuine stall (zero bytes moving) apart
 * from a slow-but-live one, so the per-part PUT moved to XHR, whose
 * `upload.onprogress` fires on every chunk actually sent and lets the
 * timeout below reset on real activity instead of the wall clock.
 *
 * Two independent bounds:
 *
 *  - INACTIVITY_TIMEOUT_MS: no upload.onprogress event within this window
 *    means the connection is genuinely stalled — a live connection, even
 *    an extremely slow one, sends SOME bytes well inside it. 60s is
 *    generous for a scheduling hiccup or a brief network blip while still
 *    recovering a truly dead connection promptly. Reset on every progress
 *    event, so a slow-but-progressing part is never aborted by this alone.
 *
 *  - PART_CEILING_MS: an ABSOLUTE bound even while progress keeps
 *    resetting the inactivity timer above — defense in depth against a
 *    connection so slow it would otherwise run indefinitely. Derived from
 *    the largest possible part (PART_SIZE_UPPER_BOUND_BYTES — 10 MiB,
 *    matching the backend's multipart PART_SIZE) at the backend's credited
 *    minimum upload rate (MIN_UPLOAD_RATE_BYTES_PER_SEC — 32 KiB/s):
 *    10 MiB / 32 KiB/s = 320s, with a 1.5x margin (≈480s) to absorb normal
 *    rate variance and the retry backoff between attempts.
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
 * named 'AbortError' — that name is reserved for a CALLER-initiated abort
 * (via `signal`), which the loop below treats as terminal and non-retriable.
 * A stalled connection is the opposite: exactly the kind of failure a retry
 * can plausibly recover from, so this falls through to the existing
 * network-layer-error branch instead of a new one.
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
          // fix(#1778): a cross-origin PUT only exposes ETag when the bucket's
          // CORS policy lists it (ExposeHeaders). Pushing '' here used to
          // reach S3's complete_multipart_upload with an empty part ETag,
          // which the backend maps to a "session may have expired" 502 — a
          // message that can never be fixed by retrying. Fail with the real
          // cause instead: the bucket is missing ExposeHeaders: ETag.
          if (etag === null) {
            if (onMissingEtag) {
              // fix(review #1800 P2 round 3): S3 already accepted this part
              // (and possibly earlier ones) — best-effort tell the backend
              // to abort the multipart upload before throwing, so it is not
              // left open consuming storage on every retry. The missing-ETag
              // error below is what the caller needs; this cleanup call's
              // own outcome is not.
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
        // A caller-initiated abort is terminal, not a retriable failure — and
        // not a problem to report.
        if (err instanceof DOMException && err.name === 'AbortError') throw err;
        // A non-retriable HTTP status threw (and was already reported) above;
        // re-throw once retries are out.
        if (err instanceof UploadHttpError) throw err;
        // Otherwise it is a network-layer error (TypeError) or a timeout
        // (UploadTimeoutError, deliberately not named AbortError above) —
        // both retriable.
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

/**
 * Minimal self-check. Run with:
 *   npx vitest run src/api/__tests__/presigned-upload.test.ts
 * (the assertions live there; this comment documents the contract).
 */
