import { act, renderHook } from '@testing-library/react';
import { createElement, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/api/datasets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/datasets')>();
  return { ...actual, setTargetStatus: vi.fn(), updateDataset: vi.fn() };
});

import { setTargetStatus, updateDataset } from '@/api/datasets';
import { useSetTargetStatus, useUpdateDataset } from '@/components/dataset/hooks/use-dataset';
import { queryKeys } from '@/lib/query-keys';

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(queryKeys.tileTokens.token('ds-1'), { kind: 'vector' });
  client.setQueryData(queryKeys.tileTokens.batch('ds-1,ds-2'), {});
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
  const stale = () => [
    client.getQueryState(queryKeys.tileTokens.token('ds-1'))?.isInvalidated,
    client.getQueryState(queryKeys.tileTokens.batch('ds-1,ds-2'))?.isInvalidated,
  ];
  return { wrapper, stale };
}

describe('tile tokens follow publication and visibility changes', () => {
  beforeEach(() => {
    vi.mocked(setTargetStatus).mockResolvedValue({} as never);
    vi.mocked(updateDataset).mockResolvedValue({} as never);
  });

  it('refetches the tile token after a publish or unpublish', async () => {
    const { wrapper, stale } = setup();
    const { result } = renderHook(() => useSetTargetStatus(), { wrapper });
    await act(() => result.current.mutateAsync({ datasetId: 'ds-1', status: 'published' }));
    expect(stale()).toEqual([true, true]);
  });

  it('refetches the tile token after a visibility change', async () => {
    const { wrapper, stale } = setup();
    const { result } = renderHook(() => useUpdateDataset(), { wrapper });
    await act(() => result.current.mutateAsync({ datasetId: 'ds-1', data: { visibility: 'private' } }));
    expect(stale()).toEqual([true, true]);
  });

  it('keeps the tile token for a metadata-only edit', async () => {
    const { wrapper, stale } = setup();
    const { result } = renderHook(() => useUpdateDataset(), { wrapper });
    await act(() => result.current.mutateAsync({ datasetId: 'ds-1', data: { title: 'New' } }));
    expect(stale()).toEqual([false, false]);
  });
});
