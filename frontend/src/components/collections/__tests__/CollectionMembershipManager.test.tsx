import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { searchDatasets } from '@/api/search';
import { toast } from 'sonner';
import { useAuthStore } from '@/stores/auth-store';
import { CollectionMembershipManager, addInBatches } from '@/components/collections/CollectionMembershipManager';
import {
  useAddDatasetsToCollection,
  useCollectionDatasets,
} from '@/components/collections/hooks/use-collections';

vi.mock('@/components/collections/hooks/use-collections', () => ({
  useAddDatasetsToCollection: vi.fn(),
  useCollectionDatasets: vi.fn(),
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock('@/api/search', () => ({
  searchDatasets: vi.fn(),
}));

const mutateAsync = vi.fn();

function record(id: string, title: string, description?: string) {
  return { id, properties: { title, description } };
}

function page(features: ReturnType<typeof record>[], hasNext = false) {
  const links = hasNext ? [{ rel: 'next', href: '/next' }] : [];
  return { features, numberMatched: features.length, links } as unknown as Awaited<ReturnType<typeof searchDatasets>>;
}

function setMembers(ids: string[]) {
  vi.mocked(useCollectionDatasets).mockReturnValue({
    data: { datasets: ids.map((id) => ({ id })), total: ids.length },
  } as unknown as ReturnType<typeof useCollectionDatasets>);
}

describe('CollectionMembershipManager', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mutateAsync.mockResolvedValue(undefined);
    setMembers([]);
    vi.mocked(useAddDatasetsToCollection).mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useAddDatasetsToCollection>);
  });

  it('lists the newest datasets as soon as it opens, without a search', async () => {
    vi.mocked(searchDatasets).mockResolvedValue(page([record('a', 'Alpha'), record('b', 'Beta')]));
    render(<CollectionMembershipManager collectionId="col-1" />);

    expect(await screen.findByRole('checkbox', { name: 'Select Alpha' })).toBeInTheDocument();
    const [params] = vi.mocked(searchDatasets).mock.calls[0];
    expect(params).toMatchObject({ sort_by: 'date_added', sort_desc: 'true', offset: '0' });
    expect(params.q).toBeUndefined();
  });

  it('prints a title once when the description repeats it', async () => {
    vi.mocked(searchDatasets).mockResolvedValue(
      page([record('a', 'Alpha', 'Alpha'), record('b', 'Beta', 'Roads of Beta')]),
    );
    render(<CollectionMembershipManager collectionId="col-1" />);

    await screen.findByRole('checkbox', { name: 'Select Alpha' });
    expect(screen.getAllByText('Alpha')).toHaveLength(1);
    expect(screen.getByText('Roads of Beta')).toBeInTheDocument();
  });

  it('hides datasets already in the collection', async () => {
    setMembers(['a']);
    vi.mocked(searchDatasets).mockResolvedValue(page([record('a', 'Alpha'), record('b', 'Beta')]));
    render(<CollectionMembershipManager collectionId="col-1" />);

    expect(await screen.findByRole('checkbox', { name: 'Select Beta' })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Select Alpha' })).not.toBeInTheDocument();
  });

  it('filters the list as the user types', async () => {
    vi.mocked(searchDatasets).mockImplementation(async (params) =>
      params.q === 'road' ? page([record('b', 'Beta Roads')]) : page([record('a', 'Alpha'), record('b', 'Beta Roads')]),
    );
    const user = userEvent.setup();
    render(<CollectionMembershipManager collectionId="col-1" />);
    await screen.findByRole('checkbox', { name: 'Select Alpha' });

    await user.type(screen.getByLabelText(/search datasets/i), 'road');

    await waitFor(() =>
      expect(screen.queryByRole('checkbox', { name: 'Select Alpha' })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole('checkbox', { name: 'Select Beta Roads' })).toBeInTheDocument();
  });

  it('adds several selected datasets in one request', async () => {
    vi.mocked(searchDatasets).mockResolvedValue(
      page([record('a', 'Alpha'), record('b', 'Beta'), record('c', 'Gamma')]),
    );
    const user = userEvent.setup();
    render(<CollectionMembershipManager collectionId="col-1" />);

    await user.click(await screen.findByRole('checkbox', { name: 'Select Alpha' }));
    await user.click(screen.getByRole('checkbox', { name: 'Select Gamma' }));
    await user.click(screen.getByRole('button', { name: 'Add 2 selected datasets' }));

    expect(mutateAsync).toHaveBeenCalledWith({ collectionId: 'col-1', datasetIds: ['a', 'c'] });
  });

  it('loads the next page on request', async () => {
    const first = Array.from({ length: 20 }, (_, i) => record(`a${i}`, `Alpha ${i}`));
    vi.mocked(searchDatasets).mockImplementation(async (params) =>
      params.offset === '0' ? page(first, true) : page([record('b', 'Beta')]),
    );
    const user = userEvent.setup();
    render(<CollectionMembershipManager collectionId="col-1" />);
    await screen.findByRole('checkbox', { name: 'Select Alpha 0' });

    await user.click(screen.getByRole('button', { name: 'Load more' }));

    expect(await screen.findByRole('checkbox', { name: 'Select Beta' })).toBeInTheDocument();
    expect(vi.mocked(searchDatasets).mock.calls[1][0]).toMatchObject({ offset: '20' });
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('keeps the Load more name while the next page loads', async () => {
    const first = Array.from({ length: 20 }, (_, i) => record(`a${i}`, `Alpha ${i}`));
    let finish: (value: Awaited<ReturnType<typeof searchDatasets>>) => void = () => {};
    vi.mocked(searchDatasets).mockImplementation((params) =>
      params.offset === '0'
        ? Promise.resolve(page(first, true))
        : new Promise((resolve) => {
            finish = resolve;
          }),
    );
    const user = userEvent.setup();
    render(<CollectionMembershipManager collectionId="col-1" />);
    await screen.findByRole('checkbox', { name: 'Select Alpha 0' });

    await user.click(screen.getByRole('button', { name: 'Load more' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'Load more' })).toBeDisabled());
    finish(page([record('b', 'Beta')]));
    expect(await screen.findByRole('checkbox', { name: 'Select Beta' })).toBeInTheDocument();
  });

  it('does not skip datasets when page 0 also returns matching collections', async () => {
    const datasets = Array.from({ length: 20 }, (_, i) => record(`d${i}`, `Dataset ${i}`));
    const collections = [1, 2, 3].map((i) => ({
      id: `c${i}`,
      properties: { title: `Collection ${i}`, type: 'collection' },
    }));
    vi.mocked(searchDatasets).mockImplementation(async (params) =>
      params.offset === '0'
        ? ({ features: [...datasets, ...collections], numberMatched: 43, links: [{ rel: 'next', href: '/next' }] } as unknown as Awaited<ReturnType<typeof searchDatasets>>)
        : page([record('d20', 'Dataset 20')]),
    );
    const user = userEvent.setup();
    render(<CollectionMembershipManager collectionId="col-1" />);
    await screen.findByRole('checkbox', { name: 'Select Dataset 0' });

    expect(screen.queryByRole('checkbox', { name: 'Select Collection 1' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Load more' }));

    expect(await screen.findByRole('checkbox', { name: 'Select Dataset 20' })).toBeInTheDocument();
    expect(vi.mocked(searchDatasets).mock.calls[1][0]).toMatchObject({ offset: '20' });
  });

  it('offers no Load more when the next link is absent, even if collections inflate the count', async () => {
    const datasets = Array.from({ length: 20 }, (_, i) => record(`d${i}`, `Dataset ${i}`));
    const collection = { id: 'c1', properties: { title: 'Collection 1', type: 'collection' } };
    vi.mocked(searchDatasets).mockResolvedValue({
      features: [...datasets, collection],
      numberMatched: 21,
      links: [],
    } as unknown as Awaited<ReturnType<typeof searchDatasets>>);
    render(<CollectionMembershipManager collectionId="col-1" />);
    await screen.findByRole('checkbox', { name: 'Select Dataset 0' });

    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('submits selections made under a previous filter', async () => {
    vi.mocked(searchDatasets).mockImplementation(async (params) =>
      params.q === 'beta' ? page([record('b', 'Beta')]) : page([record('a', 'Alpha'), record('b', 'Beta')]),
    );
    const user = userEvent.setup();
    render(<CollectionMembershipManager collectionId="col-1" />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select Alpha' }));

    await user.type(screen.getByLabelText(/search datasets/i), 'beta');
    await waitFor(() =>
      expect(screen.queryByRole('checkbox', { name: 'Select Alpha' })).not.toBeInTheDocument(),
    );
    await user.click(screen.getByRole('checkbox', { name: 'Select Beta' }));
    await user.click(screen.getByRole('button', { name: 'Add 2 selected datasets' }));

    expect(mutateAsync).toHaveBeenCalledWith({ collectionId: 'col-1', datasetIds: ['a', 'b'] });
  });

  it('drops the selection when the route reuses the panel for another collection', async () => {
    vi.mocked(searchDatasets).mockResolvedValue(page([record('a', 'Alpha')]));
    const user = userEvent.setup();
    const { rerender } = render(<CollectionMembershipManager collectionId="col-1" />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select Alpha' }));
    expect(screen.getByRole('button', { name: 'Add 1 selected dataset' })).toBeEnabled();

    rerender(<CollectionMembershipManager collectionId="col-2" />);

    expect(await screen.findByRole('button', { name: 'Add 0 selected datasets' })).toBeDisabled();
  });

  it('hides added rows at once and reports the server count', async () => {
    vi.mocked(searchDatasets).mockResolvedValue(page([record('a', 'Alpha'), record('b', 'Beta')]));
    mutateAsync.mockResolvedValue({ added: 1 });
    const user = userEvent.setup();
    render(<CollectionMembershipManager collectionId="col-1" />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select Alpha' }));
    await user.click(screen.getByRole('checkbox', { name: 'Select Beta' }));
    await user.click(screen.getByRole('button', { name: 'Add 2 selected datasets' }));

    await waitFor(() =>
      expect(screen.queryByRole('checkbox', { name: 'Select Alpha' })).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole('checkbox', { name: 'Select Beta' })).not.toBeInTheDocument();
    expect(vi.mocked(toast.success)).toHaveBeenCalledWith('1 dataset added to collection');
  });

  it('sends only one request when Add is clicked twice', async () => {
    vi.mocked(searchDatasets).mockResolvedValue(page([record('a', 'Alpha')]));
    mutateAsync.mockImplementation(() => new Promise((r) => setTimeout(() => r({ added: 1 }), 50)));
    const user = userEvent.setup();
    render(<CollectionMembershipManager collectionId="col-1" />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select Alpha' }));
    const add = screen.getByRole('button', { name: 'Add 1 selected dataset' });
    await user.dblClick(add);

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    expect(mutateAsync).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(vi.mocked(toast.success)).toHaveBeenCalled());
  });

  it('shows a dataset again once it is removed from the collection', async () => {
    vi.mocked(searchDatasets).mockResolvedValue(page([record('a', 'Alpha')]));
    mutateAsync.mockResolvedValue({ added: 1 });
    const user = userEvent.setup();
    const { rerender } = render(<CollectionMembershipManager collectionId="col-1" />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select Alpha' }));
    await user.click(screen.getByRole('button', { name: 'Add 1 selected dataset' }));
    await waitFor(() =>
      expect(screen.queryByRole('checkbox', { name: 'Select Alpha' })).not.toBeInTheDocument(),
    );

    // Membership refetch lands (Alpha is a member), then Alpha is removed elsewhere.
    vi.mocked(useCollectionDatasets).mockReturnValue({
      data: { datasets: [], total: 0 },
      dataUpdatedAt: Date.now() + 1000,
    } as unknown as ReturnType<typeof useCollectionDatasets>);
    rerender(<CollectionMembershipManager collectionId="col-1" />);

    expect(await screen.findByRole('checkbox', { name: 'Select Alpha' })).toBeInTheDocument();
  });

  it('ignores the result of an add that outlived the signed-in session', async () => {
    vi.mocked(searchDatasets).mockResolvedValue(page([record('a', 'Alpha')]));
    let finish: (v: unknown) => void = () => {};
    mutateAsync.mockImplementation(() => new Promise((r) => { finish = r; }));
    const user = userEvent.setup();
    render(<CollectionMembershipManager collectionId="col-1" />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select Alpha' }));
    await user.click(screen.getByRole('button', { name: 'Add 1 selected dataset' }));

    useAuthStore.setState((st) => ({ sessionEpoch: st.sessionEpoch + 1 }));
    finish({ added: 1 });

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    await new Promise((r) => setTimeout(r, 20));
    expect(vi.mocked(toast.success)).not.toHaveBeenCalled();
    expect(screen.getByRole('checkbox', { name: 'Select Alpha' })).toBeInTheDocument();
  });

  it('clears a selection that is no longer visible', async () => {
    vi.mocked(searchDatasets).mockImplementation(async (params) =>
      params.q === 'beta' ? page([record('b', 'Beta')]) : page([record('a', 'Alpha'), record('b', 'Beta')]),
    );
    const user = userEvent.setup();
    render(<CollectionMembershipManager collectionId="col-1" />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select Alpha' }));
    await user.type(screen.getByLabelText(/search datasets/i), 'beta');
    await waitFor(() =>
      expect(screen.queryByRole('checkbox', { name: 'Select Alpha' })).not.toBeInTheDocument(),
    );

    await user.click(screen.getByRole('button', { name: 'Clear selection' }));
    await user.click(screen.getByRole('checkbox', { name: 'Select Beta' }));
    await user.click(screen.getByRole('button', { name: 'Add 1 selected dataset' }));

    expect(mutateAsync).toHaveBeenCalledWith({ collectionId: 'col-1', datasetIds: ['b'] });
  });

  it('lets the user clear a failed selection and retry with another dataset', async () => {
    vi.mocked(searchDatasets).mockResolvedValue(page([record('a', 'Alpha'), record('b', 'Beta')]));
    mutateAsync.mockRejectedValueOnce(new Error('404'));
    const user = userEvent.setup();
    render(<CollectionMembershipManager collectionId="col-1" />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select Alpha' }));
    await user.click(screen.getByRole('button', { name: 'Add 1 selected dataset' }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));

    await user.click(await screen.findByRole('button', { name: 'Clear selection' }));
    await user.click(screen.getByRole('checkbox', { name: 'Select Beta' }));
    await user.click(screen.getByRole('button', { name: 'Add 1 selected dataset' }));

    expect(mutateAsync).toHaveBeenLastCalledWith({ collectionId: 'col-1', datasetIds: ['b'] });
  });

  it('keeps added rows hidden when the member list is truncated', async () => {
    vi.mocked(searchDatasets).mockResolvedValue(page([record('a', 'Alpha')]));
    mutateAsync.mockResolvedValue({ added: 1 });
    vi.mocked(useCollectionDatasets).mockReturnValue({
      data: { datasets: [{ id: 'm1' }], total: 250 },
      dataUpdatedAt: 0,
    } as unknown as ReturnType<typeof useCollectionDatasets>);
    const user = userEvent.setup();
    const { rerender } = render(<CollectionMembershipManager collectionId="col-1" />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select Alpha' }));
    await user.click(screen.getByRole('button', { name: 'Add 1 selected dataset' }));
    await waitFor(() =>
      expect(screen.queryByRole('checkbox', { name: 'Select Alpha' })).not.toBeInTheDocument(),
    );

    vi.mocked(useCollectionDatasets).mockReturnValue({
      data: { datasets: [{ id: 'm1' }], total: 250 },
      dataUpdatedAt: Date.now() + 1000,
    } as unknown as ReturnType<typeof useCollectionDatasets>);
    rerender(<CollectionMembershipManager collectionId="col-1" />);

    expect(screen.queryByRole('checkbox', { name: 'Select Alpha' })).not.toBeInTheDocument();
  });

  it('keeps datasets selected when the add fails', async () => {
    vi.mocked(searchDatasets).mockResolvedValue(page([record('a', 'Alpha'), record('b', 'Beta')]));
    mutateAsync.mockRejectedValueOnce(new Error('boom'));
    const user = userEvent.setup();
    render(<CollectionMembershipManager collectionId="col-1" />);
    await user.click(await screen.findByRole('checkbox', { name: 'Select Alpha' }));
    await user.click(screen.getByRole('button', { name: 'Add 1 selected dataset' }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole('button', { name: 'Add 1 selected dataset' })).toBeEnabled();
  });
});

describe('addInBatches', () => {
  const ids = Array.from({ length: 250 }, (_, i) => `d${i}`);

  it('stops sending once shouldContinue turns false', async () => {
    const add = vi.fn().mockResolvedValue(undefined);
    let calls = 0;
    await addInBatches(ids, add, 100, () => calls++ < 1);

    expect(add).toHaveBeenCalledTimes(1);
  });

  it('sends at most 100 ids per request', async () => {
    const add = vi.fn().mockResolvedValue(undefined);
    const { ids: sent, failure } = await addInBatches(ids, add);

    expect(add.mock.calls.map(([b]) => b.length)).toEqual([100, 100, 50]);
    expect(sent).toHaveLength(250);
    expect(failure).toBeNull();
  });

  it('stops at the first failure and reports only the ids that were added', async () => {
    const add = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('boom'));
    const { ids: sent, failure } = await addInBatches(ids, add);

    expect(add).toHaveBeenCalledTimes(2);
    expect(sent).toEqual(ids.slice(0, 100));
    expect(failure).toBeInstanceOf(Error);
  });
});
