/**
 * EW-05 — STAC Import size-estimate confirmation step tests.
 *
 * Tests cover:
 *   1. Mixed sizes: total bytes shown where available; partial-unavailable note displayed.
 *   2. All sizes null: per-item count shown; "(size unavailable)" qualifier — NOT "0 B".
 *   3. Confirmation flow: "Import N items" → confirm step; "Confirm and Import" calls import
 *      API; "Back" returns to items step with selection preserved.
 *
 * Strategy: Use vitest module mocking to avoid network calls. Drive the wizard
 * to the 'items' step by mocking API responses, then interact via @testing-library.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { ReactNode } from 'react';
import { StacImportForm } from '../StacImportForm';
import type { StacItemSummary } from '@/types/api';

// ── Mock @/api/stac ───────────────────────────────────────────────────────────
const mockConnectStac = vi.fn();
const mockFetchStacCollections = vi.fn();
const mockSearchStacItems = vi.fn();
const mockImportStacItems = vi.fn();
const mockFetchStacAssetSizes = vi.fn();

vi.mock('@/api/stac', () => ({
  connectStac: (...args: unknown[]) => mockConnectStac(...args),
  fetchStacCollections: (...args: unknown[]) => mockFetchStacCollections(...args),
  searchStacItems: (...args: unknown[]) => mockSearchStacItems(...args),
  importStacItems: (...args: unknown[]) => mockImportStacItems(...args),
  fetchStacAssetSizes: (...args: unknown[]) =>
    mockFetchStacAssetSizes(...args) ?? Promise.resolve({ sizes: [] }),
}));

// ── Mock sonner toast ─────────────────────────────────────────────────────────
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// ── Mock i18n — return the key so assertions are key-based ───────────────────
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      // Substitute interpolation vars so assertions can check values.
      if (!opts) return key;
      let result = key;
      for (const [k, v] of Object.entries(opts)) {
        result = result.replace(`{{${k}}}`, String(v));
      }
      return result;
    },
    i18n: { language: 'en' },
  }),
}));

// ── Test wrapper ──────────────────────────────────────────────────────────────
function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <MemoryRouter>
          {children}
        </MemoryRouter>
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

  // Fill URL + connect
  const urlInput = screen.getByRole('textbox');
  await user.type(urlInput, 'https://example.com/stac');
  await user.click(screen.getByRole('button', { name: /connect/i }));

  // Wait for collections step
  await waitFor(() => screen.getByText('Test Collection'));

  // Click collection
  await user.click(screen.getByText('Test Collection'));

  // Wait for items step
  await waitFor(() => screen.getByText(items[0].title));

  return user;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('StacImportForm — size-estimate confirmation step (EW-05)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('Test 1: mixed sizes — shows total of available bytes and partial-unavailable note', async () => {
    const items: StacItemSummary[] = [
      makeItem({ id: 'item-1', data_asset_size_bytes: 1_000_000 }),
      makeItem({ id: 'item-2', data_asset_size_bytes: 2_000_000 }),
      makeItem({ id: 'item-3', data_asset_size_bytes: null }),
    ];

    const user = await driveToItemsStep(items);

    // Select all items — first checkbox in the action bar is the select-all toggle
    const allCheckboxes = screen.getAllByRole('checkbox');
    await user.click(allCheckboxes[0]); // select-all

    // Click "Import N items" — should advance to confirm step, not importing
    const importButton = screen.getByRole('button', { name: /stac.importItems/i });
    await user.click(importButton);

    // Confirm step should now be visible
    await waitFor(() => {
      expect(screen.getByText('stac.confirm.title')).toBeInTheDocument();
    });

    // Total of 3 MB (1MB + 2MB) should appear somewhere
    expect(screen.getByText(/stac\.confirm\.totalSizeLabel/i)).toBeInTheDocument();
    // The size shown should be the 3 MB total (formatBytes(3_000_000) contains 'MB')
    const sizeText = screen.getByText(/2\.9\s*MB|3\s*MB|MB/);
    expect(sizeText).toBeInTheDocument();

    // 1 item has unavailable size — partial note should appear
    expect(screen.getByText(/stac\.confirm\.partialSizeNote/)).toBeInTheDocument();

    // importStacItems must NOT have been called yet
    expect(mockImportStacItems).not.toHaveBeenCalled();
  });

  test('Test 2: all sizes null — shows per-item count and size-unavailable qualifier', async () => {
    const items: StacItemSummary[] = [
      makeItem({ id: 'item-a', data_asset_size_bytes: null }),
      makeItem({ id: 'item-b', data_asset_size_bytes: null }),
      makeItem({ id: 'item-c', data_asset_size_bytes: null }),
    ];

    const user = await driveToItemsStep(items);

    // Select all — first checkbox is the select-all toggle
    const allCheckboxes = screen.getAllByRole('checkbox');
    await user.click(allCheckboxes[0]);

    // Advance to confirm step
    const importButton = screen.getByRole('button', { name: /stac.importItems/i });
    await user.click(importButton);

    await waitFor(() => {
      expect(screen.getByText('stac.confirm.title')).toBeInTheDocument();
    });

    // Should show sizeUnavailable text, NOT '0 B'
    expect(screen.getByText('stac.confirm.sizeUnavailable')).toBeInTheDocument();
    expect(screen.queryByText('0 B')).not.toBeInTheDocument();

    // Partial note should NOT appear when ALL sizes are unavailable
    expect(screen.queryByText(/stac\.confirm\.partialSizeNote/)).not.toBeInTheDocument();
  });

  test('Test 4: a size missing from the catalog is looked up for the selected items only', async () => {
    const items: StacItemSummary[] = [
      makeItem({ id: 'item-1', data_asset_size_bytes: 1_000_000 }),
      makeItem({ id: 'item-2', data_asset_href: 'https://example.com/two.tif' }),
      makeItem({ id: 'item-3', data_asset_href: 'https://example.com/three.tif' }),
    ];
    mockFetchStacAssetSizes.mockResolvedValue({
      sizes: [{ id: 'item-2', size_bytes: 5_000_000 }],
    });

    const user = await driveToItemsStep(items);
    const boxes = screen.getAllByRole('checkbox');
    await user.click(boxes[1]);
    await user.click(boxes[2]);
    await user.click(screen.getByRole('button', { name: /stac.importItems/i }));
    await waitFor(() => expect(screen.getByText('stac.confirm.title')).toBeInTheDocument());

    await waitFor(() => expect(mockFetchStacAssetSizes).toHaveBeenCalledTimes(1));
    expect(mockFetchStacAssetSizes.mock.calls[0][1]).toEqual([
      { id: 'item-2', href: 'https://example.com/two.tif' },
    ]);
    // 1 MB from the catalog plus 5 MB from the probe.
    await waitFor(() => expect(screen.getByText(/5\.7\s*MB|6\s*MB/)).toBeInTheDocument());
    expect(screen.queryByText(/stac\.confirm\.partialSizeNote/)).not.toBeInTheDocument();
  });

  test('Test 5: a failed lookup leaves the size unavailable', async () => {
    mockFetchStacAssetSizes.mockRejectedValue(new Error('boom'));
    const user = await driveToItemsStep([makeItem({ id: 'item-a' })]);
    await user.click(screen.getAllByRole('checkbox')[0]);
    await user.click(screen.getByRole('button', { name: /stac.importItems/i }));

    await waitFor(() =>
      expect(screen.getByText('stac.confirm.sizeUnavailable')).toBeInTheDocument(),
    );
  });

  test('Test 6: a size looked up for one search is not reused for another search\'s item with the same id', async () => {
    const first = makeItem({ id: 'same-id', data_asset_href: 'https://example.com/one.tif' });
    mockFetchStacAssetSizes.mockResolvedValue({ sizes: [{ id: 'same-id', size_bytes: 5_000_000 }] });
    const user = await driveToItemsStep([first]);
    await user.click(screen.getAllByRole('checkbox')[0]);
    await user.click(screen.getByRole('button', { name: /stac.importItems/i }));
    await waitFor(() => expect(screen.getByText(/MB/)).toBeInTheDocument());

    // Back to the results, then a new search whose item reuses the id.
    await user.click(screen.getByRole('button', { name: 'stac.confirm.backToSelection' }));
    mockSearchStacItems.mockResolvedValue({
      items: [makeItem({ id: 'same-id', data_asset_href: 'https://example.com/two.tif' })],
      matched: 1,
      returned: 1,
    });
    mockFetchStacAssetSizes.mockResolvedValue({ sizes: [{ id: 'same-id', size_bytes: null }] });
    await user.click(screen.getByRole('button', { name: 'stac.filterApply' }));
    await waitFor(() => expect(mockSearchStacItems).toHaveBeenCalledTimes(2));
    await user.click(screen.getAllByRole('checkbox')[0]);
    await user.click(screen.getByRole('button', { name: /stac.importItems/i }));

    await waitFor(() => expect(mockFetchStacAssetSizes).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.getByText('stac.confirm.sizeUnavailable')).toBeInTheDocument(),
    );
    expect(screen.queryByText(/MB/)).not.toBeInTheDocument();
  });

  test('Test 7: with mixed sizes the total and the import wait for the lookup', async () => {
    let resolveSizes!: (v: unknown) => void;
    mockFetchStacAssetSizes.mockReturnValue(
      new Promise((resolve) => {
        resolveSizes = resolve;
      }),
    );
    const items: StacItemSummary[] = [
      makeItem({ id: 'item-1', data_asset_size_bytes: 1_000_000 }),
      makeItem({ id: 'item-2', data_asset_href: 'https://example.com/two.tif' }),
    ];
    const user = await driveToItemsStep(items);
    await user.click(screen.getAllByRole('checkbox')[0]);
    await user.click(screen.getByRole('button', { name: /stac.importItems/i }));

    await waitFor(() => expect(screen.getByText('stac.confirm.sizeChecking')).toBeInTheDocument());
    expect(screen.queryByText(/[KM]B/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /stac\.confirm\.confirmImport/ })).toBeDisabled();

    resolveSizes({ sizes: [{ id: 'item-2', size_bytes: null }] });
    await waitFor(() => expect(screen.getByText(/[KM]B/)).toBeInTheDocument());
    expect(screen.getByText(/stac\.confirm\.partialSizeNote/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /stac\.confirm\.confirmImport/ })).toBeEnabled();
  });

  test('Test 3: confirmation flow — back returns to items; confirm calls importStacItems', async () => {
    const items: StacItemSummary[] = [
      makeItem({ id: 'flow-item-1', data_asset_size_bytes: 500_000 }),
    ];

    mockImportStacItems.mockResolvedValue({
      created: 1,
      skipped: 0,
      errors: 0,
      results: [{ item_id: 'flow-item-1', dataset_id: 'ds-1', status: 'created', error: null }],
    });

    const user = await driveToItemsStep(items);

    // Select first item
    const itemCheckbox = screen.getAllByRole('checkbox')[1]; // index 0 is select-all
    await user.click(itemCheckbox);

    // Advance to confirm step
    const importButton = screen.getByRole('button', { name: /stac.importItems/i });
    await user.click(importButton);

    await waitFor(() => {
      expect(screen.getByText('stac.confirm.title')).toBeInTheDocument();
    });

    // Click "Back to selection" — should return to items step with selection preserved
    await user.click(screen.getByRole('button', { name: /stac\.confirm\.backToSelection/i }));
    await waitFor(() => {
      expect(screen.getByText('flow-item-1')).toBeInTheDocument();
    });
    expect(screen.queryByText('stac.confirm.title')).not.toBeInTheDocument();

    // Advance to confirm again
    await user.click(screen.getByRole('button', { name: /stac.importItems/i }));
    await waitFor(() => {
      expect(screen.getByText('stac.confirm.title')).toBeInTheDocument();
    });

    // Click "Confirm and Import" — should call importStacItems
    await user.click(screen.getByRole('button', { name: /stac\.confirm\.confirmImport/i }));

    await waitFor(() => {
      expect(mockImportStacItems).toHaveBeenCalledTimes(1);
    });
  });
});
