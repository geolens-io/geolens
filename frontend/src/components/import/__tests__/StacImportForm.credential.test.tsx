/**
 * feat(#1764) — the STAC import wizard's credential block.
 *
 * Three claims: the credential the user types reaches connect, collections
 * and search as one `auth` object; switching methods discards the other
 * branch's fields rather than sending a stale one; and an incomplete method
 * sends nothing rather than a body the door would refuse.
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

async function typeUrlAndConnect(user: ReturnType<typeof userEvent.setup>) {
  await user.type(
    screen.getByPlaceholderText('https://earth-search.aws.element84.com/v1'),
    'https://catalog.test/v1',
  );
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

    await chooseMethod(user, 'stac.credentialMethodHeader');
    await user.type(
      screen.getByLabelText('stac.credentialHeaderNameLabel'),
      'Ocp-Apim-Subscription-Key',
    );
    await user.type(screen.getByLabelText('stac.credentialHeaderValueLabel'), 'k-secret');
    await typeUrlAndConnect(user);

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

    await chooseMethod(user, 'stac.credentialMethodBearer');
    await user.type(screen.getByLabelText('stac.credentialTokenLabel'), 'tok-secret');
    await typeUrlAndConnect(user);

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

    await chooseMethod(user, 'stac.credentialMethodBearer');
    await user.type(screen.getByLabelText('stac.credentialTokenLabel'), 'tok-secret');
    await chooseMethod(user, 'stac.credentialMethodBasic');
    await user.type(screen.getByLabelText('stac.credentialUsernameLabel'), 'reader');
    await user.type(screen.getByLabelText('stac.credentialPasswordLabel'), 'pw');
    await typeUrlAndConnect(user);

    await waitFor(() => expect(mockConnectStac).toHaveBeenCalled());
    const [, auth] = mockConnectStac.mock.calls[0];
    expect(auth).toEqual({ method: 'basic', username: 'reader', password: 'pw' });
    expect(JSON.stringify(auth)).not.toContain('tok-secret');
  });

  it('sends nothing while a method is incomplete', async () => {
    const user = userEvent.setup();
    render(<StacImportForm />, { wrapper: Wrapper });

    await chooseMethod(user, 'stac.credentialMethodBasic');
    await user.type(screen.getByLabelText('stac.credentialUsernameLabel'), 'reader');
    await typeUrlAndConnect(user);

    await waitFor(() => expect(mockConnectStac).toHaveBeenCalled());
    expect(mockConnectStac).toHaveBeenCalledWith('https://catalog.test/v1', undefined);
  });

  it('sends no credential when the method is none', async () => {
    const user = userEvent.setup();
    render(<StacImportForm />, { wrapper: Wrapper });

    await typeUrlAndConnect(user);
    await waitFor(() => expect(mockConnectStac).toHaveBeenCalled());
    expect(mockConnectStac).toHaveBeenCalledWith('https://catalog.test/v1', undefined);
  });
});
