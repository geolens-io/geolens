import { apiFetch } from '@/api/client';
import {
  setTargetStatus,
  updatePublicationStatus,
} from '@/api/datasets';
import type { StatusUpdateResponse } from '@/types/api';

vi.mock('@/api/client', () => ({
  apiFetch: vi.fn(),
  authenticatedRawFetch: vi.fn(),
}));

const mockApiFetch = vi.mocked(apiFetch);

describe('dataset publication-status API contract', () => {
  beforeEach(() => vi.clearAllMocks());

  it('uses the generated status response contract', () => {
    expectTypeOf(updatePublicationStatus)
      .returns.resolves.toEqualTypeOf<StatusUpdateResponse>();
    expectTypeOf(setTargetStatus)
      .returns.resolves.toEqualTypeOf<StatusUpdateResponse>();
  });

  it.each([
    {
      name: 'updatePublicationStatus',
      request: updatePublicationStatus,
      path: '/datasets/dataset-1/status/',
    },
    {
      name: 'setTargetStatus',
      request: setTargetStatus,
      path: '/datasets/dataset-1/target-status/',
    },
  ])('$name sends the expected PATCH request', async ({ request, path }) => {
    const response = {
      id: 'dataset-1',
      record_status: 'ready',
    } satisfies StatusUpdateResponse;
    mockApiFetch.mockResolvedValueOnce(response);

    await expect(request('dataset-1', 'ready')).resolves.toEqual(response);

    expect(mockApiFetch).toHaveBeenCalledWith(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'ready' }),
    });
  });
});
