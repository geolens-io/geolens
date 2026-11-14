/**
 * Preview calls wait past apiFetch's 30s default, long enough for the
 * server's own preview deadline to answer first.
 */
import { apiFetch } from '@/api/client';
import { reuploadServicePreview } from '@/api/datasets';
import { previewFile, previewServiceLayer } from '@/api/ingest';

vi.mock('@/api/client', () => ({
  apiFetch: vi.fn(),
}));

vi.mock('@/lib/report', () => ({
  reportNetworkError: vi.fn(),
}));

const mockApiFetch = vi.mocked(apiFetch);

describe('preview timeouts', () => {
  beforeEach(() => vi.clearAllMocks());

  it('previewFile passes a timeoutMs well past the apiFetch default', async () => {
    mockApiFetch.mockResolvedValueOnce({} as never);

    await previewFile('job-1');

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    const [, options] = mockApiFetch.mock.calls[0];
    expect(options?.timeoutMs).toBeGreaterThan(300_000);
  });

  it('previewServiceLayer passes a timeoutMs past the 60s worst-case retry', async () => {
    mockApiFetch.mockResolvedValueOnce({} as never);

    await previewServiceLayer({ url: 'https://services.example.test/wfs', layer_name: 'roads' } as never);

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    const [, options] = mockApiFetch.mock.calls[0];
    expect(options?.timeoutMs).toBeGreaterThan(60_000);
  });

  it('reuploadServicePreview waits as long as the import service preview', async () => {
    mockApiFetch.mockResolvedValue({} as never);

    await previewServiceLayer({ url: 'https://services.example.test/wfs', layer_name: 'roads' } as never);
    await reuploadServicePreview('dataset-1', {
      url: 'https://services.example.test/wfs',
      layer_name: 'roads',
    } as never);

    const [[, importOptions], [, reuploadOptions]] = mockApiFetch.mock.calls;
    expect(reuploadOptions?.timeoutMs).toBe(importOptions?.timeoutMs);
  });
});
