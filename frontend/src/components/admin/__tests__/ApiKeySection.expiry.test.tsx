import userEvent from '@testing-library/user-event';
import { act } from '@testing-library/react';
import { render, screen } from '@/test/test-utils';
import { ApiKeySection } from '../ApiKeySection';
import type { ApiKeyResponse } from '@/types/api';

const { mockUseApiKeys, mockCreate } = vi.hoisted(() => ({
  mockUseApiKeys: vi.fn(),
  mockCreate: vi.fn(),
}));

vi.mock('@/hooks/use-admin', () => ({
  useApiKeys: (...args: unknown[]) => mockUseApiKeys(...args),
  useCreateApiKey: () => ({ mutateAsync: mockCreate, error: null, isPending: false }),
  useRevokeApiKey: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('@/lib/format', () => ({
  formatDate: () => '2026-01-01',
}));

function makeKey(overrides: Partial<ApiKeyResponse> = {}): ApiKeyResponse {
  return {
    id: 'k1',
    user_id: 'u1',
    name: 'ci',
    fingerprint: null,
    is_active: true,
    expires_at: null,
    scope: 'full',
    created_at: '2026-08-01T00:00:00Z',
    last_used_at: null,
    ...overrides,
  };
}

function listing(keys: ApiKeyResponse[]) {
  mockUseApiKeys.mockReturnValue({ items: keys, total: keys.length, isLoading: false, hasMore: false });
}

// Radix Select needs these in jsdom.
beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

describe('ApiKeySection expiry', () => {
  beforeEach(() => {
    mockCreate.mockReset();
    listing([]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('sends an expires_at one year out when the 1 year preset is chosen', async () => {
    const user = userEvent.setup();
    render(<ApiKeySection userId="u1" />);
    vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-01-10T12:00:00Z') });

    await user.click(screen.getByRole('button', { name: /apiKeys\.createKey/ }));
    await user.type(screen.getByPlaceholderText(/apiKeys\.keyName/), 'svc');
    await user.click(screen.getByRole('combobox', { name: 'apiKeys.expiry' }));
    await user.click(await screen.findByRole('option', { name: 'apiKeys.expiryOptions.1y' }));
    await user.click(screen.getByRole('button', { name: 'common:create' }));

    expect(mockCreate).toHaveBeenCalledWith(
      expect.objectContaining({ userId: 'u1', name: 'svc', expiresAt: '2027-01-10T12:00:00.000Z' }),
    );
  });

  it('defaults to a key that never expires', async () => {
    const user = userEvent.setup();
    render(<ApiKeySection userId="u1" />);

    await user.click(screen.getByRole('button', { name: /apiKeys\.createKey/ }));
    await user.type(screen.getByPlaceholderText(/apiKeys\.keyName/), 'svc');
    await user.click(screen.getByRole('button', { name: 'common:create' }));

    expect(mockCreate).toHaveBeenCalledWith(expect.objectContaining({ expiresAt: null }));
  });

  it('shows the expiry date and marks an expired key', () => {
    listing([makeKey({ expires_at: '2020-01-01T00:00:00Z' })]);
    render(<ApiKeySection userId="u1" />);

    expect(screen.getAllByText('apiKeys.expired').length).toBeGreaterThan(0);
    expect(screen.getByText(/apiKeys\.expiredOn/)).toBeInTheDocument();
  });

  it('gives an expired key the inactive status dot', () => {
    listing([makeKey({ expires_at: '2020-01-01T00:00:00Z' })]);
    const { container } = render(<ApiKeySection userId="u1" />);

    expect(container.querySelector('span.rounded-full.bg-destructive')).toBeInTheDocument();
    expect(container.querySelector('span.rounded-full.bg-success')).not.toBeInTheDocument();
  });

  it('titles the dot of an expired key as expired', () => {
    listing([makeKey({ expires_at: '2020-01-01T00:00:00Z' })]);
    const { container } = render(<ApiKeySection userId="u1" />);

    expect(container.querySelector('span.rounded-full')).toHaveAttribute('title', 'apiKeys.expired');
  });

  it('keeps a revoked key revoked but still dates its past expiry as expired', () => {
    listing([makeKey({ is_active: false, expires_at: '2020-01-01T00:00:00Z' })]);
    const { container } = render(<ApiKeySection userId="u1" />);

    expect(container.querySelector('span.rounded-full')).toHaveAttribute('title', 'apiKeys.revoked');
    expect(screen.queryByText('apiKeys.expired')).not.toBeInTheDocument();
    expect(screen.getByText(/apiKeys\.expiredOn/)).toBeInTheDocument();
    expect(screen.queryByText(/apiKeys\.expiresOn/)).not.toBeInTheDocument();
  });

  it('flips an open list to expired when a key passes its expiry', () => {
    vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] });
    vi.setSystemTime(new Date('2026-01-10T12:00:00Z'));
    listing([makeKey({ expires_at: '2026-01-10T12:01:00Z' })]);
    const { container } = render(<ApiKeySection userId="u1" />);
    expect(container.querySelector('span.rounded-full')).toHaveAttribute('title', 'apiKeys.active');

    act(() => {
      vi.advanceTimersByTime(61_000);
    });

    expect(container.querySelector('span.rounded-full')).toHaveAttribute('title', 'apiKeys.expired');
  });

  it('badges a key bound to one dataset', () => {
    listing([makeKey({ scope: 'dataset_write', dataset_id: 'ds-1' })]);
    render(<ApiKeySection userId="u1" />);
    expect(screen.getByText('apiKeys.scopeDatasetWrite')).toBeInTheDocument();
  });
});
