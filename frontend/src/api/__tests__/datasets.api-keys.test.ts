import { apiFetch } from '@/api/client';
import { listDatasetApiKeys } from '@/api/datasets';
import type { DatasetApiKeyResponse } from '@/types/api';

vi.mock('@/api/client', () => ({
  apiFetch: vi.fn(),
  authenticatedRawFetch: vi.fn(),
}));

const mockApiFetch = vi.mocked(apiFetch);

function keys(count: number, from = 0): DatasetApiKeyResponse[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `key-${from + i}`,
    name: `Key ${from + i}`,
    fingerprint: null,
    is_active: true,
    expires_at: null,
    scope: 'dataset_write',
    dataset_id: 'ds-1',
    created_at: '2026-10-01T00:00:00Z',
    last_used_at: null,
    user_id: 'u1',
    username: 'owner',
  }));
}

describe('listDatasetApiKeys', () => {
  beforeEach(() => vi.clearAllMocks());

  it('reads every page until it has the total', async () => {
    mockApiFetch
      .mockResolvedValueOnce({ items: keys(200), total: 201 })
      .mockResolvedValueOnce({ items: keys(1, 200), total: 201 });

    const result = await listDatasetApiKeys('ds-1');

    expect(result).toHaveLength(201);
    expect(result[200].id).toBe('key-200');
    expect(mockApiFetch.mock.calls.map(([url]) => url)).toEqual([
      '/datasets/ds-1/api-keys?skip=0&limit=200',
      '/datasets/ds-1/api-keys?skip=200&limit=200',
    ]);
  });

  it('stops on an empty page when the list shrank while being read', async () => {
    mockApiFetch
      .mockResolvedValueOnce({ items: keys(200), total: 205 })
      .mockResolvedValueOnce({ items: [], total: 200 });

    await expect(listDatasetApiKeys('ds-1')).resolves.toHaveLength(200);
    expect(mockApiFetch).toHaveBeenCalledTimes(2);
  });
});
