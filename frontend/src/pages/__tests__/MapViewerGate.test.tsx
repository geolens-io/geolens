import { render, screen } from '@/test/test-utils';
import { Route, Routes } from 'react-router';
import { MapViewerGate } from '../MapViewerGate';
import { useAuthStore } from '@/stores/auth-store';
import { useMapAccess } from '@/hooks/use-maps';
import type { UserResponse } from '@/types/api';

vi.mock('../MapBuilderPage', () => ({
  MapBuilderPage: () => <div data-testid="builder-page" />,
}));

vi.mock('../PublicMapViewerPage', () => ({
  PublicMapViewerPage: () => <div data-testid="public-map-page" />,
}));

vi.mock('@/hooks/use-maps', () => ({
  useMapAccess: vi.fn(),
}));

const mockedUseMapAccess = vi.mocked(useMapAccess);

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
    mockedUseMapAccess.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
    } as never);
  });

  function renderRoute(route = '/maps/map-1') {
    return render(
      <Routes>
        <Route path="/maps/:id" element={<MapViewerGate />} />
      </Routes>,
      { route },
    );
  }

  it('keeps authenticated user-null route state in loading instead of loading editor chrome', () => {
    useAuthStore.setState({
      token: 'token',
      refreshToken: 'refresh',
      expiresAt: Date.now() + 900_000,
      user: null,
    });

    renderRoute();

    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.queryByTestId('builder-page')).not.toBeInTheDocument();
    expect(screen.queryByTestId('public-map-page')).not.toBeInTheDocument();
  });

  it('loads the builder for editor users', async () => {
    mockedUseMapAccess.mockReturnValue({
      data: { can_view: true, can_edit: true },
      isLoading: false,
      isError: false,
    } as never);
    useAuthStore.setState({
      token: 'token',
      refreshToken: 'refresh',
      expiresAt: Date.now() + 900_000,
      user: mockUser({ roles: ['editor'] }),
    });

    renderRoute();

    expect(await screen.findByTestId('builder-page')).toBeInTheDocument();
  });

  it('loads the public viewer when server denies builder access for a stale editor cache', async () => {
    mockedUseMapAccess.mockReturnValue({
      data: { can_view: true, can_edit: false },
      isLoading: false,
      isError: false,
    } as never);
    useAuthStore.setState({
      token: 'token',
      refreshToken: 'refresh',
      expiresAt: Date.now() + 900_000,
      user: mockUser({ roles: ['editor'] }),
    });

    renderRoute();

    expect(await screen.findByTestId('public-map-page')).toBeInTheDocument();
    expect(screen.queryByTestId('builder-page')).not.toBeInTheDocument();
  });

  it('loads the public viewer for anonymous users', async () => {
    renderRoute();

    expect(await screen.findByTestId('public-map-page')).toBeInTheDocument();
  });

  // fix(#430 V-15): editors can preview the exact anonymous rendering via ?preview=viewer.
  it('renders the public viewer for an editor when ?preview=viewer is set', async () => {
    mockedUseMapAccess.mockReturnValue({
      data: { can_view: true, can_edit: true },
      isLoading: false,
      isError: false,
    } as never);
    useAuthStore.setState({
      token: 'token',
      refreshToken: 'refresh',
      expiresAt: Date.now() + 900_000,
      user: mockUser({ roles: ['editor'] }),
    });

    renderRoute('/maps/map-1?preview=viewer');

    expect(await screen.findByTestId('public-map-page')).toBeInTheDocument();
    expect(screen.queryByTestId('builder-page')).not.toBeInTheDocument();
  });

  it('ignores ?preview=viewer for a non-editor (already the public viewer)', async () => {
    renderRoute('/maps/map-1?preview=viewer');

    expect(await screen.findByTestId('public-map-page')).toBeInTheDocument();
  });

  describe('optimistic builder-chunk warmup (#1778)', () => {
    // The dynamic import() this fix adds is cached process-wide by
    // Vitest/Node's ESM module registry once any test in this file resolves
    // it (e.g. "loads the builder for editor users" above), so a later
    // test's own import() call would silently hit that cache and never
    // re-invoke the mock factory — making call-count assertions order
    // dependent and unreliable here. The property under test is really a
    // source-shape one (an effect fires the import independently of the
    // Suspense render path, gated on the optimistic-editor condition), so
    // pin it against the source instead of racing the module cache.
    it('fires the import from a useEffect gated on hasToken && editorFallback, not from the Suspense render branch', async () => {
      const { readFileSync } = await import('node:fs');
      const { resolve } = await import('node:path');
      const source = readFileSync(resolve(__dirname, '../MapViewerGate.tsx'), 'utf-8');

      expect(source).toMatch(/useEffect\(\(\)\s*=>\s*\{[^}]*hasToken\s*&&\s*editorFallback[^}]*import\(['"]\.\/MapBuilderPage['"]\)/s);
    });
  });
});
