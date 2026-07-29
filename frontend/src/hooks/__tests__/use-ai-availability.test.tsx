import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { vi } from 'vitest';
import type { ReactNode } from 'react';

vi.mock('@/api/admin', () => ({
  getAIStatus: vi.fn(),
}));

// builder-audit #338 P1-11: non-admin editors read the public-safe availability endpoint.
vi.mock('@/api/maps', () => ({
  getAIAvailability: vi.fn(),
}));

// fix(#815): the hook branches on useAIStatusReader (capabilities + edition),
// not the isAdmin flag — mock both sides with per-test mutable state.
const mocks = vi.hoisted(() => ({
  capabilities: new Set<string>(),
  isMultiTenant: false,
  editionLoading: false,
  permissionsLoading: false,
}));
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({
    // Mirrors the real hook: permissions are null while loading, so can()
    // answers false for everything until the query resolves.
    can: (capability: string) =>
      !mocks.permissionsLoading && mocks.capabilities.has(capability),
    isLoading: mocks.permissionsLoading,
  }),
}));
vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => ({
    edition: 'community',
    features: [],
    isEnterprise: false,
    isMultiTenant: mocks.isMultiTenant,
    isLoading: mocks.editionLoading,
  }),
}));

import { getAIStatus } from '@/api/admin';
import { getAIAvailability } from '@/api/maps';
import { useAIStatus } from '@/hooks/use-admin';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { useAuthStore } from '@/stores/auth-store';

const mockGetAIStatus = vi.mocked(getAIStatus);
const mockGetAIAvailability = vi.mocked(getAIAvailability);

function makeWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

const adminUser = {
  id: 'u1',
  username: 'admin',
  email: 'admin@x',
  roles: ['admin'],
  is_active: true,
  status: 'active',
  last_login_at: null,
  created_at: '',
};

