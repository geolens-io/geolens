import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';

vi.mock('@/api/vrt', () => ({
  listVrtSources: vi.fn(),
  addVrtSource: vi.fn(),
  removeVrtSource: vi.fn(),
  getVrtStatus: vi.fn(),
  getVrtGenerations: vi.fn(),
  regenerateVrt: vi.fn(),
}));

import { listVrtSources, addVrtSource, getVrtStatus, regenerateVrt } from '@/api/vrt';
import { useVrtSources, useAddVrtSource, useVrtStatus, useRegenerateVrt } from '@/components/import/hooks/use-vrt';

const mockListVrtSources = vi.mocked(listVrtSources);
const mockAddVrtSource = vi.mocked(addVrtSource);
const mockGetVrtStatus = vi.mocked(getVrtStatus);
const mockRegenerateVrt = vi.mocked(regenerateVrt);

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

describe('useAddVrtSource', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls addVrtSource on mutate', async () => {
    const response = { message: 'Source added' };
    mockAddVrtSource.mockResolvedValueOnce(response as never);

    const { result } = renderHook(() => useAddVrtSource('ds-1'));

    await result.current.mutateAsync('ds-2');

    expect(mockAddVrtSource).toHaveBeenCalledWith('ds-1', 'ds-2');
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

describe('useRegenerateVrt', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls regenerateVrt on mutate', async () => {
    const response = { message: 'Regenerating' };
    mockRegenerateVrt.mockResolvedValueOnce(response as never);

    const { result } = renderHook(() => useRegenerateVrt('ds-1'));

    await result.current.mutateAsync();

    expect(mockRegenerateVrt).toHaveBeenCalledWith('ds-1');
  });
});
