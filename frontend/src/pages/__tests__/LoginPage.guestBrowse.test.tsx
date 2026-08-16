/**
 * fix(#1527): the guest-browse escape hatch WRITES `gl-guest-browse` to
 * sessionStorage before navigating to "/". Bare, that write throws in a
 * storage-denied context (sandboxed frame with an opaque origin, private-mode
 * Safari, third-party storage blocked) and takes the click handler with it —
 * the one button on the login page that does not require an account.
 *
 * Losing the marker is acceptable: the visitor gets bounced back to /login on
 * the next visit to "/". Losing the navigation is not.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useAuthStore } from '@/stores/auth-store';
import { queryKeys } from '@/lib/query-keys';
import { denySessionStorage } from '@/test/deny-storage';
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

vi.mock('@/api/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/auth')>();
  return {
    ...actual,
    getAuthConfig: vi.fn(),
    getOAuthProviders: vi.fn(),
  };
});

import { getAuthConfig, getOAuthProviders } from '@/api/auth';
import { LoginPage } from '../LoginPage';

function renderLoginPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  queryClient.setQueryData(queryKeys.authConfig.config, {
    registration_enabled: false,
    landing_first: true,
    password_login_enabled: true,
    auth_methods: [],
  } as unknown as AuthConfigResponse);
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <MemoryRouter initialEntries={['/login']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<div data-testid="catalog">CATALOG</div>} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe('LoginPage — guest-browse escape hatch under denied storage (#1527)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getAuthConfig).mockResolvedValue({
      registration_enabled: false,
      landing_first: true,
      password_login_enabled: true,
      auth_methods: [],
    } as unknown as AuthConfigResponse);
    vi.mocked(getOAuthProviders).mockResolvedValue([]);
    useAuthStore.setState({ token: null, user: null });
    sessionStorage.clear();
  });

  it('records the guest-browse marker and navigates', async () => {
    renderLoginPage();

    const [browse] = await screen.findAllByRole('button', { name: /browse the catalog/i });
    await userEvent.click(browse);

    await waitFor(() => expect(screen.getByTestId('catalog')).toBeInTheDocument());
    expect(sessionStorage.getItem('gl-guest-browse')).toBe('true');
  });

  it('still navigates when sessionStorage access throws', async () => {
    renderLoginPage();

    const [browse] = await screen.findAllByRole('button', { name: /browse the catalog/i });

    const restore = denySessionStorage();
    try {
      await userEvent.click(browse);

      await waitFor(() => expect(screen.getByTestId('catalog')).toBeInTheDocument());
    } finally {
      restore();
    }
  });
});
