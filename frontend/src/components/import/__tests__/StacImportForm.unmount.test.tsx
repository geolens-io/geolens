/**
 * fix(#1712): a STAC import must survive the form unmounting.
 *
 * The Import page renders tabs conditionally, so switching away mid-import
 * unmounts StacImportForm. `importStacItems` keeps running server-side and
 * creates datasets SYNCHRONOUSLY (no job id — see
 * api/stac-import-session.ts's module docstring for why this tab's actual
 * shape differs from what #1712 assumed by analogy with the Service tab).
 * An unmount mid-request loses the created/skipped/error counts even though
 * the datasets it created are real; this session protects that response.
 * Mirrors UrlImportForm.unmount.test.tsx (#1708) for this tab's shape.
 */
import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { StacImportForm } from '../StacImportForm';
import { clearStacImport, peekStacImport } from '@/api/stac-import-session';
import { useAuthStore } from '@/stores/auth-store';
import type { StacItemSummary, UserResponse } from '@/types/api';

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

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
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
    thumbnail_href: null,
    asset_count: 1,
    ...overrides,
  };
}

const ITEM = makeItem({ id: 'flow-item-1' });

/** Drive the wizard from idle through the confirm step, item selected. */
async function driveToConfirmStep() {
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
  mockSearchStacItems.mockResolvedValue({ items: [ITEM], matched: 1, returned: 1 });

  const view = render(<StacImportForm />);

  const urlInput = screen.getByRole('textbox');
  await user.type(urlInput, 'https://example.com/stac');
  await user.click(screen.getByRole('button', { name: /connect/i }));
  await waitFor(() => screen.getByText('Test Collection'));
  await user.click(screen.getByText('Test Collection'));
  await waitFor(() => screen.getByText(ITEM.title));

  const itemCheckbox = screen.getAllByRole('checkbox')[1];
  await user.click(itemCheckbox);
  await user.click(screen.getByRole('button', { name: /stac.importItems/i }));
  await waitFor(() => expect(screen.getByText('stac.confirm.title')).toBeInTheDocument());

  return { user, view };
}

const initialAuthState = useAuthStore.getState();

beforeEach(() => {
  vi.clearAllMocks();
  clearStacImport();
  useAuthStore.setState(initialAuthState, true);
});

afterEach(() => {
  clearStacImport();
  useAuthStore.setState(initialAuthState, true);
});

