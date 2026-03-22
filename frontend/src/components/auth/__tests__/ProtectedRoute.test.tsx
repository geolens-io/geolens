import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router';
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

function renderWithRoutes(initialRoute = '/') {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <Routes>
        <Route element={<ProtectedRoute />}>
          <Route index element={<div>Protected Content</div>} />
        </Route>
        <Route path="/login" element={<div>Login Page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ProtectedRoute', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, user: null });
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
});
