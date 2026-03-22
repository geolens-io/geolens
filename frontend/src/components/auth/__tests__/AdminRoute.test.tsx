import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router';
import { useAuthStore } from '@/stores/auth-store';
import { AdminRoute } from '../AdminRoute';
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
        <Route element={<AdminRoute />}>
          <Route index element={<div>Admin Content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('AdminRoute', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, user: null });
  });

  it('shows 403 when user is not admin', () => {
    useAuthStore.setState({ token: 'abc', user: mockUser(['viewer']) });
    renderWithRoutes('/');

    expect(screen.getByText('403')).toBeInTheDocument();
  });

  it('renders child content for admin user', () => {
    useAuthStore.setState({ token: 'abc', user: mockUser(['admin']) });
    renderWithRoutes('/');

    expect(screen.getByText('Admin Content')).toBeInTheDocument();
  });

  it('shows 403 when user is editor but not admin', () => {
    useAuthStore.setState({ token: 'abc', user: mockUser(['editor']) });
    renderWithRoutes('/');

    expect(screen.getByText('403')).toBeInTheDocument();
  });
});
