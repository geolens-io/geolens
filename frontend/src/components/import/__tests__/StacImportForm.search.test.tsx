import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { ReactNode } from 'react';
import { StacImportForm } from '../StacImportForm';
import type { StacItemSummary } from '@/types/api';

const mockConnectStac = vi.fn();
const mockFetchStacCollections = vi.fn();
const mockSearchStacItems = vi.fn();

vi.mock('@/api/stac', () => ({
  connectStac: (...args: unknown[]) => mockConnectStac(...args),
  fetchStacCollections: (...args: unknown[]) => mockFetchStacCollections(...args),
  searchStacItems: (...args: unknown[]) => mockSearchStacItems(...args),
  importStacItems: vi.fn(),
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

function makeItem(id: string, overrides: Partial<StacItemSummary> = {}): StacItemSummary {
  return {
    id,
    collection: 'test-col',
    item_href: null,
    title: id,
    bbox: null,
    datetime: null,
    datetime_start: null,
    datetime_end: null,
    epsg: null,
    gsd: null,
    cloud_cover: null,
    data_asset_href: 'https://example.com/data.tif',
    data_asset_type: 'image/tiff',
    data_asset_key: 'data',
    data_asset_size_bytes: null,
    data_asset_import_refusal: null,
    thumbnail_href: null,
    asset_count: 1,
    ...overrides,
  };
}

async function driveToItemsStep(
  firstPage: unknown,
  conformsTo: string[] = [],
) {
  const user = userEvent.setup();
  mockConnectStac.mockResolvedValue({
    id: 'cat',
    title: 'Catalog',
    description: '',
    stac_version: '1.0.0',
    conforms_to: conformsTo,
    url: 'https://example.com/stac',
  });
  mockFetchStacCollections.mockResolvedValue({
    collections: [
      {
        id: 'test-col',
        title: 'Test Collection',
        description: '',
        license: null,
        keywords: [],
        bbox: null,
        temporal_start: null,
        temporal_end: null,
        item_count: null,
      },
    ],
  });
  mockSearchStacItems.mockResolvedValueOnce(firstPage);

  render(
    <Wrapper>
      <StacImportForm />
    </Wrapper>,
  );
  await user.type(screen.getByRole('textbox'), 'https://example.com/stac');
  await user.click(screen.getByRole('button', { name: /connect/i }));
  await waitFor(() => screen.getByText('Test Collection'));
  await user.click(screen.getByText('Test Collection'));
  await waitFor(() => screen.getByTestId('stac-search-filters'));
  return user;
}

const QUERY = ['https://api.stacspec.org/v1.0.0/item-search#query'];
const CQL = [
  'https://api.stacspec.org/v1.0.0/item-search#filter',
  'http://www.opengis.net/spec/cql2/1.0/conf/cql2-json',
];

const page = (ids: string[], extra: Record<string, unknown> = {}) => ({
  items: ids.map((id) => makeItem(id)),
  matched: 10,
  returned: ids.length,
  ...extra,
});

describe('StacImportForm item search filters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('date range and area reach the search call and replace the items', async () => {
    const user = await driveToItemsStep(page(['old-1']));
    mockSearchStacItems.mockResolvedValueOnce(page(['new-1']));

    await user.type(screen.getByLabelText('stac.filterStart'), '2024-01-01');
    await user.type(screen.getByLabelText('stac.filterEnd'), '2024-02-01');
    await user.type(screen.getByLabelText('stac.filterBbox'), '-74.3, 40.5, -73.7, 40.9');
    await user.click(screen.getByRole('button', { name: 'stac.filterApply' }));

    await waitFor(() => expect(screen.getByText('new-1')).toBeInTheDocument());
    expect(screen.queryByText('old-1')).not.toBeInTheDocument();
    expect(mockSearchStacItems).toHaveBeenLastCalledWith(
      expect.objectContaining({
        collections: ['test-col'],
        bbox: [-74.3, 40.5, -73.7, 40.9],
        datetime_range: '2024-01-01T00:00:00Z/2024-02-01T23:59:59Z',
      }),
    );
  });

  test('a one-sided date range is open-ended', async () => {
    const user = await driveToItemsStep(page(['a']));
    mockSearchStacItems.mockResolvedValueOnce(page(['b']));

    await user.type(screen.getByLabelText('stac.filterStart'), '2024-05-01');
    await user.click(screen.getByRole('button', { name: 'stac.filterApply' }));

    await waitFor(() => expect(mockSearchStacItems).toHaveBeenCalledTimes(2));
    expect(mockSearchStacItems.mock.calls[1][0]).toMatchObject({
      datetime_range: '2024-05-01T00:00:00Z/..',
    });
    expect(mockSearchStacItems.mock.calls[1][0]).not.toHaveProperty('bbox');
  });

  test('an unusable area is refused without searching', async () => {
    const user = await driveToItemsStep(page(['a']));

    await user.type(screen.getByLabelText('stac.filterBbox'), '1, 2, 3');
    await user.click(screen.getByRole('button', { name: 'stac.filterApply' }));

    expect(await screen.findByTestId('stac-filter-error')).toHaveTextContent('stac.filterBboxInvalid');
    expect(mockSearchStacItems).toHaveBeenCalledTimes(1);
  });
});

