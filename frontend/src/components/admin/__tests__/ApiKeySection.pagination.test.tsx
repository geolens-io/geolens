// fix(#1778): listApiKeys fetched `total` and then discarded it, capping the
// visible list at the backend default limit=50 with no indication more keys
// existed — a key an admin needed to revoke could be permanently invisible.
import { render, screen } from '@/test/test-utils';
import { ApiKeySection } from '../ApiKeySection';
import type { ApiKeyResponse } from '@/types/api';

const { mockUseApiKeys } = vi.hoisted(() => ({ mockUseApiKeys: vi.fn() }));

vi.mock('@/hooks/use-admin', () => ({
  useApiKeys: (...args: unknown[]) => mockUseApiKeys(...args),
  useCreateApiKey: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
  useRevokeApiKey: () => ({ mutateAsync: vi.fn(), error: null, isPending: false }),
}));

function makeKey(name: string): ApiKeyResponse {
  return {
    id: name,
    user_id: 'u1',
    name,
    fingerprint: null,
    is_active: true,
    expires_at: null,
    scope: 'full',
    created_at: '2026-08-01T00:00:00Z',
    last_used_at: null,
  };
}

describe('ApiKeySection pagination notice', () => {
  it('#1778 — shows a "showing N of total" notice when more keys exist than are listed', () => {
    mockUseApiKeys.mockReturnValue({
      data: { items: [makeKey('key-1'), makeKey('key-2')], total: 57 },
      isLoading: false,
    });
    render(<ApiKeySection userId="u1" />);

    expect(screen.getByText(/57/)).toBeInTheDocument();
  });

  it('shows no notice when every key is already listed', () => {
    mockUseApiKeys.mockReturnValue({
      data: { items: [makeKey('key-1')], total: 1 },
      isLoading: false,
    });
    render(<ApiKeySection userId="u1" />);

    expect(screen.queryByText(/showingOf|of 1/i)).not.toBeInTheDocument();
  });
});
