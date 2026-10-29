import {
  MAX_CONCURRENT_READS,
  MAX_LOAD_BYTES,
  MAX_LOAD_READS,
  MAX_RANGE_BYTES,
  MAX_RETRIES,
} from './copc-limits';
import { createSlotPool } from '@/lib/slot-pool';

type DatasetFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

const RETRY_BASE_MS = 500;
const MAX_RETRY_DELAY_MS = 10_000;

function retryDelay(response: Response, attempt: number): number {
  const seconds = Number(response.headers.get('Retry-After'));
  const requested = Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : RETRY_BASE_MS * 2 ** attempt;
  return Math.min(requested, MAX_RETRY_DELAY_MS);
}

/**
 * A range reader for the `copc` package over the guarded dataset fetch.
 *
 * Reads are validated before any request: whole-number offsets, at most
 * MAX_RANGE_BYTES, inside the file's recorded size, and within a per-load
 * read and byte budget, so a header that declares absurd VLR or page sizes
 * cannot drive a long or huge fetch. At most MAX_CONCURRENT_READS run at once,
 * a 429 or 503 backs off (honouring Retry-After) and retries, and the
 * answer must be a 206 of exactly the requested length.
 */
export function makeRangeGetter(
  datasetFetch: DatasetFetch,
  url: string,
  fileSize: number | null,
  signal?: AbortSignal,
): (begin: number, end: number) => Promise<Uint8Array> {
  let reads = 0;
  let bytes = 0;
  const slots = createSlotPool(MAX_CONCURRENT_READS);

  return async (begin, end) => {
    if (!Number.isSafeInteger(begin) || !Number.isSafeInteger(end) || begin < 0 || end <= begin) {
      throw new Error('COPC read refused: invalid range');
    }
    // The copc package opens a file with a fixed head read, which a small file
    // answers short: clamp to the recorded size instead of refusing it.
    const readEnd = fileSize === null ? end : Math.min(end, fileSize);
    if (readEnd <= begin) throw new Error('COPC read refused: range outside the file');
    const length = readEnd - begin;
    if (length > MAX_RANGE_BYTES) throw new Error('COPC read refused: range too large');
    reads += 1;
    bytes += length;
    if (reads > MAX_LOAD_READS || bytes > MAX_LOAD_BYTES) throw new Error('COPC read refused: load budget exceeded');

    const release = await slots.acquire();
    try {
      for (let attempt = 0; ; attempt++) {
        if (signal?.aborted) throw new Error('COPC read aborted');
        const response = await datasetFetch(url, { headers: { Range: `bytes=${begin}-${readEnd - 1}` }, signal });
        if ((response.status === 429 || response.status === 503) && attempt < MAX_RETRIES) {
          await new Promise((resolve) => setTimeout(resolve, retryDelay(response, attempt)));
          continue;
        }
        if (response.status !== 206) throw new Error(`COPC range read answered ${response.status}`);
        const declared = Number(response.headers.get('Content-Length'));
        if (Number.isFinite(declared) && declared > length) throw new Error('COPC range answer larger than requested');
        const body = new Uint8Array(await response.arrayBuffer());
        if (body.byteLength !== length) throw new Error('COPC range answer has the wrong length');
        return body;
      }
    } finally {
      release();
    }
  };
}
