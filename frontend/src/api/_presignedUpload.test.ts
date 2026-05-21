import { uploadChunks } from './_presignedUpload';

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function putResponse(etag: string | null, status = 200): Response {
  const headers = new Headers();
  if (etag !== null) headers.set('ETag', etag);
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Bad Request',
    headers,
    json: () => Promise.reject(new Error('not used')),
  } as Response;
}

describe('uploadChunks', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns ETags in order for a 3-chunk upload', async () => {
    mockFetch
      .mockResolvedValueOnce(putResponse('"etag-1"'))
      .mockResolvedValueOnce(putResponse('"etag-2"'))
      .mockResolvedValueOnce(putResponse('"etag-3"'));

    const file = new Blob(['aaaabbbbccc']); // 11 bytes
    const urls = ['https://s3/u1', 'https://s3/u2', 'https://s3/u3'];
    const etags = await uploadChunks(urls, file, 4);

    expect(etags).toEqual(['"etag-1"', '"etag-2"', '"etag-3"']);
    expect(mockFetch).toHaveBeenCalledTimes(3);
    expect(mockFetch).toHaveBeenNthCalledWith(1, urls[0], expect.objectContaining({ method: 'PUT' }));
    expect(mockFetch).toHaveBeenNthCalledWith(2, urls[1], expect.objectContaining({ method: 'PUT' }));
    expect(mockFetch).toHaveBeenNthCalledWith(3, urls[2], expect.objectContaining({ method: 'PUT' }));
  });

  it('PUTs the correct slice of the input file as each chunk body', async () => {
    mockFetch
      .mockResolvedValueOnce(putResponse('"e1"'))
      .mockResolvedValueOnce(putResponse('"e2"'))
      .mockResolvedValueOnce(putResponse('"e3"'));

    // 11 bytes; partSize=4 yields slices "aaaa", "bbbb", "ccc".
    const file = new Blob(['aaaabbbbccc']);
    const urls = ['u1', 'u2', 'u3'];
    await uploadChunks(urls, file, 4);

    const bodies = await Promise.all(
      mockFetch.mock.calls.map(([, init]) => (init.body as Blob).text()),
    );
    expect(bodies).toEqual(['aaaa', 'bbbb', 'ccc']);
  });

  it('throws when any chunk PUT returns a non-2xx status', async () => {
    // First two parts succeed, third part fails with 403.
    mockFetch
      .mockResolvedValueOnce(putResponse('"e1"'))
      .mockResolvedValueOnce(putResponse('"e2"'))
      .mockResolvedValueOnce(putResponse(null, 403));

    const file = new Blob(['aaaabbbbccc']);
    const urls = ['u1', 'u2', 'u3'];

    await expect(uploadChunks(urls, file, 4)).rejects.toThrow(/S3 part 3 upload failed: 403/);
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it('falls back to empty string when ETag header is missing', async () => {
    mockFetch.mockResolvedValueOnce(putResponse(null));

    const file = new Blob(['xyz']);
    const etags = await uploadChunks(['u1'], file, 4);

    expect(etags).toEqual(['']);
  });

  it('stops on the first failing chunk and surfaces its 1-indexed part number', async () => {
    mockFetch.mockResolvedValueOnce(putResponse(null, 400));

    const file = new Blob(['aaaabbbb']);
    await expect(uploadChunks(['u1', 'u2'], file, 4)).rejects.toThrow(
      /S3 part 1 upload failed: 400/,
    );
    // Did not attempt the second part.
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
