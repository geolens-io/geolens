import { apiFetch } from '@/api/client';
import { setTargetStatus } from '@/api/datasets';
import type { StatusUpdateResponse } from '@/types/api';

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
