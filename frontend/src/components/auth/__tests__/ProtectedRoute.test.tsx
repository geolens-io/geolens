import { act, render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router';
import { abortInflightRefresh, ApiError } from '@/api/client';
import { refreshAccessToken } from '@/api/auth';
import { restoreSession, useSessionRestore } from '@/lib/session-sync';
import { useAuthStore } from '@/stores/auth-store';
import { denySessionStorage } from '@/test/deny-storage';
import { ProtectedRoute } from '../ProtectedRoute';
import type { UserResponse } from '@/types/api';

vi.mock('@/api/auth', () => ({
  refreshAccessToken: vi.fn(),
  revokeCurrentSession: vi.fn(() => Promise.resolve()),
}));

function mockUser(roles: string[] = ['viewer']): UserResponse {
  return {
    id: '1',
    username: 'testuser',
    email: 'test@example.com',
    is_active: true,
    status: 'active',
    last_login_at: null,
    can_reset_password: true,
    created_at: '2025-01-01T00:00:00Z',
    roles,
  };
}

/** Helper that renders the login route and displays location.state.from */
function LoginPageWithState() {
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from;
  return <div>Login Page{from && <span data-testid="from">{from}</span>}</div>;
}

function renderWithRoutes(initialRoute = '/') {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <Routes>
        <Route element={<ProtectedRoute />}>
          <Route index element={<div>Protected Content</div>} />
          <Route path="datasets/:id" element={<div>Dataset Detail</div>} />
          <Route path="admin/settings" element={<div>Admin Settings</div>} />
        </Route>
        <Route path="/login" element={<LoginPageWithState />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ProtectedRoute', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, user: null });
    sessionStorage.clear();
  });

  it('redirects to /login when not authenticated', () => {
    renderWithRoutes('/');

    expect(screen.getByText('Login Page')).toBeInTheDocument();
  });

  it('renders child content when authenticated', () => {
    useAuthStore.setState({ token: 'abc', user: mockUser() });
    renderWithRoutes('/');

    expect(screen.getByText('Protected Content')).toBeInTheDocument();
  });

  it('passes current path as state.from when redirecting to /login', () => {
    renderWithRoutes('/datasets/abc');

    expect(screen.getByText('Login Page')).toBeInTheDocument();
    expect(screen.getByTestId('from')).toHaveTextContent('/datasets/abc');
  });

  it('passes path with query string as state.from', () => {
    renderWithRoutes('/admin/settings?tab=auth');

    expect(screen.getByText('Login Page')).toBeInTheDocument();
    expect(screen.getByTestId('from')).toHaveTextContent('/admin/settings?tab=auth');
  });

  it('saves redirect target to sessionStorage', () => {
    renderWithRoutes('/datasets/abc');

    expect(sessionStorage.getItem('geolens-login-redirect')).toBe('/datasets/abc');
  });

  /**
   * The redirect target is written during render, so a storage-denied
   * context turns "bounce an anonymous visitor to /login" into a thrown render.
   * Every protected route in the app is behind this component, so the blast
   * radius is the whole authenticated surface, not one lost preference.
   */
  it('still redirects to /login when sessionStorage access throws', () => {
    const restore = denySessionStorage();
    try {
      renderWithRoutes('/datasets/abc');

      expect(screen.getByText('Login Page')).toBeInTheDocument();
      expect(screen.getByTestId('from')).toHaveTextContent('/datasets/abc');
    } finally {
      restore();
    }
  });

  describe('while a reload restores its session', () => {
    beforeEach(() => {
      vi.mocked(refreshAccessToken).mockReset();
      useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: mockUser(), sessionId: 'session-1' });
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
      abortInflightRefresh();
      useSessionRestore.setState({ failures: 0, restoring: false });
      useAuthStore.setState({ token: null, user: null, sessionId: null });
    });

    it('keeps the route through a rate-limited refresh instead of sending the user to /login', async () => {
      const limited = Object.assign(new ApiError('rate limited', 429), { retryAfterMs: 3_000 });
      vi.mocked(refreshAccessToken).mockRejectedValueOnce(limited).mockResolvedValueOnce({
        access_token: 'recovered', refresh_token: null, token_type: 'bearer', expires_in: 900,
      });

      const pending = restoreSession();
      renderWithRoutes('/admin/settings');
      await act(() => vi.advanceTimersByTimeAsync(0));

      expect(screen.getByRole('status')).toBeInTheDocument();
      expect(screen.queryByText('Login Page')).not.toBeInTheDocument();

      await act(() => vi.advanceTimersByTimeAsync(3_000));
      await act(() => pending);

      expect(screen.getByText('Admin Settings')).toBeInTheDocument();
      expect(useAuthStore.getState()).toMatchObject({ token: 'recovered', sessionId: 'session-1' });
    });

    it('signs in again from /login, with the session kept, once the rate-limit retries run out', async () => {
      vi.mocked(refreshAccessToken).mockRejectedValue(new ApiError('rate limited', 429));

      const pending = restoreSession();
      renderWithRoutes('/admin/settings');
      await act(() => vi.advanceTimersByTimeAsync(4_000));
      await act(() => pending);

      expect(screen.getByText('Login Page')).toBeInTheDocument();
      expect(screen.getByTestId('from')).toHaveTextContent('/admin/settings');
      expect(useAuthStore.getState()).toMatchObject({ token: null, sessionId: 'session-1' });
    });

    it('sends the user to /login when the refresh is rejected', async () => {
      vi.mocked(refreshAccessToken).mockRejectedValueOnce(new ApiError('expired', 401));

      const pending = restoreSession();
      renderWithRoutes('/admin/settings');
      await act(() => pending);

      expect(screen.getByText('Login Page')).toBeInTheDocument();
      expect(useAuthStore.getState()).toMatchObject({ token: null, sessionId: null, user: null });
    });
  });
});
