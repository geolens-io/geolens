import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router';
import { useAuthStore } from '@/stores/auth-store';
import { ProtectedRoute } from '../ProtectedRoute';
import type { UserResponse } from '@/types/api';

function mockUser(roles: string[] = ['viewer']): UserResponse {
  return {
    id: '1',
    username: 'testuser',
    email: 'test@example.com',
    is_active: true,
    status: 'approved',
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
});
