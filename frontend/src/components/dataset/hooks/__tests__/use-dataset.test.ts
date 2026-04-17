import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';

vi.mock('@/api/datasets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/datasets')>();
  return { ...actual, getDataset: vi.fn(), getDatasetRows: vi.fn() };
});

import { getDataset, getDatasetRows } from '@/api/datasets';
import { useDataset, useDatasetRows } from '@/components/dataset/hooks/use-dataset';

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

  it('returns error state on 404', async () => {
    mockGetDataset.mockRejectedValueOnce(Object.assign(new Error('Not Found'), { status: 404 }));

    const { result } = renderHook(() => useDataset('nonexistent'));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });

  it('starts in loading state', () => {
    mockGetDataset.mockReturnValueOnce(new Promise(() => {}) as never);

    const { result } = renderHook(() => useDataset('ds-1'));

    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeUndefined();
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
