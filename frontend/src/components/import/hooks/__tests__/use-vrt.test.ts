import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';

vi.mock('@/api/vrt', () => ({
  listVrtSources: vi.fn(),
  getVrtStatus: vi.fn(),
  getVrtGenerations: vi.fn(),
}));

import {
  listVrtSources,
  getVrtStatus,
} from '@/api/vrt';
import {
  useVrtSources,
  useVrtStatus,
} from '@/components/import/hooks/use-vrt';

const mockListVrtSources = vi.mocked(listVrtSources);
const mockGetVrtStatus = vi.mocked(getVrtStatus);

describe('useVrtSources', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches VRT sources for a dataset', async () => {
    const data = { sources: [{ dataset_id: 'ds-2', title: 'Source A' }], total: 1 };
    mockListVrtSources.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useVrtSources('ds-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
    expect(mockListVrtSources).toHaveBeenCalledWith('ds-1');
  });

  it('does not fetch when datasetId is empty', () => {
    const { result } = renderHook(() => useVrtSources(''));

    expect(result.current.fetchStatus).toBe('idle');
    expect(mockListVrtSources).not.toHaveBeenCalled();
  });

  it('returns error state on failure', async () => {
    mockListVrtSources.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useVrtSources('ds-1'));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useVrtStatus', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches VRT status', async () => {
    const data = { status: 'ready', source_count: 3 };
    mockGetVrtStatus.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useVrtStatus('ds-1', false));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
  });

  it('returns error state on failure', async () => {
    mockGetVrtStatus.mockRejectedValueOnce(new Error('Server error'));

    const { result } = renderHook(() => useVrtStatus('ds-1', false));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
