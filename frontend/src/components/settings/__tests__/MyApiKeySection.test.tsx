/**
 * Regression gate for the MyApiKeySection
 * control semantics.
 *
 * Asserts:
 * - Create-form name input has an accessible name via FieldLabel.
 * - Active / revoked status is rendered as visible text, not color+title only.
 * - The icon-only revoke button has an accessible name.
 * - Create and revoke mutation errors are announced via role=alert.
 */
import userEvent from '@testing-library/user-event';
import { act } from '@testing-library/react';
import { render, screen } from '@/test/test-utils';
import { vi } from 'vitest';
import { MyApiKeySection } from '@/components/settings/MyApiKeySection';
import { useMyApiKeys, useCreateMyApiKey, useRevokeMyApiKey } from '@/hooks/use-api-keys';
import type { MyApiKeyResponse } from '@/types/api';

// ── mock react-i18next ──────────────────────────────────────────────────────
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// ── mock api-key hooks ───────────────────────────────────────────────────────
vi.mock('@/hooks/use-api-keys', () => ({
  useMyApiKeys: vi.fn(),
  useCreateMyApiKey: vi.fn(),
  useRevokeMyApiKey: vi.fn(),
}));

// ── stub dialogs that need extra context ──────────────────────────────────────
vi.mock('@/components/admin/ApiKeyRevealDialog', () => ({
  ApiKeyRevealDialog: () => null,
}));

// ── mock date formatter ───────────────────────────────────────────────────────
vi.mock('@/lib/format', () => ({
  formatDate: () => '2026-01-01',
}));

// ── default mutation shapes ────────────────────────────────────────────────
const defaultCreateMutation = {
  mutateAsync: vi.fn(),
  isPending: false,
  error: null,
};

const defaultRevokeMutation = {
  mutateAsync: vi.fn(),
  isPending: false,
  error: null,
};

function makeKey(overrides: Partial<MyApiKeyResponse> = {}): MyApiKeyResponse {
  return {
    id: 'key-1',
    name: 'test-key',
    fingerprint: 'abcd1234…wxyz',
    is_active: true,
    expires_at: null,
    scope: 'full',
    created_at: '2026-01-01T00:00:00Z',
    last_used_at: null,
    ...overrides,
  };
}

describe('GLUX-002 / GLUX-014: MyApiKeySection control semantics', () => {
  beforeEach(() => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    vi.mocked(useCreateMyApiKey).mockReturnValue(
      defaultCreateMutation as unknown as ReturnType<typeof useCreateMyApiKey>,
    );

    vi.mocked(useRevokeMyApiKey).mockReturnValue(
      defaultRevokeMutation as unknown as ReturnType<typeof useRevokeMyApiKey>,
    );
  });

  it('create-form name input is queryable by its accessible name (GLUX-002)', async () => {
    const user = userEvent.setup();
    render(<MyApiKeySection />);

    // The form is hidden until the user opens it; click "create key" to reveal it
    await user.click(screen.getByRole('button', { name: 'admin:apiKeys.createKey' }));

    // FieldLabel renders <label htmlFor="api-key-name-input"> which associates
    // the label with the Input that has id="api-key-name-input".
    const nameInput = screen.getByLabelText('admin:apiKeys.keyName');
    expect(nameInput).toBeInTheDocument();
    expect(nameInput.tagName.toLowerCase()).toBe('input');
  });

  it('active key renders visible status text (not sr-only only) (GLUX-014)', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ is_active: true })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);

    // The badge renders visible text; it must NOT be in a sr-only element
    const activeText = screen.getByText('admin:apiKeys.active');
    expect(activeText).toBeInTheDocument();
    expect(activeText).not.toHaveClass('sr-only');
  });

  it('revoked key renders visible status text (not sr-only only) (GLUX-014)', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ is_active: false })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);

    const revokedText = screen.getByText('admin:apiKeys.revoked');
    expect(revokedText).toBeInTheDocument();
    expect(revokedText).not.toHaveClass('sr-only');
  });

  it('renders the non-secret key fingerprint', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ fingerprint: 'abcd1234…wxyz' })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);

    expect(screen.getByText('abcd1234…wxyz')).toBeVisible();
  });

  it('revoke button is queryable by its accessible name (GLUX-002)', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ is_active: true })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);

    // The icon-only Trash button carries aria-label so it has an accessible name
    const revokeButton = screen.getByRole('button', {
      name: 'admin:apiKeys.revokeDialog.revoke',
    });
    expect(revokeButton).toBeInTheDocument();
  });

  it('create mutation error is rendered inside role=alert (GLUX-014)', () => {
    vi.mocked(useCreateMyApiKey).mockReturnValue({
      ...defaultCreateMutation,
      error: new Error('Failed to create key'),
    } as unknown as ReturnType<typeof useCreateMyApiKey>);

    render(<MyApiKeySection />);

    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent('Failed to create key');
  });

  it('revoke mutation error is rendered inside role=alert (GLUX-014)', () => {
    vi.mocked(useRevokeMyApiKey).mockReturnValue({
      ...defaultRevokeMutation,
      error: new Error('Failed to revoke key'),
    } as unknown as ReturnType<typeof useRevokeMyApiKey>,
    );

    render(<MyApiKeySection />);

    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent('Failed to revoke key');
  });
});