describe('useAIStatus / useAIAvailability — caching (SP-08)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.capabilities = new Set(['use_ai_chat', 'manage_users']);
    mocks.isMultiTenant = false;
    mocks.editionLoading = false;
    mocks.permissionsLoading = false;
    useAuthStore.setState({
      token: 'test-token',
      refreshToken: null,
      expiresAt: null,
      user: adminUser,
    });
    mockGetAIStatus.mockResolvedValue({
      enabled: true,
      configured: true,
      provider: 'openai',
      model: 'gpt-4',
    } as never);
  });

  it('shares a single in-flight query across multiple consumers (queryKey-deduped)', async () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 5 * 60_000 } },
    });
    const wrapper = makeWrapper(qc);

    // Mount three independent consumers of the underlying hook
    const a = renderHook(() => useAIStatus({ enabled: true }), { wrapper });
    const b = renderHook(() => useAIAvailability(), { wrapper });
    const c = renderHook(() => useAIAvailability(), { wrapper });

    await waitFor(() => {
      expect(a.result.current.data).toBeDefined();
      expect(b.result.current.data).toBeDefined();
      expect(c.result.current.data).toBeDefined();
    });

    // Despite 3 consumers, only one network call
    expect(mockGetAIStatus).toHaveBeenCalledTimes(1);
  });

  it('does not refetch within 60s staleTime when a new consumer mounts', async () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 5 * 60_000 } },
    });
    const wrapper = makeWrapper(qc);

    const first = renderHook(() => useAIAvailability(), { wrapper });
    await waitFor(() => expect(first.result.current.data).toBeDefined());
    expect(mockGetAIStatus).toHaveBeenCalledTimes(1);

    // Mount a second consumer immediately — within staleTime → no refetch
    const second = renderHook(() => useAIAvailability(), { wrapper });
    await waitFor(() => expect(second.result.current.data).toBeDefined());

    expect(mockGetAIStatus).toHaveBeenCalledTimes(1);
  });

  it('does NOT poll on a refetchInterval (no idle network storm)', async () => {
    vi.useFakeTimers();
    try {
      const qc = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 5 * 60_000 } },
      });
      const wrapper = makeWrapper(qc);

      const view = renderHook(() => useAIAvailability(), { wrapper });

      // Advance well past the old 60s refetchInterval to ensure no auto-poll
      await vi.advanceTimersByTimeAsync(180_000);

      // The first mount triggers exactly one call; no further polling
      expect(mockGetAIStatus).toHaveBeenCalledTimes(1);
      view.unmount();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('useAIAvailability — CONSOLE-01 gating', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.capabilities = new Set(['use_ai_chat', 'manage_users']);
    mocks.isMultiTenant = false;
    mocks.editionLoading = false;
    mocks.permissionsLoading = false;
    mockGetAIStatus.mockResolvedValue({
      enabled: true,
      configured: true,
      provider: 'openai',
      model: 'gpt-4',
    } as never);
  });

  it('anonymous user (no token): does NOT fire getAIStatus — query stays idle', async () => {
    useAuthStore.setState({
      token: null,
      refreshToken: null,
      expiresAt: null,
      user: null,
    });
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = makeWrapper(qc);

    const { result } = renderHook(() => useAIAvailability(), { wrapper });

    // fetchStatus 'idle' means the query is disabled (never fetched)
    expect(result.current.fetchStatus).toBe('idle');
    expect(mockGetAIStatus).not.toHaveBeenCalled();
  });

  it('authed viewer WITHOUT use_ai_chat: fires NEITHER endpoint — query stays idle, reason=permission', async () => {
    // A genuine viewer lacks use_ai_chat → no admin status probe AND no public
    // availability probe (P1-11: no 403 console noise for viewers).
    mocks.capabilities = new Set();
    useAuthStore.setState({
      token: 'viewer-token',
      refreshToken: null,
      expiresAt: null,
      user: {
        id: 'u2',
        username: 'viewer',
        email: 'viewer@x',
        roles: ['viewer'],
        is_active: true,
        status: 'active',
        last_login_at: null,
        created_at: '',
      },
    });
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = makeWrapper(qc);

    const { result } = renderHook(() => useAIAvailability(), { wrapper });

    expect(result.current.fetchStatus).toBe('idle');
    expect(mockGetAIStatus).not.toHaveBeenCalled();
    expect(mockGetAIAvailability).not.toHaveBeenCalled();
    expect(result.current.isAIAvailable).toBe(false);
    expect(result.current.reason).toBe('permission');
  });

  it('P1-11: non-admin editor WITH use_ai_chat fires the public availability endpoint, NOT admin status', async () => {
    mocks.capabilities = new Set(['use_ai_chat']);
    mockGetAIAvailability.mockResolvedValue({ available: true });
    useAuthStore.setState({
      token: 'editor-token',
      refreshToken: null,
      expiresAt: null,
      user: {
        id: 'u4',
        username: 'editor',
        email: 'editor@x',
        roles: ['editor'],
        is_active: true,
        status: 'active',
        last_login_at: null,
        created_at: '',
      },
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = makeWrapper(qc);

    const { result } = renderHook(() => useAIAvailability(), { wrapper });

    await waitFor(() => expect(result.current.isAIAvailable).toBe(true));
    expect(mockGetAIAvailability).toHaveBeenCalledTimes(1);
    expect(mockGetAIStatus).not.toHaveBeenCalled();
    expect(result.current.reason).toBeNull();
  });

  it('P1-11: non-admin editor sees a safe disabled state (reason=no_key) when AI is not configured', async () => {
    mocks.capabilities = new Set(['use_ai_chat']);
    mockGetAIAvailability.mockResolvedValue({ available: false });
    useAuthStore.setState({
      token: 'editor-token',
      refreshToken: null,
      expiresAt: null,
      user: {
        id: 'u4',
        username: 'editor',
        email: 'editor@x',
        roles: ['editor'],
        is_active: true,
        status: 'active',
        last_login_at: null,
        created_at: '',
      },
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = makeWrapper(qc);

    const { result } = renderHook(() => useAIAvailability(), { wrapper });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.isAIAvailable).toBe(false);
    expect(result.current.reason).toBe('no_key');
    expect(mockGetAIStatus).not.toHaveBeenCalled();
  });

  it('authed admin: DOES fire getAIStatus — query is enabled', async () => {
    useAuthStore.setState({
      token: 'admin-token',
      refreshToken: null,
      expiresAt: null,
      user: {
        id: 'u3',
        username: 'admin',
        email: 'admin@x',
        roles: ['admin'],
        is_active: true,
        status: 'active',
        last_login_at: null,
        created_at: '',
      },
    });
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = makeWrapper(qc);

    const { result } = renderHook(() => useAIAvailability(), { wrapper });

    await waitFor(() => {
      expect(result.current.data).toBeDefined();
    });

    expect(mockGetAIStatus).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// Phase 1135 AI-02: reason field taxonomy
// ---------------------------------------------------------------------------

describe('useAIAvailability — reason field (Phase 1135 AI-02)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: a status reader who can also use chat; individual tests override.
    mocks.capabilities = new Set(['use_ai_chat', 'manage_users']);
    mocks.isMultiTenant = false;
    mocks.editionLoading = false;
    mocks.permissionsLoading = false;
    // Default auth state: admin token.
    useAuthStore.setState({
      token: 'admin-token',
      refreshToken: null,
      expiresAt: null,
      user: adminUser,
    });
  });

  // Test A
  it('reason is "env_disabled" when aiStatus.data.enabled === false', async () => {
    mockGetAIStatus.mockResolvedValue({
      enabled: false,
      configured: true,
      provider: null,
      model: null,
      semantic_search_enabled: false,
      has_embeddings: false,
    } as never);

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = makeWrapper(qc);
    const { result } = renderHook(() => useAIAvailability(), { wrapper });

    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(result.current.reason).toBe('env_disabled');
    expect(result.current.isAIAvailable).toBe(false);
  });

  // Test B
  it('reason is "no_key" when enabled but not configured', async () => {
    mockGetAIStatus.mockResolvedValue({
      enabled: true,
      configured: false,
      provider: null,
      model: null,
      semantic_search_enabled: false,
      has_embeddings: false,
    } as never);

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = makeWrapper(qc);
    const { result } = renderHook(() => useAIAvailability(), { wrapper });

    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(result.current.reason).toBe('no_key');
    expect(result.current.isAIAvailable).toBe(false);
  });

  // Test C
  it('reason is "permission" when enabled + configured but caller lacks use_ai_chat', async () => {
    // A status reader without use_ai_chat: the status query still resolves,
    // but chat stays permission-denied.
    mocks.capabilities = new Set(['manage_users']);
    mockGetAIStatus.mockResolvedValue({
      enabled: true,
      configured: true,
      provider: 'openai',
      model: 'gpt-4',
      semantic_search_enabled: false,
      has_embeddings: false,
    } as never);

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = makeWrapper(qc);
    const { result } = renderHook(() => useAIAvailability(), { wrapper });

    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(result.current.reason).toBe('permission');
    expect(result.current.isAIAvailable).toBe(false);
  });

  // Test D
  it('reason is null when isAIAvailable === true (happy path)', async () => {
    mockGetAIStatus.mockResolvedValue({
      enabled: true,
      configured: true,
      provider: 'openai',
      model: 'gpt-4',
      semantic_search_enabled: false,
      has_embeddings: false,
    } as never);

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = makeWrapper(qc);
    const { result } = renderHook(() => useAIAvailability(), { wrapper });

    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(result.current.reason).toBeNull();
    expect(result.current.isAIAvailable).toBe(true);
  });

  // Test E
  it('reason is null while aiStatus is loading (spinner state, not error)', () => {
    // Never-resolving promise simulates loading state
    mockGetAIStatus.mockImplementation(() => new Promise(() => {}));

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = makeWrapper(qc);
    const { result } = renderHook(() => useAIAvailability(), { wrapper });

    // Query is in loading state (pending, not yet resolved)
    expect(result.current.isLoading).toBe(true);
    expect(result.current.reason).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// fix(#815): the status branch follows useAIStatusReader, not the isAdmin flag
// ---------------------------------------------------------------------------

describe('useAIAvailability — mode-aware status gate (fix #815)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.isMultiTenant = false;
    mocks.editionLoading = false;
    mocks.permissionsLoading = false;
    mockGetAIStatus.mockResolvedValue({
      enabled: true,
      configured: true,
      provider: 'openai',
      model: 'gpt-4',
    } as never);
    mockGetAIAvailability.mockResolvedValue({ available: true });
  });

  it('multi-tenant: admin-flagged user WITHOUT manage_tenants falls back to the public endpoint (no 403 probe)', async () => {
    mocks.isMultiTenant = true;
    // manage_users is not enough in multi-tenant mode — the backend requires
    // manage_tenants there, so probing admin status would just 403.
    mocks.capabilities = new Set(['use_ai_chat', 'manage_users']);
    useAuthStore.setState({
      token: 'admin-token',
      refreshToken: null,
      expiresAt: null,
      user: adminUser,
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const { result } = renderHook(() => useAIAvailability(), {
      wrapper: makeWrapper(qc),
    });

    await waitFor(() => expect(result.current.isAIAvailable).toBe(true));
    expect(mockGetAIStatus).not.toHaveBeenCalled();
    expect(mockGetAIAvailability).toHaveBeenCalledTimes(1);
  });

  it('multi-tenant: manage_tenants holder reads detailed admin status', async () => {
    mocks.isMultiTenant = true;
    mocks.capabilities = new Set(['use_ai_chat', 'manage_tenants']);
    useAuthStore.setState({
      token: 'admin-token',
      refreshToken: null,
      expiresAt: null,
      user: adminUser,
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const { result } = renderHook(() => useAIAvailability(), {
      wrapper: makeWrapper(qc),
    });

    await waitFor(() => expect(result.current.isAIAvailable).toBe(true));
    expect(mockGetAIStatus).toHaveBeenCalledTimes(1);
    expect(mockGetAIAvailability).not.toHaveBeenCalled();
  });

  it('holds BOTH probes while the edition query is loading (no wrong-endpoint 403), surfacing isLoading', () => {
    // Until the edition resolves, tenancy mode reads as single-tenant, so a
    // manage_users holder in a multi-tenant deployment would probe the admin
    // endpoint and 403. Neither endpoint may fire before the mode is known.
    mocks.editionLoading = true;
    mocks.capabilities = new Set(['use_ai_chat', 'manage_users']);
    useAuthStore.setState({
      token: 'admin-token',
      refreshToken: null,
      expiresAt: null,
      user: adminUser,
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const { result } = renderHook(() => useAIAvailability(), {
      wrapper: makeWrapper(qc),
    });

    expect(mockGetAIStatus).not.toHaveBeenCalled();
    expect(mockGetAIAvailability).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(true);
    expect(result.current.reason).toBeNull();
  });

  // fix(#818): can() answers false while the permissions query is loading, which
  // used to settle reason='permission' with isLoading=false — a cold mount
  // flashed the no-permission disabled state at permitted editors.
  it('cold permissions load: surfaces isLoading with reason=null instead of a premature permission denial', () => {
    mocks.permissionsLoading = true;
    mocks.capabilities = new Set(['use_ai_chat']);
    useAuthStore.setState({
      token: 'editor-token',
      refreshToken: null,
      expiresAt: null,
      user: {
        id: 'u4',
        username: 'editor',
        email: 'editor@x',
        roles: ['editor'],
        is_active: true,
        status: 'active',
        last_login_at: null,
        created_at: '',
      },
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const { result } = renderHook(() => useAIAvailability(), {
      wrapper: makeWrapper(qc),
    });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.reason).toBeNull();
    expect(result.current.isAIAvailable).toBe(false);
    // Neither probe fires before permissions resolve (can() gates both).
    expect(mockGetAIStatus).not.toHaveBeenCalled();
    expect(mockGetAIAvailability).not.toHaveBeenCalled();
  });

  it('single-tenant: a non-admin manage_users holder reads detailed admin status', async () => {
    mocks.capabilities = new Set(['use_ai_chat', 'manage_users']);
    useAuthStore.setState({
      token: 'editor-token',
      refreshToken: null,
      expiresAt: null,
      user: {
        id: 'u5',
        username: 'ops',
        email: 'ops@x',
        roles: ['editor'],
        is_active: true,
        status: 'active',
        last_login_at: null,
        created_at: '',
      },
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const { result } = renderHook(() => useAIAvailability(), {
      wrapper: makeWrapper(qc),
    });

    await waitFor(() => expect(result.current.isAIAvailable).toBe(true));
    expect(mockGetAIStatus).toHaveBeenCalledTimes(1);
    expect(mockGetAIAvailability).not.toHaveBeenCalled();
  });
});
