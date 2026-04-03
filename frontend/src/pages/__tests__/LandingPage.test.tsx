import { act } from 'react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router';
import { render, screen, waitFor } from '@/test/test-utils';
import { LandingPage } from '@/pages/LandingPage';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

const initialAuthState = useAuthStore.getState();

function setAnonymousUser() {
  act(() => {
    useAuthStore.setState({
      ...initialAuthState,
      token: null,
      refreshToken: null,
      expiresAt: null,
      user: null,
    });
  });
}

function setAuthenticatedUser() {
  act(() => {
    useAuthStore.setState({
      ...initialAuthState,
      token: 'token',
      refreshToken: 'refresh-token',
      expiresAt: Date.now() + 60_000,
      user: {
        id: 'user-1',
        username: 'demo',
        email: 'demo@example.com',
        is_active: true,
        status: 'active',
        created_at: '2026-04-01T00:00:00Z',
        roles: ['editor'],
      },
    });
  });
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}{location.search}</div>;
}

function renderLanding(initialRoute = '/') {
  return render(
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/search" element={<LocationProbe />} />
      <Route path="/login" element={<div>Login route</div>} />
    </Routes>,
    { route: initialRoute },
  );
}

describe('LandingPage', () => {
  beforeEach(() => {
    act(() => {
      useAuthStore.setState(initialAuthState, true);
    });
  });

  it('renders the public landing page with trust signals and app entry CTAs', () => {
    setAnonymousUser();

    renderLanding();

    expect(screen.getByRole('heading', { level: 1, name: /your team's spatial data, searchable in one place/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /explore catalog/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /sign in/i })).toHaveAttribute('href', '/login');
    expect(screen.getByRole('link', { name: /view on github/i })).toHaveClass('min-h-10');
  });

  it('hands typed search intent off to the search workspace route', async () => {
    setAnonymousUser();
    const user = userEvent.setup();

    renderLanding();

    await user.type(screen.getByRole('textbox', { name: /search geospatial data/i }), 'wetlands');
    await user.click(screen.getByRole('button', { name: /explore catalog/i }));

    expect(screen.getByTestId('location-probe')).toHaveTextContent('/search?q=wetlands');
  });

  it('redirects authenticated users to the search workspace', async () => {
    setAuthenticatedUser();

    renderLanding();

    await waitFor(() => {
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/search');
    });
  });

  it('preserves legacy root query links by redirecting them to /search', async () => {
    setAnonymousUser();

    renderLanding('/?q=roads');

    await waitFor(() => {
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/search?q=roads');
    });
  });
});
