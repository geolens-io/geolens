/**
 * feat(#1764) — the STAC import wizard's credential block. What is pinned:
 * one `auth` object reaches connect, collections and search; a stale
 * method's or a stale catalog's fields are never sent.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { ReactNode } from 'react';
import { StacImportForm } from '../StacImportForm';

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

const CATALOG = {
  id: 'test-catalog',
  title: 'Test Catalog',
  description: '',
  stac_version: '1.0.0',
  conforms_to: [],
  url: 'https://catalog.test/v1',
};

const COLLECTION = {
  id: 'test-col',
  title: 'Test Collection',
  description: '',
  license: null,
  keywords: [],
  bbox: null,
  temporal_start: null,
  temporal_end: null,
  item_count: 1,
};

// Radix Select needs these in jsdom.
beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

beforeEach(() => {
  vi.clearAllMocks();
  mockConnectStac.mockResolvedValue(CATALOG);
  mockFetchStacCollections.mockResolvedValue({ collections: [COLLECTION] });
  mockSearchStacItems.mockResolvedValue({ items: [], matched: 0, returned: 0 });
});

/** Choose a method in the credential select. */
async function chooseMethod(user: ReturnType<typeof userEvent.setup>, label: string) {
  await user.click(screen.getByLabelText('stac.credentialMethodLabel'));
  await user.click(await screen.findByRole('option', { name: label }));
}

async function typeUrl(
  user: ReturnType<typeof userEvent.setup>,
  url = 'https://catalog.test/v1',
) {
  await user.type(screen.getByPlaceholderText('https://earth-search.aws.element84.com/v1'), url);
}

async function connect(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'stac.connect' }));
}

