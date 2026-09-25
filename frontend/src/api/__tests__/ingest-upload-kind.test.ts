/** Every upload door carries the tileset `kind`, and none sends one for ordinary files. */
import { requestPresignedUpload, uploadFile, uploadFromUrl } from '@/api/ingest';

class CapturingXHR {
  static sent: FormData[] = [];
  status = 200;
  responseText = JSON.stringify({ job_id: 'job-1', status: 'pending' });
  upload = { onprogress: null as unknown };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  open() {}
  setRequestHeader() {}
  send(body: FormData) {
    CapturingXHR.sent.push(body);
    queueMicrotask(() => this.onload?.());
  }
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as Response;
}

describe('upload kind', () => {
  beforeEach(() => {
    CapturingXHR.sent = [];
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('adds kind=tiles3d to the multipart upload form', async () => {
    vi.stubGlobal('XMLHttpRequest', CapturingXHR);

    await uploadFile(new File(['PK'], 'campus.zip'), undefined, 'tiles3d');
    await uploadFile(new File(['{}'], 'parks.geojson'));

    expect(CapturingXHR.sent[0].get('kind')).toBe('tiles3d');
    expect(CapturingXHR.sent[1].has('kind')).toBe(false);
  });

  it('adds kind to the presigned upload request body', async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ job_id: 'job-1', urls: ['u'], s3_key: 'k', upload_id: null, part_size: null }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await requestPresignedUpload('campus.zip', 10, 'application/zip', 'tiles3d');
    await requestPresignedUpload('parks.geojson', 10);

    const bodies = fetchMock.mock.calls.map(
      (call) => JSON.parse((call as unknown as [string, RequestInit])[1].body as string),
    );
    expect(bodies[0]).toMatchObject({ filename: 'campus.zip', kind: 'tiles3d' });
    expect(bodies[1]).not.toHaveProperty('kind');
  });

  it('adds kind to the URL import request body', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ job_id: 'job-1', status: 'running' }));
    vi.stubGlobal('fetch', fetchMock);

    await uploadFromUrl('https://files.example.test/campus.3tz', undefined, 'tiles3d');
    await uploadFromUrl('https://files.example.test/parks.geojson', undefined, null);

    const bodies = fetchMock.mock.calls.map(
      (call) => JSON.parse((call as unknown as [string, RequestInit])[1].body as string),
    );
    expect(bodies[0]).toEqual({ url: 'https://files.example.test/campus.3tz', kind: 'tiles3d' });
    expect(bodies[1]).toEqual({ url: 'https://files.example.test/parks.geojson' });
  });
});
