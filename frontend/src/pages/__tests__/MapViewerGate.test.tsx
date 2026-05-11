import { render, screen } from '@/test/test-utils';
import { MapViewerGate } from '../MapViewerGate';
import { useAuthStore } from '@/stores/auth-store';
import type { UserResponse } from '@/types/api';

vi.mock('../MapBuilderPage', () => ({
  MapBuilderPage: () => <div data-testid="builder-page" />,
}));

vi.mock('../PublicMapViewerPage', () => ({
  PublicMapViewerPage: () => <div data-testid="public-map-page" />,
}));

function mockUser(overrides?: Partial<UserResponse>): UserResponse {
  return {
    id: '1',
    username: 'testuser',
    email: 'test@example.com',
    is_active: true,
    status: 'approved',
    last_login_at: null,
    created_at: '2026-01-01T00:00:00Z',
    roles: ['viewer'],
    ...overrides,
  };
}

describe('MapViewerGate', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
  });

  it('keeps authenticated user-null route state in loading instead of loading editor chrome', () => {
    useAuthStore.setState({
      token: 'token',
      refreshToken: 'refresh',
      expiresAt: Date.now() + 900_000,
      user: null,
    });

    render(<MapViewerGate />);

    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.queryByTestId('builder-page')).not.toBeInTheDocument();
    expect(screen.queryByTestId('public-map-page')).not.toBeInTheDocument();
  });

  it('loads the builder for editor users', async () => {
    useAuthStore.setState({
      token: 'token',
      refreshToken: 'refresh',
      expiresAt: Date.now() + 900_000,
      user: mockUser({ roles: ['editor'] }),
    });

    render(<MapViewerGate />);

    expect(await screen.findByTestId('builder-page')).toBeInTheDocument();
  });

  it('loads the public viewer for anonymous users', async () => {
    render(<MapViewerGate />);

    expect(await screen.findByTestId('public-map-page')).toBeInTheDocument();
  });
});
