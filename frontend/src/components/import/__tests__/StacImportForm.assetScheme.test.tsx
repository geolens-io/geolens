/**
 * STAC items whose data asset GeoLens can't fetch — a catalog that publishes
 * an item's only asset as `s3://...` (Earth Search's Copernicus DEM and
 * similar collections) rather than an http(s) URL, one signed with a
 * credential GeoLens won't store, one too long to store, or no asset at all.
 *
 * Eligibility comes from the search response's own
 * `data_asset_import_refusal` field — the search endpoint's prediction of
 * what `/import`'s own validator would refuse — not from re-deriving the
 * rule client-side, so the two can never drift apart.
 *
 * Tests cover:
 *   1. An item flagged `not_http` renders disabled with a reason; select-all
 *      skips it; a plain https:// item in the same list stays selectable.
 *   2. An item with no data asset at all is disabled the same way.
 *   3. An item flagged `credentials` (a signed https:// href) is disabled,
 *      and a submitted import carries only the valid items.
 *   4. An item flagged `too_long` is disabled with its own reason.
 *   5. A refused import (the scheme check, expressed as a 422) shows its
 *      reason next to the Import action, not below the item list.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { ReactNode } from 'react';
import { StacImportForm } from '../StacImportForm';
import { ApiError } from '@/api/client';
import type { StacItemSummary } from '@/types/api';

const mockConnectStac = vi.fn();
const mockFetchStacCollections = vi.fn();
const mockSearchStacItems = vi.fn();
const mockImportStacItems = vi.fn();

vi.mock('@/api/stac', () => ({
  connectStac: (...args: unknown[]) => mockConnectStac(...args),
  fetchStacCollections: (...args: unknown[]) => mockFetchStacCollections(...args),
  searchStacItems: (...args: unknown[]) => mockSearchStacItems(...args),
  importStacItems: (...args: unknown[]) => mockImportStacItems(...args),
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// Return the key, plus its interpolation values in a stable "k=v" suffix,
// so assertions can check both which key rendered and what it was given
// (the scheme, or the importable/total counts) without a real i18next.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (!opts) return key;
      const values = Object.entries(opts).map(([k, v]) => `${k}=${v}`).join(',');
      return `${key}(${values})`;
    },
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

function makeItem(overrides: Partial<StacItemSummary> & { id: string }): StacItemSummary {
  return {
    collection: 'test-col',
    item_href: null,
    title: overrides.id,
    bbox: null,
    datetime: null,
    datetime_start: null,
    datetime_end: null,
    epsg: null,
    gsd: null,
    cloud_cover: null,
    data_asset_href: 'https://example.com/data.tif',
    data_asset_type: 'image/tiff; application=geotiff; profile=cloud-optimized',
    data_asset_key: 'data',
    data_asset_size_bytes: null,
    data_asset_import_refusal: null,
    thumbnail_href: null,
    asset_count: 1,
    ...overrides,
  };
}

/** Drive wizard from idle → items step via mocked API. Returns the user-event instance. */
async function driveToItemsStep(items: StacItemSummary[]) {
  const user = userEvent.setup();

  mockConnectStac.mockResolvedValue({
    id: 'test-catalog',
    title: 'Test Catalog',
    description: '',
    stac_version: '1.0.0',
    conforms_to: [],
    url: 'https://example.com/stac',
  });
  mockFetchStacCollections.mockResolvedValue({
    collections: [
      {
        id: 'test-col',
        title: 'Test Collection',
        description: 'A test collection',
        license: null,
        keywords: [],
        bbox: null,
        temporal_start: null,
        temporal_end: null,
        item_count: null,
      },
    ],
  });
  mockSearchStacItems.mockResolvedValue({
    items,
    matched: items.length,
    returned: items.length,
  });

  render(
    <Wrapper>
      <StacImportForm />
    </Wrapper>,
  );

  const urlInput = screen.getByRole('textbox');
  await user.type(urlInput, 'https://example.com/stac');
  await user.click(screen.getByRole('button', { name: /connect/i }));

  await waitFor(() => screen.getByText('Test Collection'));
  await user.click(screen.getByText('Test Collection'));
  await waitFor(() => screen.getByText(items[0].title));

  return user;
}

