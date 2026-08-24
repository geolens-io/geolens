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
 */
import { clearReportEntries, getReportEntries } from '@/lib/report';
import { previewFile, uploadFile, uploadPresigned } from '@/api/ingest';

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

describe('upload-path report capture', () => {
  beforeEach(() => {
    clearReportEntries();
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

  it('(d) captures a multipart presigned PUT failure with the failing part number', async () => {
    const part1 = 'https://storage.example.com/bucket/key?partNumber=1&X-Amz-Signature=SIG1';
    const part2 = 'https://storage.example.com/bucket/key?partNumber=2&X-Amz-Signature=SIG2';
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url === part1) return { ok: true, status: 200, headers: new Headers({ ETag: 'e1' }) } as Response;
        // Non-retriable status — fails immediately, no backoff delay to wait out.
        if (url === part2) return { ok: false, status: 403, headers: new Headers() } as Response;
        return jsonResponse(200, {
          job_id: 'job-2',
          urls: [part1, part2],
          s3_key: 'k',
          upload_id: 'multipart-1',
          part_size: 5,
        });
      }),
    );

    await expect(
      uploadPresigned(new File(['aaaaaaaaaa'], 'big.tif')),
    ).rejects.toBeTruthy();

    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].source).toBe('network');
    expect(entries[0].message).toContain('403');
    expect(entries[0].message).toContain('part 2/2');
    expect(entries[0].message).toContain('big.tif');
    expect(entries[0].message).not.toContain('SIG2');
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
});
