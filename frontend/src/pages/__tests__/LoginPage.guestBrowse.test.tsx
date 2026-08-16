/**
 * fix(#1527): the guest-browse escape hatch, end to end, under denied storage.
 *
 * The claim under test is "an anonymous visitor can reach the catalog", NOT
 * "a navigation happened". Those come apart: the button writes
 * `gl-guest-browse` to sessionStorage and navigates to "/", where the REAL
 * `LandingFirstGuard` reads that marker back and bounces anyone without it to
 * /login. A write that silently no-ops therefore leaves the button dead, and
 * the visitor cannot tell that from a click that did nothing.
 *
 * So this file routes "/" through the production guard. An earlier revision
 * substituted a dummy catalog route, which asserted the navigation and
 * masked the bounce (#1535 codex P1). `SearchPage` is still stubbed, which is
 * a sound substitution: it is the destination's content, not the component
 * whose behaviour is the claim.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useAuthStore } from '@/stores/auth-store';
import { queryKeys } from '@/lib/query-keys';
import { denySessionStorage } from '@/test/deny-storage';
import { _resetSessionStorageFallback } from '@/lib/storage';
import type { AuthConfigResponse } from '@/types/api';

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({
    login: vi.fn(),
    logout: vi.fn(),
    token: null,
    user: null,
    isAdmin: false,
    isEditor: false,
  }),
}));

// The catalog's CONTENT is stubbed; the guard in front of it is real.
vi.mock('@/pages/SearchPage', () => ({
  SearchPage: () => <div data-testid="search-page">SearchPage</div>,
}));

vi.mock('@/api/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/auth')>();
  return {
    ...actual,
    getAuthConfig: vi.fn(),
    getOAuthProviders: vi.fn(),
  };
});

import { getAuthConfig, getOAuthProviders } from '@/api/auth';
import { LandingFirstGuard } from '@/components/auth/LandingFirstGuard';
import { LoginPage } from '../LoginPage';

const LANDING_FIRST_CONFIG = {
  registration_enabled: false,
  landing_first: true,
  password_login_enabled: true,
  auth_methods: [],
} as unknown as AuthConfigResponse;

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  queryClient.setQueryData(queryKeys.authConfig.config, LANDING_FIRST_CONFIG);
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <MemoryRouter initialEntries={['/login']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            {/* The production guard, not a stand-in. */}
            <Route path="/" element={<LandingFirstGuard />} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

async function clickBrowseCatalog() {
  const [browse] = await screen.findAllByRole('button', { name: /browse the catalog/i });
  await userEvent.click(browse);
}

describe('LoginPage guest-browse reaches the catalog (#1527)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getAuthConfig).mockResolvedValue(LANDING_FIRST_CONFIG);
    vi.mocked(getOAuthProviders).mockResolvedValue([]);
    useAuthStore.setState({ token: null, user: null });
    sessionStorage.clear();
    // The mirror is module state; sessionStorage.clear() does not reach it.
    _resetSessionStorageFallback();
  });

  it('reaches the catalog and records the marker when storage works', async () => {
    renderApp();
    await clickBrowseCatalog();

    await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
    expect(sessionStorage.getItem('gl-guest-browse')).toBe('true');
  });

  /**
   * The bug #1535 shipped with: the click no longer threw, but the marker was
   * dropped, so the guard bounced the visitor straight back to /login. The
   * button was still dead in the one environment the fix exists for.
   */
  it('reaches the catalog when sessionStorage access throws', async () => {
    renderApp();

    const restore = denySessionStorage();
    try {
      await clickBrowseCatalog();

      await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
    } finally {
      restore();
    }
  });
});