// Per-key scopes. A read-only key is a different credential in
// practice, so the list has to say which one you are holding, and the mint
// form has to be able to ask for one.
describe('#875: API key scope', () => {
  beforeEach(() => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    vi.mocked(useCreateMyApiKey).mockReturnValue(
      defaultCreateMutation as unknown as ReturnType<typeof useCreateMyApiKey>,
    );

    vi.mocked(useRevokeMyApiKey).mockReturnValue(
      defaultRevokeMutation as unknown as ReturnType<typeof useRevokeMyApiKey>,
    );
  });

  it('offers a scope control on the create form', async () => {
    const user = userEvent.setup();
    render(<MyApiKeySection />);

    await user.click(screen.getByRole('button', { name: 'admin:apiKeys.createKey' }));

    // The react-i18next mock drops the namespace, so ApiKeyScopeSelect's
    // useTranslation('admin') + t('apiKeys.scope') renders the bare key.
    expect(screen.getByRole('combobox', { name: 'apiKeys.scope' })).toBeInTheDocument();
  });

  it('submits the selected scope with the name', async () => {
    const user = userEvent.setup();
    render(<MyApiKeySection />);

    await user.click(screen.getByRole('button', { name: 'admin:apiKeys.createKey' }));
    await user.type(screen.getByLabelText('admin:apiKeys.keyName'), 'CI pipeline');
    await user.click(screen.getByRole('button', { name: 'create' }));

    expect(defaultCreateMutation.mutateAsync).toHaveBeenCalledWith({
      name: 'CI pipeline',
      scope: 'full',
      expiresAt: null,
    });
  });

  it('submits the publish scope and says what it allows', async () => {
    const user = userEvent.setup();
    render(<MyApiKeySection />);

    await user.click(screen.getByRole('button', { name: 'admin:apiKeys.createKey' }));
    expect(screen.queryByText('apiKeys.scopePublishDescription')).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('admin:apiKeys.keyName'), 'QGIS laptop');
    await user.click(screen.getByRole('combobox', { name: 'apiKeys.scope' }));
    await user.click(await screen.findByRole('option', { name: 'apiKeys.scopePublish' }));

    expect(screen.getByRole('combobox', { name: 'apiKeys.scope' })).toHaveAccessibleDescription(
      'apiKeys.scopePublishDescription',
    );
    await user.click(screen.getByRole('button', { name: 'create' }));
    expect(defaultCreateMutation.mutateAsync).toHaveBeenCalledWith({
      name: 'QGIS laptop',
      scope: 'publish',
      expiresAt: null,
    });
  });

  it('badges a publish key in the list', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ scope: 'publish' })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);

    expect(screen.getByText('admin:apiKeys.scopePublish')).toBeInTheDocument();
  });

  it('badges a read_only key in the list', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ scope: 'read_only' })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);

    expect(screen.getByText('admin:apiKeys.scopeReadOnly')).toBeInTheDocument();
  });

  it('badges a dataset_write key in the list', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ scope: 'dataset_write', dataset_id: 'ds-1' })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);

    expect(screen.getByText('admin:apiKeys.scopeDatasetWrite')).toBeInTheDocument();
  });

  it('badges a dataset_append key in the list', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ scope: 'dataset_append', dataset_id: 'ds-1' })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);

    expect(screen.getByText('admin:apiKeys.scopeDatasetAppend')).toBeInTheDocument();
    expect(screen.queryByText('admin:apiKeys.scopeDatasetWrite')).not.toBeInTheDocument();
  });

  it('wraps the badges below a key name instead of squeezing it at phone width', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ name: 'Webhook smoke', scope: 'dataset_write', dataset_id: 'ds-1' })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);

    const name = screen.getByText('Webhook smoke');
    expect(name).toHaveClass('min-w-0', 'max-w-full', 'truncate');
    expect(name.parentElement).toHaveClass('flex-wrap');
  });

  it('does not badge a full key', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ scope: 'full' })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);

    expect(screen.queryByText('admin:apiKeys.scopeReadOnly')).not.toBeInTheDocument();
  });
});

