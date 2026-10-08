import { authenticatedDownload } from '@/api/datasets';
import { authenticatedRawFetch } from '@/api/client';
import { triggerDownload } from '@/lib/download';

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  authenticatedRawFetch: vi.fn(),
}));
vi.mock('@/lib/download', () => ({ triggerDownload: vi.fn() }));

const mockRawFetch = vi.mocked(authenticatedRawFetch);

describe('authenticatedDownload', () => {
  beforeEach(() => vi.clearAllMocks());

  it('hands the fetched blob to the shared download helper', async () => {
    mockRawFetch.mockResolvedValueOnce(new Response('a,b', { status: 200 }));

    await authenticatedDownload('/api/x', 'x.csv');

    expect(triggerDownload).toHaveBeenCalledWith(expect.any(Blob), 'x.csv');
  });

  it('rejects without downloading when the caller aborts', async () => {
    const controller = new AbortController();
    mockRawFetch.mockImplementationOnce((_url, init) => new Promise((_, reject) => {
      init?.signal?.addEventListener('abort', () => reject(init.signal?.reason));
    }));

    const pending = authenticatedDownload('/api/x', 'x.csv', controller.signal);
    controller.abort(new Error('cancelled'));

    await expect(pending).rejects.toThrow('cancelled');
    expect(triggerDownload).not.toHaveBeenCalled();
  });

  it('keeps the localized error for non-2xx responses', async () => {
    mockRawFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Forbidden' }), { status: 403 }),
    );

    await expect(authenticatedDownload('/api/x', 'x.csv')).rejects.toThrow('Access denied');
    expect(triggerDownload).not.toHaveBeenCalled();
  });
});