describe('StacImportForm — items whose data asset GeoLens cannot fetch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('an s3:// item is disabled with a reason; select-all skips it; an https:// item stays selectable', async () => {
    const items: StacItemSummary[] = [
      makeItem({ id: 'readable-item', data_asset_href: 'https://example.com/data.tif' }),
      makeItem({
        id: 's3-item',
        data_asset_href: 's3://copernicus-dem-90m/tile.tif',
        data_asset_import_refusal: 'not_http',
      }),
    ];

    const user = await driveToItemsStep(items);

    const [selectAll, readableCheckbox, s3Checkbox] = screen.getAllByRole('checkbox');

    expect(readableCheckbox).toBeEnabled();
    expect(readableCheckbox.getAttribute('aria-describedby')).toBeNull();

    expect(s3Checkbox).toBeDisabled();
    const describedById = s3Checkbox.getAttribute('aria-describedby');
    expect(describedById).toBeTruthy();
    // The reason is a real element the checkbox is wired to, not only a
    // hover tooltip, and it names the scheme that defeated it.
    expect(document.getElementById(describedById!)).toHaveTextContent(
      'stac.unsupportedAssetScheme(scheme=s3)',
    );

    // Select-all must skip the item GeoLens can't fetch.
    await user.click(selectAll);
    expect(readableCheckbox).toBeChecked();
    expect(s3Checkbox).not.toBeChecked();

    // The selected count is scoped to importable items: 1 of 1 importable,
    // not 1 of 2 — otherwise "select all" would look incomplete.
    expect(screen.getByText(/stac\.selectedCount/)).toHaveTextContent(
      'stac.selectedCount(selected=1,total=1)',
    );
  });

  test('an item with no data asset at all is disabled the same way', async () => {
    const items: StacItemSummary[] = [makeItem({ id: 'no-asset-item', data_asset_href: null })];

    await driveToItemsStep(items);

    const [, noAssetCheckbox] = screen.getAllByRole('checkbox');
    expect(noAssetCheckbox).toBeDisabled();
    const describedById = noAssetCheckbox.getAttribute('aria-describedby');
    expect(describedById).toBeTruthy();
    expect(document.getElementById(describedById!)).toHaveTextContent('stac.noCogAsset');
  });

  test('a signed https item is flagged by the server; select-all skips it and only valid items are imported', async () => {
    const items: StacItemSummary[] = [
      makeItem({ id: 'plain-item', data_asset_href: 'https://example.com/data.tif' }),
      makeItem({
        id: 'signed-item',
        data_asset_href: 'https://example.com/data.tif?X-Amz-Signature=abc123',
        data_asset_import_refusal: 'credentials',
      }),
    ];
    mockImportStacItems.mockResolvedValue({
      created: 1,
      skipped: 0,
      errors: 0,
      results: [{ item_id: 'plain-item', dataset_id: 'ds-1', status: 'created', error: null }],
    });

    const user = await driveToItemsStep(items);
    const [selectAll, plainCheckbox, signedCheckbox] = screen.getAllByRole('checkbox');

    expect(plainCheckbox).toBeEnabled();
    expect(signedCheckbox).toBeDisabled();
    const describedById = signedCheckbox.getAttribute('aria-describedby');
    expect(describedById).toBeTruthy();
    expect(document.getElementById(describedById!)).toHaveTextContent(
      'stac.assetHasCredentials',
    );

    // Select-all must skip the signed item too.
    await user.click(selectAll);
    expect(plainCheckbox).toBeChecked();
    expect(signedCheckbox).not.toBeChecked();

    await user.click(screen.getByRole('button', { name: /stac.importItems/i }));
    await waitFor(() => screen.getByText('stac.confirm.title'));
    await user.click(screen.getByRole('button', { name: /stac\.confirm\.confirmImport/i }));

    await waitFor(() => expect(mockImportStacItems).toHaveBeenCalledTimes(1));
    // startStacImport(url, items, ...) — items is the second positional arg.
    const submittedItems = mockImportStacItems.mock.calls[0][1];
    expect(submittedItems).toHaveLength(1);
    expect(submittedItems[0].id).toBe('plain-item');
  });

  test('an item flagged too_long by the server is disabled with its own reason', async () => {
    const items: StacItemSummary[] = [
      makeItem({
        id: 'overlong-item',
        data_asset_href: `https://example.com/${'a'.repeat(4090)}.tif`,
        data_asset_import_refusal: 'too_long',
      }),
    ];

    await driveToItemsStep(items);

    const [, checkbox] = screen.getAllByRole('checkbox');
    expect(checkbox).toBeDisabled();
    const describedById = checkbox.getAttribute('aria-describedby');
    expect(describedById).toBeTruthy();
    expect(document.getElementById(describedById!)).toHaveTextContent('stac.assetHrefTooLong');
  });

  test('a refused import shows its reason next to the Import action, not below the item list', async () => {
    const items: StacItemSummary[] = [makeItem({ id: 'flow-item' })];
    mockImportStacItems.mockRejectedValue(
      new ApiError('data_asset_href must be an http or https address.', 422),
    );

    const user = await driveToItemsStep(items);

    await user.click(screen.getAllByRole('checkbox')[1]);
    await user.click(screen.getByRole('button', { name: /stac.importItems/i }));
    await waitFor(() => screen.getByText('stac.confirm.title'));
    await user.click(screen.getByRole('button', { name: /stac\.confirm\.confirmImport/i }));

    const actionBar = await screen.findByTestId('stac-items-action-bar');
    const errorNode = await within(actionBar).findByTestId('stac-import-error');
    expect(errorNode).toHaveTextContent('data_asset_href must be an http or https address.');

    // Not sitting below the (potentially 50-row) item list.
    const itemsList = screen.getByTestId('stac-items-list');
    expect(within(itemsList).queryByTestId('stac-import-error')).not.toBeInTheDocument();
  });
});