describe('StacImportForm unmount survival', () => {
  test('a result returned while unmounted is captured', async () => {
    let resolveImport!: (v: unknown) => void;
    mockImportStacItems.mockReturnValue(
      new Promise((resolve) => {
        resolveImport = resolve;
      }),
    );

    const { user, view } = await driveToConfirmStep();
    await user.click(screen.getByRole('button', { name: /stac\.confirm\.confirmImport/i }));
    await waitFor(() => expect(mockImportStacItems).toHaveBeenCalledTimes(1));

    // Switch tabs: the Import page unmounts the form.
    view.unmount();

    // The server finishes anyway.
    resolveImport({
      created: 1,
      skipped: 0,
      errors: 0,
      results: [{ item_id: 'flow-item-1', dataset_id: 'ds-1', status: 'created', error: null }],
    });

    await waitFor(() => expect(peekStacImport()?.status).toBe('fulfilled'));
    expect(peekStacImport()?.result?.created).toBe(1);
  });

  test('remount adopts the in-flight import instead of starting a second one', async () => {
    mockImportStacItems.mockReturnValue(new Promise(() => {}));

    const { user, view } = await driveToConfirmStep();
    await user.click(screen.getByRole('button', { name: /stac\.confirm\.confirmImport/i }));
    await waitFor(() => expect(mockImportStacItems).toHaveBeenCalledTimes(1));

    view.unmount();
    render(<StacImportForm />);

    // Still exactly one server-side import, and the remounted form shows the
    // in-flight spinner rather than the idle URL form.
    expect(mockImportStacItems).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByText('stac.importing')).toBeInTheDocument());
  });

  test('a failure while unmounted settles the session and does not resume', async () => {
    let rejectImport!: (e: unknown) => void;
    mockImportStacItems.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectImport = reject;
      }),
    );

    const { user, view } = await driveToConfirmStep();
    await user.click(screen.getByRole('button', { name: /stac\.confirm\.confirmImport/i }));
    await waitFor(() => expect(mockImportStacItems).toHaveBeenCalledTimes(1));

    view.unmount();
    rejectImport(new Error('boom'));

    // The rejection is handled at module scope (marked handled in
    // startStacImport), so it never surfaces as an unhandled rejection.
    await waitFor(() => expect(peekStacImport()?.status).toBe('rejected'));

    // Remounting can't rebuild the collection/item list this step needs
    // (only the import response is sessioned), so it degrades to the idle
    // URL form with the failure surfaced, and clears the session — the
    // graceful-degradation path documented in the component.
    render(<StacImportForm />);
    await waitFor(() => expect(screen.getByRole('textbox')).toBeInTheDocument());
    expect(peekStacImport()).toBeNull();
  });

  test('successful import releases the session', async () => {
    mockImportStacItems.mockResolvedValue({
      created: 1,
      skipped: 0,
      errors: 0,
      results: [{ item_id: 'flow-item-1', dataset_id: 'ds-1', status: 'created', error: null }],
    });

    const { user } = await driveToConfirmStep();
    expect(peekStacImport()).toBeNull(); // not started until confirmed

    await user.click(screen.getByRole('button', { name: /stac\.confirm\.confirmImport/i }));
    await waitFor(() => expect(screen.getByText('stac.importComplete')).toBeInTheDocument());

    expect(peekStacImport()).toBeNull();
  });

  // fix(codex #1763 r3): the session used to restore only `importResult` on
  // adoption, so "Back to Results" (which sets `step` back to 'items')
  // rendered nothing — that branch guards on `selectedCollection` and
  // `catalogInfo`, both null on a fresh mount. The session now carries the
  // search context captured when the import started, restored alongside
  // the result.
  test('an adopted result still supports "Back to Results", showing the same items', async () => {
    let resolveImport!: (v: unknown) => void;
    mockImportStacItems.mockReturnValue(
      new Promise((resolve) => {
        resolveImport = resolve;
      }),
    );

    const { user, view } = await driveToConfirmStep();
    await user.click(screen.getByRole('button', { name: /stac\.confirm\.confirmImport/i }));
    await waitFor(() => expect(mockImportStacItems).toHaveBeenCalledTimes(1));

    // Switch tabs while the import is still in flight — a manually-settled
    // promise guarantees this mount never sees the resolution itself, so
    // the NEXT mount is the one that has to adopt the result.
    view.unmount();
    resolveImport({
      created: 1,
      skipped: 0,
      errors: 0,
      results: [{ item_id: 'flow-item-1', dataset_id: 'ds-1', status: 'created', error: null }],
    });
    await waitFor(() => expect(peekStacImport()?.status).toBe('fulfilled'));

    render(<StacImportForm />);
    await waitFor(() => expect(screen.getByText('stac.importComplete')).toBeInTheDocument());

    await user.click(screen.getByText('stac.backToResults'));

    // The items step renders again, with the same collection and result the
    // session captured at import time — not the empty URL form the missing
    // context used to fall through to.
    await waitFor(() => expect(screen.getByText(ITEM.title)).toBeInTheDocument());
    expect(screen.getByText('Test Collection')).toBeInTheDocument();
  });

  test('a different identity does not adopt the import', async () => {
    useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
    mockImportStacItems.mockReturnValue(new Promise(() => {}));

    const { user, view } = await driveToConfirmStep();
    await user.click(screen.getByRole('button', { name: /stac\.confirm\.confirmImport/i }));
    await waitFor(() => expect(mockImportStacItems).toHaveBeenCalledTimes(1));
    view.unmount();

    // A different identity signs in before the next mount.
    useAuthStore.setState({ token: 't2', user: { id: 'user-2' } as UserResponse });

    render(<StacImportForm />);

    // No adoption: the second identity sees the idle URL form, and does not
    // start a second import against the first identity's abandoned request.
    await waitFor(() => expect(screen.getByRole('textbox')).toBeInTheDocument());
    expect(mockImportStacItems).toHaveBeenCalledTimes(1);
    expect(peekStacImport()).toBeNull();
  });
});
