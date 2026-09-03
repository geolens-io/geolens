// fix(#1778): listApiKeys fetched `total` and then discarded it, capping the
// visible list at the backend default limit=50 with no indication more keys
// existed — a key an admin needed to revoke could be permanently invisible.
// fix(#1805 review round 3 P2): the flat limit=200 fetch that replaced it
// was itself the backend's hard cap (`le=200`) — a user with 201+ keys
// still had no way to reach the rest. useApiKeys now returns
// {items, total, isLoading, hasMore} for a given pageCount, and the
// component's "Load more" control grows pageCount until every key loads.
import { fireEvent, render, screen } from '@/test/test-utils';
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
      items: [makeKey('key-1'), makeKey('key-2')],
      total: 57,
      isLoading: false,
      hasMore: true,
    });
    render(<ApiKeySection userId="u1" />);

    expect(screen.getByText(/57/)).toBeInTheDocument();
  });

  it('shows no notice when every key is already listed', () => {
    mockUseApiKeys.mockReturnValue({
      items: [makeKey('key-1')],
      total: 1,
      isLoading: false,
      hasMore: false,
    });
    render(<ApiKeySection userId="u1" />);

    expect(screen.queryByText(/showingOf|of 1/i)).not.toBeInTheDocument();
  });
});

describe('ApiKeySection "Load more" pagination (#1805 review round 3 P2)', () => {
  const PAGE_SIZE = 50;
  const TOTAL = 250;
  const allKeys = Array.from({ length: TOTAL }, (_, i) => makeKey(`key-${i + 1}`));

  beforeEach(() => {
    mockUseApiKeys.mockImplementation((_userId: string, pageCount: number) => {
      const items = allKeys.slice(0, pageCount * PAGE_SIZE);
      return { items, total: TOTAL, isLoading: false, hasMore: items.length < TOTAL };
    });
  });

  it('a user with 250 keys can reach key 201 through the "Load more" control', () => {
    render(<ApiKeySection userId="u1" />);

    // Only the first page is loaded initially.
    expect(screen.getByText('key-1')).toBeInTheDocument();
    expect(screen.queryByText('key-201')).not.toBeInTheDocument();

    const loadMore = screen.getByRole('button', { name: /load more/i });
    // 1 page already loaded; 4 more clicks reach pageCount=5 (250 keys, past key-201).
    fireEvent.click(loadMore);
    fireEvent.click(loadMore);
    fireEvent.click(loadMore);
    fireEvent.click(loadMore);

    expect(screen.getByText('key-201')).toBeInTheDocument();
  });

  it('hides the "Load more" control once every key is loaded', () => {
    render(<ApiKeySection userId="u1" />);

    const loadMore = screen.getByRole('button', { name: /load more/i });
    fireEvent.click(loadMore);
    fireEvent.click(loadMore);
    fireEvent.click(loadMore);
    fireEvent.click(loadMore);

    expect(screen.getByText('key-250')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument();
  });
});