// Radix Select needs these in jsdom.
beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

describe('API key expiry', () => {
  beforeEach(() => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);
    vi.mocked(useCreateMyApiKey).mockReturnValue(
      defaultCreateMutation as unknown as ReturnType<typeof useCreateMyApiKey>,
    );
    vi.mocked(useRevokeMyApiKey).mockReturnValue(
      defaultRevokeMutation as unknown as ReturnType<typeof useRevokeMyApiKey>,
    );
    defaultCreateMutation.mutateAsync.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('sends an expires_at 90 days out when the 90 day preset is chosen', async () => {
    const user = userEvent.setup();
    render(<MyApiKeySection />);
    // Fake only Date so userEvent's timers keep running.
    vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-01-10T12:00:00Z') });

    await user.click(screen.getByRole('button', { name: 'admin:apiKeys.createKey' }));
    await user.type(screen.getByLabelText('admin:apiKeys.keyName'), 'CI pipeline');
    await user.click(screen.getByRole('combobox', { name: 'apiKeys.expiry' }));
    await user.click(await screen.findByRole('option', { name: 'apiKeys.expiryOptions.90d' }));
    await user.click(screen.getByRole('button', { name: 'create' }));

    expect(defaultCreateMutation.mutateAsync).toHaveBeenCalledWith({
      name: 'CI pipeline',
      scope: 'full',
      expiresAt: '2026-04-10T12:00:00.000Z',
    });
  });

  it('shows when a key expires', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ expires_at: '2999-01-01T00:00:00Z' })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);

    expect(screen.getByText(/admin:apiKeys\.expiresOn/)).toBeInTheDocument();
    expect(screen.getByText('admin:apiKeys.active')).toBeInTheDocument();
  });

  it('marks a key past its expiry as expired instead of active', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ expires_at: '2020-01-01T00:00:00Z' })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);

    expect(screen.getByText('admin:apiKeys.expired')).toBeInTheDocument();
    expect(screen.queryByText('admin:apiKeys.active')).not.toBeInTheDocument();
  });

  it('gives an expired key the inactive status dot', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ expires_at: '2020-01-01T00:00:00Z' })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    const { container } = render(<MyApiKeySection />);

    expect(container.querySelector('span.rounded-full.bg-destructive')).toBeInTheDocument();
    expect(container.querySelector('span.rounded-full.bg-success')).not.toBeInTheDocument();
  });

  it('keeps a revoked key revoked but still dates its past expiry as expired', () => {
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ is_active: false, expires_at: '2020-01-01T00:00:00Z' })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);

    expect(screen.getByText('admin:apiKeys.revoked')).toBeInTheDocument();
    expect(screen.queryByText('admin:apiKeys.expired')).not.toBeInTheDocument();
    expect(screen.getByText(/admin:apiKeys\.expiredOn/)).toBeInTheDocument();
    expect(screen.queryByText(/admin:apiKeys\.expiresOn/)).not.toBeInTheDocument();
  });

  it('flips an open list to expired when a key passes its expiry', () => {
    vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] });
    vi.setSystemTime(new Date('2026-01-10T12:00:00Z'));
    vi.mocked(useMyApiKeys).mockReturnValue({
      data: [makeKey({ expires_at: '2026-01-10T12:01:00Z' })],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyApiKeys>);

    render(<MyApiKeySection />);
    expect(screen.getByText('admin:apiKeys.active')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(61_000);
    });

    expect(screen.getByText('admin:apiKeys.expired')).toBeInTheDocument();
    expect(screen.queryByText('admin:apiKeys.active')).not.toBeInTheDocument();
  });
});
