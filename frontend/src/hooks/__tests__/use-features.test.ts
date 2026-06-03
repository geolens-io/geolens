import { renderHook } from '@/test/test-utils';
import { vi } from 'vitest';

vi.mock('@/api/features', () => ({
  createFeature: vi.fn(),
  updateFeature: vi.fn(),
  deleteFeature: vi.fn(),
}));

vi.mock('@/api/datasets', () => ({
  addColumn: vi.fn(),
  dropColumn: vi.fn(),
}));

import { createFeature, updateFeature, deleteFeature } from '@/api/features';
import { useCreateFeature, useUpdateFeature, useDeleteFeature } from '@/hooks/use-features';

const mockCreateFeature = vi.mocked(createFeature);
const mockUpdateFeature = vi.mocked(updateFeature);
const mockDeleteFeature = vi.mocked(deleteFeature);

describe('useCreateFeature', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls createFeature on mutate', async () => {
    const created = { type: 'Feature', id: 1, geometry: { type: 'Point', coordinates: [0, 0] }, properties: {} };
    mockCreateFeature.mockResolvedValueOnce(created as never);

    const { result } = renderHook(() => useCreateFeature());

    await result.current.mutateAsync({
      datasetId: 'ds-1',
      geometry: { type: 'Point', coordinates: [0, 0] },
      properties: {},
    });

    expect(mockCreateFeature).toHaveBeenCalledWith('ds-1', { type: 'Point', coordinates: [0, 0] }, {});
  });

  it('returns error state on failure', async () => {
    mockCreateFeature.mockRejectedValueOnce(new Error('Forbidden'));

    const { result } = renderHook(() => useCreateFeature());

    await expect(
      result.current.mutateAsync({
        datasetId: 'ds-1',
        geometry: { type: 'Point', coordinates: [0, 0] },
      }),
    ).rejects.toThrow('Forbidden');
  });
});

describe('useUpdateFeature', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls updateFeature on mutate', async () => {
    const updated = { type: 'Feature', id: 1, geometry: { type: 'Point', coordinates: [1, 1] }, properties: {} };
    mockUpdateFeature.mockResolvedValueOnce(updated as never);

    const { result } = renderHook(() => useUpdateFeature());

    await result.current.mutateAsync({
      datasetId: 'ds-1',
      gid: 1,
      geometry: { type: 'Point', coordinates: [1, 1] },
    });

    expect(mockUpdateFeature).toHaveBeenCalledWith('ds-1', 1, { type: 'Point', coordinates: [1, 1] }, undefined);
  });
});

describe('useDeleteFeature', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls deleteFeature on mutate', async () => {
    mockDeleteFeature.mockResolvedValueOnce(undefined as never);

    const { result } = renderHook(() => useDeleteFeature());

    await result.current.mutateAsync({ datasetId: 'ds-1', gid: 1 });

    expect(mockDeleteFeature).toHaveBeenCalledWith('ds-1', 1);
  });

  it('returns error state on failure', async () => {
    mockDeleteFeature.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useDeleteFeature());

    await expect(result.current.mutateAsync({ datasetId: 'ds-1', gid: 99 })).rejects.toThrow('Not found');
  });
});
