/**
 * A presigned single-PUT URL is signed for one content type. The presign
 * request and the PUT must name the same value, and fetch sends no
 * Content-Type at all for a Blob whose type is empty (GeoPackage, COPC .laz,
 * .3tz, FlatGeobuf, Parquet), so the client names the fallback itself.
 */
import { uploadPresigned } from '@/api/ingest';
import { reuploadPresigned } from '@/api/datasets';

const PUT_URL = 'https://storage.example.test/bucket/key?X-Amz-Signature=abc';

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as Response;
}

function stubStorageFetch() {
  const fetchMock = vi.fn(async (url: string) => {
    if (url === PUT_URL) return { ok: true, status: 200 } as Response;
    if (url.endsWith('/complete')) return jsonResponse({ job_id: 'job-1', status: 'pending' });
    return jsonResponse({ job_id: 'job-1', urls: [PUT_URL], s3_key: 'k', upload_id: null, part_size: null });
  });
  vi.stubGlobal('fetch', fetchMock);

  const calls = () => fetchMock.mock.calls as unknown as [string, RequestInit][];
  return {
    presignBody: () => JSON.parse(calls()[0][1].body as string),
    putInit: () => calls().find(([url]) => url === PUT_URL)![1],
  };
}

const doors = [
  { name: 'upload', run: (file: File) => uploadPresigned(file) },
  { name: 'reupload', run: (file: File) => reuploadPresigned('ds-1', file) },
];

describe.each(doors)('presigned $name content type', ({ run }) => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('requests and PUTs application/octet-stream when the browser gives no type', async () => {
    const storage = stubStorageFetch();

    await run(new File(['GPKG'], 'parks.gpkg'));

    expect(storage.presignBody().content_type).toBe('application/octet-stream');
    expect(storage.putInit().headers).toEqual({ 'Content-Type': 'application/octet-stream' });
  });

  it('passes a known type through unchanged to the request and the PUT', async () => {
    const storage = stubStorageFetch();

    await run(new File(['II*'], 'dem.tif', { type: 'image/tiff' }));

    expect(storage.presignBody().content_type).toBe('image/tiff');
    expect(storage.putInit().headers).toEqual({ 'Content-Type': 'image/tiff' });
  });
});
