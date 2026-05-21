/**
 * Shared chunked-PUT helper for presigned S3 multipart uploads.
 *
 * Extracted from the identical loops previously duplicated in
 * `ingest.ts` and `datasets.ts` (INGEST-AUDIT P2-05). A single
 * canonical location for future retry-on-ETag-mismatch /
 * exponential backoff / abort-signal work.
 *
 * Plain `fetch` is correct here — presigned URLs are pre-signed by
 * the backend and must not carry the session JWT (S3 rejects extra
 * Authorization headers on V4-signed URLs).
 */

/**
 * Upload a File/Blob in order to N presigned URLs as PUT chunks.
 *
 * @param urls     Ordered list of presigned PUT URLs (one per part).
 * @param file     The File or Blob to slice and upload.
 * @param partSize Byte size of each chunk; the final part may be shorter.
 * @returns        ETag header values in the same order as `urls`.
 *                 An empty string is returned for any part whose response
 *                 omitted the ETag header (preserves prior behaviour).
 * @throws Error on the first non-2xx response, with the offending
 *               part number (1-indexed) and status code in the message.
 */
export async function uploadChunks(
  urls: string[],
  file: File | Blob,
  partSize: number,
): Promise<string[]> {
  const etags: string[] = [];

  for (let i = 0; i < urls.length; i++) {
    const start = i * partSize;
    const end = Math.min(start + partSize, file.size);
    const chunk = file.slice(start, end);
    const resp = await fetch(urls[i], { method: 'PUT', body: chunk });
    if (!resp.ok) {
      throw new Error(`S3 part ${i + 1} upload failed: ${resp.status}`);
    }
    etags.push(resp.headers.get('ETag') ?? '');
  }

  return etags;
}
