import { apiFetch } from '@/api/client';
import { reuploadDataset, setTargetStatus } from '@/api/datasets';
import type { ReuploadResponse, StatusUpdateResponse } from '@/types/api';

vi.mock('@/api/client', () => ({
  apiFetch: vi.fn(),
  authenticatedRawFetch: vi.fn(),
}));

const mockApiFetch = vi.mocked(apiFetch);

// chore(#835): the single-step `updatePublicationStatus` rows were removed
// with the function itself — the app talks only to the target-status endpoint.
describe('dataset publication-status API contract', () => {
  beforeEach(() => vi.clearAllMocks());

  it('uses the generated status response contract', () => {
    expectTypeOf(setTargetStatus)
      .returns.resolves.toEqualTypeOf<StatusUpdateResponse>();
  });

  it('setTargetStatus sends the expected PATCH request', async () => {
    const response = {
      id: 'dataset-1',
      record_status: 'ready',
    } satisfies StatusUpdateResponse;
    mockApiFetch.mockResolvedValueOnce(response);

    await expect(setTargetStatus('dataset-1', 'ready')).resolves.toEqual(response);

    expect(mockApiFetch).toHaveBeenCalledWith('/datasets/dataset-1/target-status/', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'ready' }),
    });
  });
});

// fix(#1778): reuploadDataset sends a FormData body that can hold up to
// upload_max_size_mb (500 MB) — it must not fall back to apiFetch's 30s
// default timeout, or a large transfer aborts client-side before it finishes.
describe('reuploadDataset timeout', () => {
  beforeEach(() => vi.clearAllMocks());

  it('passes an extended timeoutMs, not the apiFetch default', async () => {
    const response = {
      job_id: 'job-1',
      status: 'pending',
      message: 'Upload received',
    } satisfies ReuploadResponse;
    mockApiFetch.mockResolvedValueOnce(response);

    const file = new File(['data'], 'dataset.gpkg');
    await reuploadDataset('dataset-1', file);

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    const [, options] = mockApiFetch.mock.calls[0];
    expect(options?.timeoutMs).toBeGreaterThan(30_000);
  });
});
