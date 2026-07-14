/**
 * GLUX-002 / GLUX-014 (Phase 1248): regression gate for the MyApiKeySection
 * control semantics.
 *
 * Asserts:
 * - Create-form name input has an accessible name via FieldLabel (GLUX-002).
 * - Active / revoked status is rendered as visible text, not color+title only (GLUX-014).
 * - The icon-only revoke button has an accessible name (GLUX-002).
 * - Create and revoke mutation errors are announced via role=alert (GLUX-014).
 */
import userEvent from '@testing-library/user-event';
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
