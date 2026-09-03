/**
 * The upload path bypasses TanStack entirely: UploadForm calls uploadFile /
 * uploadPresigned / previewFile directly from a plain try/catch (per-file
 * progress needs granular state a shared mutation can't give it), so none of
 * these failures ever reached the shared MutationCache.onError tap that feeds
 * the problem-reporter buffer in main.tsx. A file could fail to stage or
 * detect with nothing recorded anywhere a user could report.
 *
 * Tests that each failure class now lands a redacted entry in the report
 * buffer via the existing reportNetworkError tap — metadata only (status,
 * error text, filename), never the file body or a presigned URL's signature:
 * (a) direct-POST upload failure (uploadFile / xhrUpload)
 * (b) presign-request failure (uploadPresigned, step 1)
 * (c) single-part presigned PUT failure (uploadPresigned, step 2)
 * (d) multipart presigned PUT failure (uploadPresigned → uploadChunks)
 * (e) preview/detection failure (previewFile)
 * (f) a redaction-worthy error detail is scrubbed the same as any other entry
 *
 * codex on #1660 found the same gap class at three more sites — a failure
 * path that flips a staged file's row to 'upload-failed'/'commit-failed'
 * (and so shows the report CTA) without writing a buffer entry:
 * (g) commitImport failure (no capture existed here at all, unlike (a)/(e))
 * (h) commitFanOut failure (same — a different API module, same gap)
 * (i) a 2xx response with a malformed JSON body on the direct-POST upload
 *     (xhrUpload's final JSON.parse, outside the status-based reporting)
 * (j) a non-ApiError preview rejection (apiFetch's own response.json()
 *     parse failure isn't an ApiError, so the old `instanceof` guard skipped it)
 *
 * codex round 3 on #1660: commitFanOut can return HTTP 200 with
 * results[].status === 'failed' for one or more layers — not a transport
 * failure, so reportNetworkError doesn't apply, but UploadForm still maps
 * that to a commit-failed row (showing the report CTA) with nothing about
 * WHICH layer failed or WHY ever written to the buffer:
 * (k) a mixed 200 (some layers failed) writes one entry per failed layer
 * (l) an all-success 200 writes nothing
 */
import { clearReportEntries, getReportEntries } from '@/lib/report';
import { commitImport, previewFile, uploadFile, uploadPresigned } from '@/api/ingest';
import { commitFanOut } from '@/api/datasets';

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

class FakeXHR {
  static respond: { status: number; body: string } = { status: 500, body: '{}' };
  status = 0;
  responseText = '';
  upload = { onprogress: null as unknown };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  open() {}
  setRequestHeader() {}
  send() {
    this.status = FakeXHR.respond.status;
    this.responseText = FakeXHR.respond.body;
    queueMicrotask(() => this.onload?.());
  }
}

// fix(review #1800 P2 round 3): uploadChunks' per-part PUT moved to XHR —
// URL-aware so test (d) can drive two concurrent-in-flight-order parts by
// which presigned URL each XHR instance was opened against.
class PartXHR {
  static instances: PartXHR[] = [];
  static forUrl(url: string): PartXHR | undefined {
    return PartXHR.instances.find((x) => x.url === url);
  }

