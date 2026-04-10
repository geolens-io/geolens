import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router';
import { useAuthStore } from '@/stores/auth-store';
import { EditorRoute } from '../EditorRoute';
import type { UserResponse } from '@/types/api';

function mockUser(roles: string[] = ['viewer']): UserResponse {
  return {
    id: '1',
    username: 'testuser',
    email: 'test@example.com',
    is_active: true,
    status: 'approved',
    last_login_at: null,
    created_at: '2025-01-01T00:00:00Z',
    roles,
  };
}

function renderWithRoutes(initialRoute = '/') {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <Routes>
        <Route element={<EditorRoute />}>
          <Route index element={<div>Editor Content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('EditorRoute', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, user: null });
  });

  it('shows 403 when user is viewer only', () => {
    useAuthStore.setState({ token: 'abc', user: mockUser(['viewer']) });
    renderWithRoutes('/');

    expect(screen.getByText('403')).toBeInTheDocument();
  });

  it('renders child content for editor user', () => {
    useAuthStore.setState({ token: 'abc', user: mockUser(['editor']) });
    renderWithRoutes('/');

    expect(screen.getByText('Editor Content')).toBeInTheDocument();
  });

  it('renders child content for admin user', () => {
    useAuthStore.setState({ token: 'abc', user: mockUser(['admin']) });
    renderWithRoutes('/');

    expect(screen.getByText('Editor Content')).toBeInTheDocument();
  });
});
