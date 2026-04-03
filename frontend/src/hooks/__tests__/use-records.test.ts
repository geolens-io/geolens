import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';

vi.mock('@/api/records', () => ({
  listContacts: vi.fn(),
  createContact: vi.fn(),
  deleteContact: vi.fn(),
  listKeywords: vi.fn(),
  createKeyword: vi.fn(),
  deleteKeyword: vi.fn(),
  listDistributions: vi.fn(),
}));

vi.mock('@/api/datasets', () => ({
  fetchRelatedDatasets: vi.fn(),
}));

import { listContacts, createContact, listKeywords } from '@/api/records';
import { fetchRelatedDatasets } from '@/api/datasets';
import { useContacts, useCreateContact, useKeywords, useRelatedDatasets } from '@/hooks/use-records';

const mockListContacts = vi.mocked(listContacts);
const mockCreateContact = vi.mocked(createContact);
const mockListKeywords = vi.mocked(listKeywords);
const mockFetchRelatedDatasets = vi.mocked(fetchRelatedDatasets);

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
