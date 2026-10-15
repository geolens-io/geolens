import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { searchDatasets } from '@/api/search';
import { CollectionMembershipManager } from '@/components/collections/CollectionMembershipManager';
import {
  useAddDatasetsToCollection,
  useCollectionDatasets,
} from '@/components/collections/hooks/use-collections';

vi.mock('@/components/collections/hooks/use-collections', () => ({
  useAddDatasetsToCollection: vi.fn(),
  useCollectionDatasets: vi.fn(),
}));

vi.mock('@/api/search', () => ({
  searchDatasets: vi.fn(),
}));

const mutateAsync = vi.fn();

function record(id: string, title: string) {
  return { id, properties: { title } };
}

function page(features: ReturnType<typeof record>[], numberMatched = features.length) {
  return { features, numberMatched } as unknown as Awaited<ReturnType<typeof searchDatasets>>;
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
    vi.mocked(searchDatasets).mockImplementation(async (params) =>
      params.offset === '0' ? page([record('a', 'Alpha')], 2) : page([record('b', 'Beta')], 2),
    );
    const user = userEvent.setup();
    render(<CollectionMembershipManager collectionId="col-1" />);
    await screen.findByRole('checkbox', { name: 'Select Alpha' });

    await user.click(screen.getByRole('button', { name: 'Load more' }));

    expect(await screen.findByRole('checkbox', { name: 'Select Beta' })).toBeInTheDocument();
    expect(vi.mocked(searchDatasets).mock.calls[1][0]).toMatchObject({ offset: '1' });
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });
});
