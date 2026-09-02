/**
 * fix(#1778): previewFile and previewServiceLayer used apiFetch's 30s
 * default timeout while the server-side work they trigger can run far
 * longer — run_ogrinfo_preview is bounded at 300s (worse on its JSON-decode
 * fallback), and a WFS namespace retry makes run_service_preview run twice
 * at 30s each. The client aborted long before either server-side deadline,
 * wasting the work with nothing observing the abort.
 */
import { apiFetch } from '@/api/client';
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
});
