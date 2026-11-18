import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';
import type { ReactNode } from 'react';
import { renderHook as rtlRenderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { ApiError } from '@/api/client';

vi.mock('@/api/vrt', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/vrt')>()),
  listVrtSources: vi.fn(),
  getVrtStatus: vi.fn(),
  getVrtGenerations: vi.fn(),
  regenerateVrt: vi.fn(),
}));

import {
  listVrtSources,
  getVrtStatus,
  getVrtGenerations,
  regenerateVrt,
} from '@/api/vrt';
import {
  useVrtSources,
  useVrtStatus,
  useVrtGenerations,
  useRegenerateVrt,
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

describe('VRT rebuild refresh', () => {
  const gens = (status: string) => ({ generations: [{ id: 'g1', status }], total: 1 }) as never;

  beforeEach(() => vi.clearAllMocks());

  it('polls while the newest generation is in progress, then stops and refreshes members', async () => {
    vi.mocked(getVrtGenerations)
      .mockResolvedValueOnce(gens('running'))
      .mockResolvedValue(gens('completed'));
    renderHook(() => ({
      generations: useVrtGenerations('ds-1', { limit: 1 }),
      sources: useVrtSources('ds-1'),
      status: useVrtStatus('ds-1', false),
    }));

    await waitFor(() => expect(getVrtGenerations).toHaveBeenCalledTimes(2), { timeout: 6000 });
    // Sources and status were fetched once at mount and once more at the transition.
    await waitFor(() => expect(mockListVrtSources).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mockGetVrtStatus).toHaveBeenCalledTimes(2));
  }, 10000);

  it('does not poll once the newest generation is terminal', async () => {
    vi.mocked(getVrtGenerations).mockResolvedValue(gens('completed'));
    const { result } = renderHook(() => useVrtGenerations('ds-1', { limit: 1 }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await new Promise((r) => setTimeout(r, 3500));
    expect(getVrtGenerations).toHaveBeenCalledTimes(1);
  }, 10000);

  it('refetches on remount instead of showing a cached in-progress row', async () => {
    vi.mocked(getVrtGenerations).mockResolvedValue(gens('completed'));
    const client = new QueryClient();
    client.setQueryData(queryKeys.vrt.generations('ds-1', { limit: 1 }), gens('running'));
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = rtlRenderHook(() => useVrtGenerations('ds-1', { limit: 1 }), { wrapper });
    await waitFor(() => expect(getVrtGenerations).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(result.current.data?.generations[0].status).toBe('completed'));
  });

  it('refetches parameterized generation queries when a rebuild is accepted', async () => {
    vi.mocked(getVrtGenerations).mockResolvedValue(gens('completed'));
    vi.mocked(regenerateVrt).mockResolvedValue({} as never);
    const { result } = renderHook(() => ({
      generations: useVrtGenerations('ds-1', { limit: 1 }),
      regenerate: useRegenerateVrt('ds-1'),
    }));
    await waitFor(() => expect(result.current.generations.isSuccess).toBe(true));

    result.current.regenerate.mutate();
    await waitFor(() => expect(getVrtGenerations).toHaveBeenCalledTimes(2));
  });

  function renderWithClient<T>(hook: () => T) {
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    return { client, ...rtlRenderHook(hook, { wrapper }) };
  }

  it('restarts a history read that was in flight when the rebuild was accepted', async () => {
    let resolveOld!: (v: never) => void;
    vi.mocked(getVrtGenerations)
      .mockImplementationOnce(() => new Promise((r) => { resolveOld = r as never; }))
      .mockResolvedValue({ generations: [{ id: 'g2', status: 'running' }], total: 2 } as never);
    vi.mocked(regenerateVrt).mockResolvedValue({} as never);
    const { result } = renderWithClient(() => ({
      generations: useVrtGenerations('ds-1', { limit: 1 }),
      regenerate: useRegenerateVrt('ds-1'),
    }));
    await waitFor(() => expect(getVrtGenerations).toHaveBeenCalledTimes(1));

    result.current.regenerate.mutate();
    await waitFor(() => expect(getVrtGenerations).toHaveBeenCalledTimes(2));
    resolveOld(gens('completed'));

    await waitFor(() => expect(result.current.generations.data?.generations[0].id).toBe('g2'));
  });

  it('refetches a cached-ready dataset detail when the history shows a running rebuild', async () => {
    vi.mocked(getVrtGenerations).mockResolvedValue(gens('running'));
    const detail = vi.fn().mockResolvedValue({ raster: { status: 'ready' } });
    renderWithClient(() => ({
      generations: useVrtGenerations('ds-1', { limit: 1 }),
      detail: useQuery({ queryKey: queryKeys.datasets.detail('ds-1'), queryFn: detail, staleTime: Infinity }),
    }));
    await waitFor(() => expect(detail).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(detail).toHaveBeenCalledTimes(2));
  });

  it('picks up a rebuild someone else started on a dataset_busy answer', async () => {
    vi.mocked(getVrtGenerations).mockResolvedValue(gens('completed'));
    vi.mocked(regenerateVrt).mockRejectedValue(new ApiError('busy', 409, { code: 'dataset_busy' }));
    const detail = vi.fn().mockResolvedValue({});
    const { result } = renderWithClient(() => ({
      generations: useVrtGenerations('ds-1', { limit: 1 }),
      detail: useQuery({ queryKey: queryKeys.datasets.detail('ds-1'), queryFn: detail, staleTime: Infinity }),
      regenerate: useRegenerateVrt('ds-1'),
    }));
    await waitFor(() => expect(detail).toHaveBeenCalledTimes(1));

    result.current.regenerate.mutate();
    await waitFor(() => expect(detail).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(getVrtGenerations).toHaveBeenCalledTimes(2));
  });

  it('leaves the caches alone on a catalog lock conflict', async () => {
    vi.mocked(getVrtGenerations).mockResolvedValue(gens('completed'));
    vi.mocked(regenerateVrt).mockRejectedValue(new ApiError('locked', 409, { code: 'catalog_lock_conflict' }));
    const { result } = renderWithClient(() => ({
      generations: useVrtGenerations('ds-1', { limit: 1 }),
      regenerate: useRegenerateVrt('ds-1'),
    }));
    await waitFor(() => expect(result.current.generations.isSuccess).toBe(true));

    result.current.regenerate.mutate();
    await waitFor(() => expect(result.current.regenerate.isError).toBe(true));
    expect(getVrtGenerations).toHaveBeenCalledTimes(1);
  });

  it('stays pending until the refetches after an accepted rebuild settle', async () => {
    let resolveRefetch!: (v: never) => void;
    vi.mocked(getVrtGenerations)
      .mockResolvedValueOnce(gens('completed'))
      .mockImplementationOnce(() => new Promise((r) => { resolveRefetch = r as never; }));
    vi.mocked(regenerateVrt).mockResolvedValue({} as never);
    const { result } = renderWithClient(() => ({
      generations: useVrtGenerations('ds-1', { limit: 1 }),
      regenerate: useRegenerateVrt('ds-1'),
    }));
    await waitFor(() => expect(result.current.generations.isSuccess).toBe(true));

    result.current.regenerate.mutate();
    await waitFor(() => expect(getVrtGenerations).toHaveBeenCalledTimes(2));
    expect(result.current.regenerate.isPending).toBe(true);

    resolveRefetch(gens('completed'));
    await waitFor(() => expect(result.current.regenerate.isPending).toBe(false));
  });
});