describe('StacImportForm credential block', () => {
  it('renders the credential block on the idle step', () => {
    render(<StacImportForm />, { wrapper: Wrapper });
    expect(screen.getByTestId('stac-credential-block')).toBeInTheDocument();
  });

  it('sends a header-key credential to connect and collections', async () => {
    const user = userEvent.setup();
    render(<StacImportForm />, { wrapper: Wrapper });

    await typeUrl(user);
    await chooseMethod(user, 'stac.credentialMethodHeader');
    await user.type(
      screen.getByLabelText('stac.credentialHeaderNameLabel'),
      'Ocp-Apim-Subscription-Key',
    );
    await user.type(screen.getByLabelText('stac.credentialHeaderValueLabel'), 'k-secret');
    await connect(user);

    const expected = {
      method: 'header',
      header_name: 'Ocp-Apim-Subscription-Key',
      header_value: 'k-secret',
    };
    await waitFor(() =>
      expect(mockConnectStac).toHaveBeenCalledWith('https://catalog.test/v1', expected),
    );
    expect(mockFetchStacCollections).toHaveBeenCalledWith('https://catalog.test/v1', expected);
  });

  it('sends the same credential on the item search', async () => {
    const user = userEvent.setup();
    render(<StacImportForm />, { wrapper: Wrapper });

    await typeUrl(user);
    await chooseMethod(user, 'stac.credentialMethodBearer');
    await user.type(screen.getByLabelText('stac.credentialTokenLabel'), 'tok-secret');
    await connect(user);

    await user.click(await screen.findByText('Test Collection'));
    await waitFor(() =>
      expect(mockSearchStacItems).toHaveBeenCalledWith(
        expect.objectContaining({ auth: { method: 'bearer', token: 'tok-secret' } }),
      ),
    );
  });

  it('discards the previous method fields when the method changes', async () => {
    const user = userEvent.setup();
    render(<StacImportForm />, { wrapper: Wrapper });

    await typeUrl(user);
    await chooseMethod(user, 'stac.credentialMethodBearer');
    await user.type(screen.getByLabelText('stac.credentialTokenLabel'), 'tok-secret');
    await chooseMethod(user, 'stac.credentialMethodBasic');
    await user.type(screen.getByLabelText('stac.credentialUsernameLabel'), 'reader');
    await user.type(screen.getByLabelText('stac.credentialPasswordLabel'), 'pw');
    await connect(user);

    await waitFor(() => expect(mockConnectStac).toHaveBeenCalled());
    const [, auth] = mockConnectStac.mock.calls[0];
    expect(auth).toEqual({ method: 'basic', username: 'reader', password: 'pw' });
    expect(JSON.stringify(auth)).not.toContain('tok-secret');
  });

  it('sends nothing while a method is incomplete', async () => {
    const user = userEvent.setup();
    render(<StacImportForm />, { wrapper: Wrapper });

    await typeUrl(user);
    await chooseMethod(user, 'stac.credentialMethodBasic');
    await user.type(screen.getByLabelText('stac.credentialUsernameLabel'), 'reader');
    await connect(user);

    await waitFor(() => expect(mockConnectStac).toHaveBeenCalled());
    expect(mockConnectStac).toHaveBeenCalledWith('https://catalog.test/v1', undefined);
  });

  it('sends no credential when the method is none', async () => {
    const user = userEvent.setup();
    render(<StacImportForm />, { wrapper: Wrapper });

    await typeUrl(user);
    await connect(user);
    await waitFor(() => expect(mockConnectStac).toHaveBeenCalled());
    expect(mockConnectStac).toHaveBeenCalledWith('https://catalog.test/v1', undefined);
  });

  it('tells import that browsing the catalog needed a credential', async () => {
    const user = userEvent.setup();
    mockSearchStacItems.mockResolvedValue({
      items: [
        {
          id: 'item-1',
          collection: 'test-col',
          item_href: null,
          title: 'item-1',
          bbox: null,
          datetime: null,
          datetime_start: null,
          datetime_end: null,
          epsg: null,
          gsd: null,
          cloud_cover: null,
          data_asset_href: 'https://catalog.test/v1/assets/a.tif',
          data_asset_type: null,
          data_asset_key: 'data',
          data_asset_size_bytes: null,
          thumbnail_href: null,
          asset_count: 1,
        },
      ],
      matched: 1,
      returned: 1,
    });
    mockImportStacItems.mockResolvedValue({
      created: 1,
      skipped: 0,
      errors: 0,
      results: [{ item_id: 'item-1', dataset_id: 'ds-1', status: 'created', error: null }],
    });
    render(<StacImportForm />, { wrapper: Wrapper });

    await typeUrl(user);
    await chooseMethod(user, 'stac.credentialMethodBearer');
    await user.type(screen.getByLabelText('stac.credentialTokenLabel'), 'tok-secret');
    await connect(user);

    await user.click(await screen.findByText('Test Collection'));
    await user.click((await screen.findAllByRole('checkbox'))[0]);
    await user.click(screen.getByRole('button', { name: /stac.importItems/i }));
    await user.click(
      await screen.findByRole('button', { name: /stac\.confirm\.confirmImport/i }),
    );

    await waitFor(() => expect(mockImportStacItems).toHaveBeenCalledTimes(1));
    // A boolean, never the credential.
    const call = mockImportStacItems.mock.calls[0];
    expect(call[3]).toBe(true);
    expect(JSON.stringify(call)).not.toContain('tok-secret');
  });

  it('drops a credential typed for one catalog when the URL moves to another', async () => {
    const user = userEvent.setup();
    mockConnectStac.mockRejectedValueOnce(new Error('nope'));
    render(<StacImportForm />, { wrapper: Wrapper });

    await typeUrl(user);
    await chooseMethod(user, 'stac.credentialMethodBearer');
    await user.type(screen.getByLabelText('stac.credentialTokenLabel'), 'first-secret');
    await connect(user);
    await waitFor(() => expect(mockConnectStac).toHaveBeenCalledTimes(1));

    await user.clear(
      screen.getByPlaceholderText('https://earth-search.aws.element84.com/v1'),
    );
    await typeUrl(user, 'https://other.test/v1');
    await connect(user);

    await waitFor(() => expect(mockConnectStac).toHaveBeenCalledTimes(2));
    // The first catalog got the key it was typed for; the second gets none.
    expect(mockConnectStac).toHaveBeenLastCalledWith('https://other.test/v1', undefined);
    expect(JSON.stringify(mockConnectStac.mock.calls[1])).not.toContain('first-secret');
  });
});
