import { renderHook, waitFor } from '@/test/test-utils';
import {
  useCollections,
  useCollection,
  useCollectionDatasets,
  useCreateCollection,
  useDeleteCollection,
} from '@/hooks/use-collections';

vi.mock('@/api/collections', () => ({
  listCollections: vi.fn(),
  getCollection: vi.fn(),
  getCollectionDatasets: vi.fn(),
  createCollection: vi.fn(),
  updateCollection: vi.fn(),
  deleteCollection: vi.fn(),
  addDatasetsToCollection: vi.fn(),
  removeDatasetFromCollection: vi.fn(),
}));

import {
  listCollections,
  getCollection,
  getCollectionDatasets,
  createCollection,
  deleteCollection,
} from '@/api/collections';

const mockListCollections = vi.mocked(listCollections);
const mockGetCollection = vi.mocked(getCollection);
const mockGetCollectionDatasets = vi.mocked(getCollectionDatasets);
const mockCreateCollection = vi.mocked(createCollection);
const mockDeleteCollection = vi.mocked(deleteCollection);

describe('useCollections', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches collection list', async () => {
    const data = { items: [{ id: '1', name: 'Test' }], total: 1 };
    mockListCollections.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useCollections());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(data);
    expect(mockListCollections).toHaveBeenCalledWith({ skip: 0, limit: 50 });
  });

  it('passes skip and limit parameters', async () => {
    mockListCollections.mockResolvedValueOnce({ items: [], total: 0 } as never);

    const { result } = renderHook(() => useCollections(10, 25));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockListCollections).toHaveBeenCalledWith({ skip: 10, limit: 25 });
  });
});

describe('useCollection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches a single collection by id', async () => {
    const collection = { id: 'c-1', name: 'My Collection' };
    mockGetCollection.mockResolvedValueOnce(collection as never);

    const { result } = renderHook(() => useCollection('c-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(collection);
    expect(mockGetCollection).toHaveBeenCalledWith('c-1');
  });

  it('does not fetch when id is empty', () => {
    const { result } = renderHook(() => useCollection(''));

    expect(result.current.fetchStatus).toBe('idle');
    expect(mockGetCollection).not.toHaveBeenCalled();
  });
});

describe('useCollectionDatasets', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches datasets for a collection', async () => {
    const data = { items: [], total: 0 };
    mockGetCollectionDatasets.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useCollectionDatasets('c-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockGetCollectionDatasets).toHaveBeenCalledWith('c-1', { skip: 0, limit: 20 });
  });

  it('does not fetch when collectionId is empty', () => {
    const { result } = renderHook(() => useCollectionDatasets(''));

    expect(result.current.fetchStatus).toBe('idle');
  });
});

describe('useCreateCollection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls createCollection on mutate', async () => {
    const newCollection = { id: 'c-2', name: 'New' };
    mockCreateCollection.mockResolvedValueOnce(newCollection as never);

    const { result } = renderHook(() => useCreateCollection());

    await result.current.mutateAsync({ name: 'New' } as never);

    expect(mockCreateCollection).toHaveBeenCalledWith({ name: 'New' }, expect.anything());
  });
});

describe('useDeleteCollection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls deleteCollection on mutate', async () => {
    mockDeleteCollection.mockResolvedValueOnce(undefined as never);

    const { result } = renderHook(() => useDeleteCollection());

    await result.current.mutateAsync('c-1');

    expect(mockDeleteCollection).toHaveBeenCalledWith('c-1');
  });
});

describe('useCollections – error and empty states', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns error state on API failure', async () => {
    mockListCollections.mockRejectedValueOnce(new Error('Server error'));

    const { result } = renderHook(() => useCollections());

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });

  it('handles empty collection list', async () => {
    mockListCollections.mockResolvedValueOnce({ items: [], total: 0 } as never);

    const { result } = renderHook(() => useCollections());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ items: [], total: 0 });
  });
});