  url = '';
  status = 0;
  upload: { onprogress: ((e: unknown) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private headers: Record<string, string> = {};

  open(_method: string, url: string) {
    this.url = url;
    PartXHR.instances.push(this);
  }
  send() {}
  abort() {}
  getResponseHeader(name: string): string | null {
    return this.headers[name] ?? null;
  }
  respond(status: number, headers: Record<string, string> = {}) {
    this.status = status;
    this.headers = headers;
    this.onload?.();
  }
}

describe('upload-path report capture', () => {
  beforeEach(() => {
    clearReportEntries();
    PartXHR.instances = [];
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('(a) captures a direct-POST upload failure with filename, never the file body', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    FakeXHR.respond = { status: 500, body: JSON.stringify({ detail: 'Unsupported file type' }) };

    const secretRow = 'ROW-CONTENT-471,parcel,42.0,-71.0';
    await expect(
      uploadFile(new File([secretRow], 'parcels.csv', { type: 'text/csv' })),
    ).rejects.toMatchObject({ status: 500 });

    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].source).toBe('network');
    expect(entries[0].severity).toBe('error'); // 5xx
    expect(entries[0].message).toContain('500');
    expect(entries[0].message).toContain('parcels.csv');
    // Metadata only — the uploaded row content must never reach the buffer.
    expect(entries[0].message).not.toContain(secretRow);
    expect(entries[0].detail ?? '').not.toContain(secretRow);
  });

  it('(b) captures a presign-request failure (step 1 of uploadPresigned)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(422, { detail: 'File size exceeds the configured limit' })),
    );

    await expect(
      uploadPresigned(new File(['x'], 'big-parcels.gpkg')),
    ).rejects.toBeTruthy();

    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].source).toBe('network');
    expect(entries[0].message).toContain('422');
    expect(entries[0].message).toContain('presigned:request');
    expect(entries[0].message).toContain('big-parcels.gpkg');
  });

  it('(c) captures a single-part presigned PUT failure without leaking the signed URL', async () => {
    const signedUrl = 'https://storage.example.com/bucket/key?X-Amz-Signature=SECRETSIG&X-Amz-Credential=AKIDEXAMPLE';
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url === signedUrl) {
          return { ok: false, status: 403 } as Response;
        }
        return jsonResponse(200, {
          job_id: 'job-1',
          urls: [signedUrl],
          s3_key: 'k',
          upload_id: null,
          part_size: null,
        });
      }),
    );

    await expect(uploadPresigned(new File(['x'], 'parcels.gpkg'))).rejects.toBeTruthy();

    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].source).toBe('network');
    expect(entries[0].message).toContain('403');
    expect(entries[0].message).toContain('presigned:put');
    expect(entries[0].message).toContain('parcels.gpkg');
    // The presigned URL carries a time-limited access signature — never log it.
    expect(entries[0].message).not.toContain('SECRETSIG');
    expect(entries[0].message).not.toContain('X-Amz-Signature');
  });

  // fix(review #1800 P2 round 3): the per-part PUT moved from `fetch` to
  // XHR (see _presignedUpload.ts) — the presign-request JSON call still
  // goes through apiFetch/fetch, but each part PUT now needs an XHR mock.
  it('(d) captures a multipart presigned PUT failure with the failing part number', async () => {
    const part1 = 'https://storage.example.com/bucket/key?partNumber=1&X-Amz-Signature=SIG1';
    const part2 = 'https://storage.example.com/bucket/key?partNumber=2&X-Amz-Signature=SIG2';
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(200, {
          job_id: 'job-2',
          urls: [part1, part2],
          s3_key: 'k',
          upload_id: 'multipart-1',
          part_size: 5,
        }),
      ),
    );
    vi.stubGlobal('XMLHttpRequest', PartXHR);

    const promise = uploadPresigned(new File(['aaaaaaaaaa'], 'big.tif'));
    promise.catch(() => {});

    await vi.waitFor(() => expect(PartXHR.forUrl(part1)).toBeDefined());
    PartXHR.forUrl(part1)!.respond(200, { ETag: 'e1' });
    await vi.waitFor(() => expect(PartXHR.forUrl(part2)).toBeDefined());
    // Non-retriable status — fails immediately, no backoff delay to wait out.
    PartXHR.forUrl(part2)!.respond(403);

    await expect(promise).rejects.toBeTruthy();

    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].source).toBe('network');
    expect(entries[0].message).toContain('403');
    expect(entries[0].message).toContain('part 2/2');
    expect(entries[0].message).toContain('big.tif');
    expect(entries[0].message).not.toContain('SIG2');
  });

  // fix(review #1800 P2 round 3): S3 accepting a part with no ETag exposed
  // (a bucket CORS misconfiguration) used to throw straight out of
  // uploadPresigned, leaving the multipart upload open server-side on
  // every retry — the completion endpoint's own abort-on-empty-parts path
  // was never reached because uploadPresigned never called /complete at
  // all in that case. uploadPresigned now wires uploadChunks'
  // onMissingEtag hook to `completePresignedUpload(job_id)` (parts
  // omitted, defaulting to `[]`), which is exactly the "failed
  // completion" shape the backend already aborts on.
  it('calls the presigned-complete endpoint with no parts (the abort path) exactly once when ETag is absent', async () => {
    const part1 = 'https://storage.example.com/bucket/key?partNumber=1&X-Amz-Signature=SIG1';
    const completeCalls: unknown[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url.endsWith('/complete')) {
          completeCalls.push(init?.body ? JSON.parse(init.body as string) : null);
          // Mirrors the backend: no parts is a 400, not a success.
          return jsonResponse(400, { detail: 'Multipart upload completion requires at least one uploaded part' });
        }
        return jsonResponse(200, {
          job_id: 'job-3',
          urls: [part1],
          s3_key: 'k',
          upload_id: 'multipart-2',
          part_size: 5,
        });
      }),
    );
    vi.stubGlobal('XMLHttpRequest', PartXHR);

    const promise = uploadPresigned(new File(['aaaaaaaaaa'], 'big.tif'));
    promise.catch(() => {});

    await vi.waitFor(() => expect(PartXHR.forUrl(part1)).toBeDefined());
    // 2xx, but no ETag header — the CORS-misconfigured-bucket case.
    PartXHR.forUrl(part1)!.respond(200);

    await expect(promise).rejects.toThrow(/ETag/);
    expect(completeCalls).toEqual([{ parts: [] }]);
  });

  it('(e) captures a preview/detection failure, dropping the job id from the reported path', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(422, { detail: 'Could not determine a coordinate reference system' })),
    );

    await expect(previewFile('job-abc-123')).rejects.toBeTruthy();

    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].source).toBe('network');
    expect(entries[0].message).toContain('422');
    expect(entries[0].message).toContain('/ingest/preview');
    // The job id is a parameter, not a namespace — dropped like reportQueryKey
    // drops ids in main.tsx.
    expect(entries[0].message).not.toContain('job-abc-123');
  });

  it('(f) redacts a credential in the captured error detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(400, { detail: 'Rejected: api_key=SUPERSECRET123 is not permitted in uploads' }),
      ),
    );

    await expect(previewFile('job-1')).rejects.toBeTruthy();

    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].detail ?? '').not.toContain('SUPERSECRET123');
  });

  it('(g) captures a commitImport failure (a class codex found uncaptured entirely)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(500, { detail: 'Dispatch failed' })),
    );

    await expect(
      commitImport('job-1', { title: 'Parcels' }),
    ).rejects.toBeTruthy();

    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].source).toBe('network');
    expect(entries[0].message).toContain('500');
    expect(entries[0].message).toContain('/ingest/commit');
    expect(entries[0].message).not.toContain('job-1');
  });

  it('(h) captures a commitFanOut failure (same gap, different API module)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(502, { detail: 'Bad gateway' })),
    );

    await expect(
      commitFanOut('job-1', [{ layer_name: 'a' }, { layer_name: 'b' }]),
    ).rejects.toBeTruthy();

    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].source).toBe('network');
    expect(entries[0].message).toContain('502');
    expect(entries[0].message).toContain('/ingest/commit-fan-out');
  });

  it('(i) captures a malformed-JSON 2xx body on the direct-POST upload', async () => {
    class MalformedJsonXHR {
      status = 0;
      responseText = '';
      upload = { onprogress: null as unknown };
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      open() {}
      setRequestHeader() {}
      send() {
        this.status = 200;
        // Truncated body — valid HTTP 200, invalid JSON. The old code's
        // status-based branch (`res.status < 200 || res.status >= 300`)
        // never runs for a 2xx, so JSON.parse threw completely uncaptured.
        this.responseText = '{"job_id": "job-1"';
        queueMicrotask(() => this.onload?.());
      }
    }
    vi.stubGlobal('XMLHttpRequest', MalformedJsonXHR);

    await expect(
      uploadFile(new File(['x'], 'parcels.csv')),
    ).rejects.toBeTruthy();

    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].source).toBe('network');
    expect(entries[0].message).toContain('200');
    expect(entries[0].message).toContain('parcels.csv');
  });

  it('(j) captures a non-ApiError preview rejection (malformed 2xx JSON)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        // apiFetch calls response.json() directly; a malformed body throws a
        // raw SyntaxError here, never an ApiError.
        json: () => Promise.reject(new SyntaxError('Unexpected end of JSON input')),
      }) as unknown as Response),
    );

    await expect(previewFile('job-1')).rejects.toBeInstanceOf(SyntaxError);

    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].source).toBe('network');
    // No HTTP error status exists for this failure — reported as status 0,
    // the same convention xhrUpload's network-layer catch uses.
    expect(entries[0].message).toContain('/ingest/preview');
  });

  it('(k) a mixed 200 from commitFanOut writes one entry per failed layer', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(200, {
          fan_out_id: 'job-1',
          results: [
            { layer_name: 'roads', new_job_id: 'j2', dataset_id: null, status: 'queued', error: null },
            {
              layer_name: 'parcels',
              new_job_id: null,
              dataset_id: null,
              status: 'failed',
              error: 'Dispatch failed: queue unavailable',
            },
            {
              layer_name: 'rivers',
              new_job_id: null,
              dataset_id: null,
              status: 'failed',
              error: 'Dispatch failed: queue unavailable',
            },
          ],
        }),
      ),
    );

    const response = await commitFanOut('job-1', [
      { layer_name: 'roads' },
      { layer_name: 'parcels' },
      { layer_name: 'rivers' },
    ]);
    expect(response.results).toHaveLength(3);

    const entries = getReportEntries();
    // Two failed layers, byte-identical error text — still two entries, not
    // one deduped row, because each message names its own layer.
    expect(entries).toHaveLength(2);
    for (const entry of entries) {
      expect(entry.source).toBe('network');
      expect(entry.severity).toBe('error');
      expect(entry.detail).toContain('Dispatch failed: queue unavailable');
    }
    expect(entries.some((e) => e.message.includes('parcels'))).toBe(true);
    expect(entries.some((e) => e.message.includes('rivers'))).toBe(true);
    // The queued layer wrote nothing.
    expect(entries.some((e) => e.message.includes('roads'))).toBe(false);
  });

  it('(l) an all-success 200 from commitFanOut writes nothing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(200, {
          fan_out_id: 'job-1',
          results: [
            { layer_name: 'roads', new_job_id: 'j2', dataset_id: null, status: 'queued', error: null },
            { layer_name: 'parcels', new_job_id: 'j3', dataset_id: null, status: 'queued', error: null },
          ],
        }),
      ),
    );

    await commitFanOut('job-1', [{ layer_name: 'roads' }, { layer_name: 'parcels' }]);

    expect(getReportEntries()).toHaveLength(0);
  });
});
