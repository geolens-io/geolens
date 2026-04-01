import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';

vi.mock('@/api/datasets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/datasets')>();
  return { ...actual, getDataset: vi.fn(), getDatasetRows: vi.fn() };
});

import { getDataset, getDatasetRows } from '@/api/datasets';
import { useDataset, useDatasetRows } from '@/hooks/use-dataset';

const mockGetDataset = vi.mocked(getDataset);
const mockGetDatasetRows = vi.mocked(getDatasetRows);

describe('useDataset', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches dataset by id', async () => {
    const mockData = { id: 'ds-1', title: 'Test Dataset' };
    mockGetDataset.mockResolvedValueOnce(mockData as never);

    const { result } = renderHook(() => useDataset('ds-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
    expect(mockGetDataset).toHaveBeenCalledWith('ds-1');
  });

  it('does not fetch when id is empty', () => {
    renderHook(() => useDataset(''));

    expect(mockGetDataset).not.toHaveBeenCalled();
  });

  it('returns error state on failure', async () => {
    mockGetDataset.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useDataset('bad-id'));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useDatasetRows', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches rows with pagination params', async () => {
    const mockRows = { rows: [{ name: 'a' }], total: 1 };
    mockGetDatasetRows.mockResolvedValueOnce(mockRows as never);

    const { result } = renderHook(() => useDatasetRows('ds-1', 10, 0));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockRows);
    expect(mockGetDatasetRows).toHaveBeenCalledWith('ds-1', { limit: 10, after: 0, filters: undefined });
  });

  it('does not fetch when id is empty', () => {
    renderHook(() => useDatasetRows('', 10, 0));

    expect(mockGetDatasetRows).not.toHaveBeenCalled();
  });
});
