import { apiFetch } from '@/api/client';
import { createDatasetSync, listSyncCredentials, runDatasetSync } from '@/api/dataset-sync';

vi.mock('@/api/client', () => ({ apiFetch: vi.fn() }));

describe('dataset sync API adapter', () => {
  beforeEach(() => vi.clearAllMocks());

  it('uses the dataset-scoped draft endpoint without putting secrets in a URL', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({} as never);
    await createDatasetSync('dataset-1', { source: { connector: 'arcgis_feature_server', service_url: 'https://maps.example.test/FeatureServer', layer_id: 3 }, cadence: { kind: 'hourly', minute: 15 } });
    expect(apiFetch).toHaveBeenCalledWith('/datasets/dataset-1/sync', expect.objectContaining({ method: 'POST' }));
    expect(String(vi.mocked(apiFetch).mock.calls[0][0])).not.toContain('token');
  });

  it('filters credential metadata by dataset and unwraps the metadata-only list', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({ items: [{ id: 'credential-1', display_name: 'Parks' }] } as never);
    await expect(listSyncCredentials('dataset 1')).resolves.toEqual([{ id: 'credential-1', display_name: 'Parks' }]);
    expect(apiFetch).toHaveBeenCalledWith('/sync/credentials?dataset_id=dataset%201');
  });

  it('adds an idempotency key to every verification run', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({} as never);
    await runDatasetSync('dataset-1', 3);
    const [, options] = vi.mocked(apiFetch).mock.calls[0];
    expect(options).toMatchObject({ method: 'POST', body: JSON.stringify({ revision: 3 }) });
    expect(options?.headers).toHaveProperty('Idempotency-Key');
  });
});
