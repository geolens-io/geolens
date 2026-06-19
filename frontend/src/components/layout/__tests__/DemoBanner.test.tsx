/**
 * DEMO-03 (Phase 1226): DemoBanner rendering matrix.
 *
 * Scenarios:
 *  A) demo_mode=true + token present   → banner renders
 *  B) demo_mode=false + token present  → no banner
 *  C) demo_mode=true + no token        → no banner (anonymous visitors unaffected)
 */
import { act } from 'react';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';
import { DemoBanner } from '../DemoBanner';
import type { AuthConfigResponse } from '@/types/api';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock('@/api/auth', () => ({
  getAuthConfig: vi.fn(),
}));

import { getAuthConfig } from '@/api/auth';
const mockGetAuthConfig = vi.mocked(getAuthConfig);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createTestClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
}

function renderBanner(
  config: Partial<AuthConfigResponse> = {},
  options: { token?: string | null } = {},
) {
  const queryClient = createTestClient();

  const fullConfig: AuthConfigResponse = {
    registration_enabled: false,
    landing_first: false,
    demo_mode: false,
    auth_methods: [],
    ...config,
  };
  queryClient.setQueryData(['auth', 'config'], fullConfig);

  act(() => {
    useAuthStore.setState({
      token: options.token ?? null,
      user: null,
      refreshToken: null,
      expiresAt: null,
    });
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <DemoBanner />
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DemoBanner', () => {
  beforeEach(() => {
    mockGetAuthConfig.mockResolvedValue({
      registration_enabled: false,
      landing_first: false,
      demo_mode: false,
      auth_methods: [],
    });
    act(() => {
      useAuthStore.setState({ token: null, user: null, refreshToken: null, expiresAt: null });
    });
  });

  it('A) demo_mode=true + token → banner renders', () => {
    renderBanner({ demo_mode: true }, { token: 'bearer-token-xyz' });

    const banner = screen.getByRole('status');
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).not.toBe('');
  });

  it('B) demo_mode=false + token → no banner', () => {
    renderBanner({ demo_mode: false }, { token: 'bearer-token-xyz' });

    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('C) demo_mode=true + no token → no banner (anonymous visitors unaffected)', () => {
    renderBanner({ demo_mode: true }, { token: null });

    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});
