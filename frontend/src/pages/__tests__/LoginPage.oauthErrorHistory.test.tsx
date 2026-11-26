import { render, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import { toast } from 'sonner';

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

vi.mock('@/api/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/auth')>();
  return {
    ...actual,
    getAuthConfig: () =>
      Promise.resolve({ registration_enabled: false, password_login_enabled: true }),
    getOAuthProviders: () => Promise.resolve([]),
  };
});

import { LoginPage } from '../LoginPage';

describe('LoginPage after a failed SSO redirect', () => {
  it('drops the consumed error from the entry but keeps the router index', async () => {
    window.history.replaceState(
      { idx: 2, key: 'k', usr: { oauthError: 'access_denied' } },
      '',
      '/login',
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <MemoryRouter
            initialEntries={[{ pathname: '/login', state: { oauthError: 'access_denied' } }]}
          >
            <Routes>
              <Route path="/login" element={<LoginPage />} />
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(window.history.state).toEqual({ idx: 2, key: 'k', usr: null });
  });
});
