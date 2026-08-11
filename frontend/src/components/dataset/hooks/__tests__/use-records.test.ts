import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';
import { useRef } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';

vi.mock('@/api/records', () => ({
  listContacts: vi.fn(),
  createContact: vi.fn(),
  deleteContact: vi.fn(),
  listKeywords: vi.fn(),
  createKeyword: vi.fn(),
  deleteKeyword: vi.fn(),
  listDistributions: vi.fn(),
  updateDistribution: vi.fn(),
}));

vi.mock('@/api/datasets', () => ({
  fetchRelatedDatasets: vi.fn(),
}));

import { listContacts, createContact, listKeywords, updateDistribution } from '@/api/records';
import { fetchRelatedDatasets } from '@/api/datasets';
import {
  useContacts,
  useCreateContact,
  useKeywords,
  useRelatedDatasets,
  useSetPrimaryDistribution,
} from '@/components/dataset/hooks/use-records';
import { queryKeys } from '@/lib/query-keys';

const mockListContacts = vi.mocked(listContacts);
const mockCreateContact = vi.mocked(createContact);
const mockListKeywords = vi.mocked(listKeywords);
const mockFetchRelatedDatasets = vi.mocked(fetchRelatedDatasets);
const mockUpdateDistribution = vi.mocked(updateDistribution);

describe('useContacts', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches contacts for a record', async () => {
    const data = { contacts: [{ id: 'c1', name: 'John' }], total: 1 };
    mockListContacts.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useContacts('rec-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
    expect(mockListContacts).toHaveBeenCalledWith('rec-1');
  });

  it('does not fetch when recordId is undefined', () => {
    const { result } = renderHook(() => useContacts(undefined));

    expect(result.current.fetchStatus).toBe('idle');
    expect(mockListContacts).not.toHaveBeenCalled();
  });

  it('returns error state on failure', async () => {
    mockListContacts.mockRejectedValueOnce(new Error('Server error'));

    const { result } = renderHook(() => useContacts('rec-1'));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useCreateContact', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls createContact on mutate', async () => {
    const created = { id: 'c2', name: 'Jane' };
    mockCreateContact.mockResolvedValueOnce(created as never);

    const { result } = renderHook(() => useCreateContact('rec-1'));

    await result.current.mutateAsync({ name: 'Jane', role: 'author' } as never);

    expect(mockCreateContact).toHaveBeenCalledWith('rec-1', { name: 'Jane', role: 'author' });
  });
});

describe('useKeywords', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches keywords for a record', async () => {
    const data = { keywords: [{ id: 'k1', value: 'geo' }], total: 1 };
    mockListKeywords.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useKeywords('rec-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
  });

  it('returns error state on failure', async () => {
    mockListKeywords.mockRejectedValueOnce(new Error('Failed'));

    const { result } = renderHook(() => useKeywords('rec-1'));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useRelatedDatasets', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches related datasets', async () => {
    const data = [{ id: 'ds-2', title: 'Related' }];
    mockFetchRelatedDatasets.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useRelatedDatasets('ds-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
  });

  it('returns error state on failure', async () => {
    mockFetchRelatedDatasets.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useRelatedDatasets('ds-1'));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// feat(#1395): set-primary control.
describe('useSetPrimaryDistribution', () => {
  beforeEach(() => vi.clearAllMocks());

  /**
   * Capture the QueryClient from inside the renderHook wrapper so we can
   * spy on invalidateQueries — see useReuploadCommit in use-dataset.test.ts
   * for the same pattern.
   */
  function renderWithClient(recordId: string | undefined) {
    let captured: QueryClient | null = null;
    const { result } = renderHook(() => {
      const qc = useQueryClient();
      const ref = useRef<QueryClient | null>(null);
      if (ref.current === null) ref.current = qc;
      captured = ref.current;
      return useSetPrimaryDistribution(recordId);
    });
    if (!captured) throw new Error('QueryClient capture failed');
    return { result, qc: captured as QueryClient };
  }

  it('PATCHes the chosen distribution with is_primary: true', async () => {
    mockUpdateDistribution.mockResolvedValueOnce({ id: 'dist-2', is_primary: true } as never);
    const { result } = renderWithClient('rec-1');

    await result.current.mutateAsync('dist-2');

    expect(mockUpdateDistribution).toHaveBeenCalledWith('rec-1', 'dist-2', { is_primary: true });
  });

  it('invalidates the distributions list on success, so the badge moves on refetch', async () => {
    mockUpdateDistribution.mockResolvedValueOnce({ id: 'dist-2', is_primary: true } as never);
    const { result, qc } = renderWithClient('rec-1');
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await result.current.mutateAsync('dist-2');

    expect(spy).toHaveBeenCalledWith({
      queryKey: queryKeys.records.distributions('rec-1'),
    });
  });

  it('does not invalidate when the PATCH is rejected (e.g. an auto-generated row)', async () => {
    mockUpdateDistribution.mockRejectedValueOnce(
      new Error('Cannot update auto-generated distributions'),
    );
    const { result, qc } = renderWithClient('rec-1');
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await expect(result.current.mutateAsync('dist-1')).rejects.toThrow();

    expect(spy).not.toHaveBeenCalled();
  });
});
