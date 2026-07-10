/**
 * Shared chunked-PUT helper for presigned S3 multipart uploads.
 *
 * Extracted from the identical loops previously duplicated in
 * `ingest.ts` and `datasets.ts` (INGEST-AUDIT P2-05).
 *
 * Plain `fetch` is correct here — presigned URLs are pre-signed by
 * the backend and must not carry the session JWT (S3 rejects extra
 * Authorization headers on V4-signed URLs).
 */

export interface UploadChunksOptions {
  /**
   * fix(#438): DATA-02 — cancel a runaway multi-GB upload. Aborting rejects the
   * in-flight part's fetch; the loop then throws the AbortError without starting
   * the next part.
   */
  signal?: AbortSignal;
  /**
   * fix(#438): DATA-02 — retry a failed part instead of discarding the whole
   * upload. One transient blip on part k of n used to throw and lose every part
   * already uploaded. Retries apply per part, so earlier parts are never re-sent.
   */
  maxRetries?: number;
}

const DEFAULT_MAX_RETRIES = 3;

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

/**
 * Upload a File/Blob in order to N presigned URLs as PUT chunks.
 *
 * @param urls     Ordered list of presigned PUT URLs (one per part).
 * @param file     The File or Blob to slice and upload.
 * @param partSize Byte size of each chunk; the final part may be shorter.
 * @param onProgress Optional callback invoked with the cumulative fraction
 *                 (0–1) after each chunk completes. Coarse (per-chunk).
 * @param options  Optional abort signal and per-part retry count.
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
  const { signal, maxRetries = DEFAULT_MAX_RETRIES } = options;
  const etags: string[] = [];

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
        const resp = await fetch(urls[i], { method: 'PUT', body: chunk, signal });
        if (resp.ok) {
          etags.push(resp.headers.get('ETag') ?? '');
          onProgress?.(end / file.size);
          break;
        }
        if (!isRetriableStatus(resp.status) || attempt >= maxRetries) {
          throw new Error(`S3 part ${i + 1} upload failed: ${resp.status}`);
        }
      } catch (err) {
        // A caller-initiated abort is terminal, not a retriable failure.
        if (err instanceof DOMException && err.name === 'AbortError') throw err;
        // A non-retriable HTTP status threw above; re-throw once retries are out.
        if (err instanceof Error && err.message.startsWith('S3 part')) throw err;
        // Otherwise it is a network-layer error (TypeError) — retriable.
        if (attempt >= maxRetries) {
          throw new Error(`S3 part ${i + 1} upload failed after ${maxRetries + 1} attempts`);
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