describe('StacImportForm load more', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const link = { method: 'GET' as const, href: 'https://example.com/stac/search?t=2' };

  test('Load more sends the next link and appends the new items', async () => {
    const user = await driveToItemsStep(page(['a', 'b'], { next_page: link }));
    mockSearchStacItems.mockResolvedValueOnce(page(['b', 'c']));

    await user.click(screen.getByRole('button', { name: 'stac.loadMore' }));

    await waitFor(() => expect(screen.getByText('c')).toBeInTheDocument());
    expect(screen.getAllByText('a')).toHaveLength(1);
    expect(screen.getAllByText('b')).toHaveLength(1);
    expect(mockSearchStacItems.mock.calls[1][0]).toMatchObject({
      collections: ['test-col'],
      next_page: link,
    });
    expect(screen.queryByRole('button', { name: 'stac.loadMore' })).not.toBeInTheDocument();
  });

  test('Load more repeats the applied filters, not the edited fields', async () => {
    const user = await driveToItemsStep(page(['a']));
    mockSearchStacItems.mockResolvedValueOnce(page(['b'], { next_page: link }));
    await user.type(screen.getByLabelText('stac.filterBbox'), '-10, -10, 10, 10');
    await user.click(screen.getByRole('button', { name: 'stac.filterApply' }));
    await waitFor(() => screen.getByText('b'));

    await user.clear(screen.getByLabelText('stac.filterBbox'));
    await user.type(screen.getByLabelText('stac.filterBbox'), '0, 0, 1, 1');
    mockSearchStacItems.mockResolvedValueOnce(page(['c']));
    await user.click(screen.getByRole('button', { name: 'stac.loadMore' }));

    await waitFor(() => expect(mockSearchStacItems).toHaveBeenCalledTimes(3));
    expect(mockSearchStacItems.mock.calls[2][0]).toMatchObject({
      bbox: [-10, -10, 10, 10],
      next_page: link,
    });
  });

  test('no Load more on the last page', async () => {
    await driveToItemsStep(page(['a']));
    expect(screen.queryByRole('button', { name: 'stac.loadMore' })).not.toBeInTheDocument();
  });
});

describe('StacImportForm cloud cover filter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const withCloud = (ids: string[]) => ({
    items: ids.map((id) => makeItem(id, { cloud_cover: 12 })),
    matched: ids.length,
    returned: ids.length,
  });

  test('is sent through the query extension when the catalog advertises it', async () => {
    const user = await driveToItemsStep(withCloud(['a']), QUERY);
    mockSearchStacItems.mockResolvedValueOnce(withCloud(['b']));

    await user.type(screen.getByLabelText('stac.filterCloud'), '15');
    await user.click(screen.getByRole('button', { name: 'stac.filterApply' }));

    await waitFor(() => expect(mockSearchStacItems).toHaveBeenCalledTimes(2));
    expect(mockSearchStacItems.mock.calls[1][0]).toMatchObject({
      max_cloud_cover: 15,
      cloud_cover_mode: 'query',
    });
  });

  test('falls back to CQL2 filter when only that is advertised', async () => {
    const user = await driveToItemsStep(withCloud(['a']), CQL);
    mockSearchStacItems.mockResolvedValueOnce(withCloud(['b']));

    await user.type(screen.getByLabelText('stac.filterCloud'), '0');
    await user.click(screen.getByRole('button', { name: 'stac.filterApply' }));

    await waitFor(() => expect(mockSearchStacItems).toHaveBeenCalledTimes(2));
    expect(mockSearchStacItems.mock.calls[1][0]).toMatchObject({
      max_cloud_cover: 0,
      cloud_cover_mode: 'filter',
    });
  });

  test('is hidden when the items carry no cloud cover', async () => {
    await driveToItemsStep(page(['a']), QUERY);
    expect(screen.queryByLabelText('stac.filterCloud')).not.toBeInTheDocument();
  });

  test('is hidden when the catalog advertises neither extension', async () => {
    await driveToItemsStep(withCloud(['a']), []);
    expect(screen.queryByLabelText('stac.filterCloud')).not.toBeInTheDocument();
  });

  test('stays available when a limit empties the list', async () => {
    const user = await driveToItemsStep(withCloud(['a']), QUERY);
    mockSearchStacItems.mockResolvedValueOnce({ items: [], matched: 0, returned: 0 });

    await user.type(screen.getByLabelText('stac.filterCloud'), '1');
    await user.click(screen.getByRole('button', { name: 'stac.filterApply' }));

    await waitFor(() => expect(screen.getByText('stac.noItems')).toBeInTheDocument());
    expect(screen.getByLabelText('stac.filterCloud')).toBeInTheDocument();
  });
});
