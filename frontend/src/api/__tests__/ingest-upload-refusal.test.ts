/**
 * An upload or reupload door's 422 is hand-composed prose for the person who
 * submitted the file (an unsafe archive, a disallowed extension). Every door
 * shows it verbatim when this table doesn't otherwise recognize it, instead
 * of collapsing to the generic "submitted values are invalid" fallback.
 */
import { requestPresignedUpload, uploadFile, uploadFromUrl } from '@/api/ingest';
import { requestPresignedReupload } from '@/api/datasets';
import { ApiError } from '@/api/client';

class CapturingXHR {
  status = 422;
  responseText = JSON.stringify({
    detail: 'Archive contains a path outside the tileset root: ../secrets.txt',
  });
  upload = { onprogress: null as unknown };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  open() {}
  setRequestHeader() {}
  send() {
    queueMicrotask(() => this.onload?.());
  }
}

function errorResponse(status: number, detail: unknown): Response {
  return {
    ok: false,
    status,
    json: () => Promise.resolve({ detail }),
  } as Response;
}

describe('upload and reupload doors show an unmapped 422 detail verbatim', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('the multipart upload door (xhrUpload) shows the refusal verbatim', async () => {
    vi.stubGlobal('XMLHttpRequest', CapturingXHR);

    await expect(uploadFile(new File(['PK'], 'campus.zip'))).rejects.toThrow(
      'Archive contains a path outside the tileset root: ../secrets.txt',
    );
  });

  it('the presigned upload door shows the refusal verbatim', async () => {
    const detail = "A member of this archive uses a compression method GeoLens does not support: bzip2.";
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(422, detail)));

    await expect(requestPresignedUpload('campus.zip', 10)).rejects.toThrow(detail);
  });

  it('the presigned reupload door shows the refusal verbatim', async () => {
    const detail = 'This archive has no tileset.json at its root.';
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(422, detail)));

    await expect(requestPresignedReupload('ds-1', 'campus.zip', 10)).rejects.toThrow(detail);
  });

  it('still translates a 422 this table already recognizes, rather than showing it verbatim', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => errorResponse(422, 'Dataset quota exceeded: 5 of 5 datasets used')),
    );

    await expect(requestPresignedUpload('campus.zip', 10)).rejects.toThrow(
      'Dataset quota exceeded: 5 of 5 datasets used.',
    );
  });

  it('still translates a Pydantic validation array rather than rendering it', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => errorResponse(422, [{ loc: ['body', 'filename'], type: 'missing' }])),
    );

    const err = await requestPresignedUpload('campus.zip', 10).catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).not.toContain('missing');
    expect((err as ApiError).message).toContain('filename');
  });
});

describe('the doors show a 400 extension refusal verbatim', () => {
  const detail = "File extension '.exe' not allowed. Allowed: ['.zip', '.geojson']";

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('the multipart upload door (xhrUpload) shows the extension refusal verbatim', async () => {
    class ExtensionRefusalXHR extends CapturingXHR {
      status = 400;
      responseText = JSON.stringify({ detail });
    }
    vi.stubGlobal('XMLHttpRequest', ExtensionRefusalXHR);

    await expect(uploadFile(new File(['MZ'], 'malware.exe'))).rejects.toThrow(detail);
  });

  it('the presigned upload door shows the extension refusal verbatim', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(400, detail)));

    await expect(requestPresignedUpload('malware.exe', 10)).rejects.toThrow(detail);
  });

  it('the URL import door shows the extension refusal verbatim', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => errorResponse(400, detail)));

    await expect(uploadFromUrl('https://example.test/malware.exe')).rejects.toThrow(detail);
  });
});

describe('a transport failure keeps its own message rather than a refusal one', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('a status-0 network failure on the presigned upload door keeps "network unavailable"', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));

    await expect(requestPresignedUpload('campus.zip', 10)).rejects.toThrow(
      'Network unavailable. Check your connection.',
    );
  });

  it('a timeout on the presigned upload door keeps its own message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new DOMException('The operation was aborted', 'TimeoutError');
    }));

    await expect(requestPresignedUpload('campus.zip', 10)).rejects.toThrow(
      'The request took too long. Try again.',
    );
  });

  it('the multipart upload door (xhrUpload) keeps its own message on a network failure', async () => {
    class NetworkFailureXHR extends CapturingXHR {
      open() {}
      send() {
        queueMicrotask(() => this.onerror?.());
      }
    }
    vi.stubGlobal('XMLHttpRequest', NetworkFailureXHR);

    await expect(uploadFile(new File(['PK'], 'campus.zip'))).rejects.toThrow(
      'Network unavailable. Check your connection.',
    );
  });
});
