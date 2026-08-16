/**
 * FRONT-01/FRONT-02 (Phase 1223): LandingFirstGuard routing matrix.
 *
 * Scenarios:
 *  A) flag OFF → SearchPage (no redirect)
 *  B) flag ON + no token + no guest marker → redirect to /login
 *  C) flag ON + guest marker set → SearchPage (escape hatch honoured)
 *  D) flag ON + authenticated → SearchPage (token present)
 */
import { act } from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';
import { LandingFirstGuard } from '../LandingFirstGuard';
import type { AuthConfigResponse } from '@/types/api';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock('@/pages/SearchPage', () => ({
  SearchPage: () => <div data-testid="search-page">SearchPage</div>,
}));

vi.mock('@/api/auth', () => ({
  getAuthConfig: vi.fn(),
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

import { getAuthConfig } from '@/api/auth';
const mockGetAuthConfig = vi.mocked(getAuthConfig);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createTestClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
}

function LoginSpy() {
  const loc = useLocation();
  return <div data-testid="login-page">Login{loc.pathname}</div>;
}

function renderGuard(
  config: Partial<AuthConfigResponse> = {},
  options: { token?: string; guestBrowse?: boolean } = {},
) {
  const queryClient = createTestClient();

  // Seed the auth config query result
  const fullConfig: AuthConfigResponse = {
    registration_enabled: false,
    landing_first: false,
    ...config,
  };
  queryClient.setQueryData(['auth', 'config'], fullConfig);

  // Set auth store state
  act(() => {
    useAuthStore.setState({
      token: options.token ?? null,
      user: null,
      refreshToken: null,
      expiresAt: null,
    });
  });

  // Set sessionStorage marker
  if (options.guestBrowse) {
    sessionStorage.setItem('gl-guest-browse', 'true');
  } else {
    sessionStorage.removeItem('gl-guest-browse');
  }

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route index element={<LandingFirstGuard />} />
          <Route path="/login" element={<LoginSpy />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LandingFirstGuard', () => {
  beforeEach(() => {
    sessionStorage.clear();
    mockGetAuthConfig.mockResolvedValue({
      registration_enabled: false,
      landing_first: false,
      auth_methods: [],
    });
    act(() => {
      useAuthStore.setState({ token: null, user: null, refreshToken: null, expiresAt: null });
    });
  });

  it('A) flag OFF — renders SearchPage for anonymous user (default self-hoster path)', () => {
    renderGuard({ landing_first: false });

    expect(screen.getByTestId('search-page')).toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
  });

  it('B) flag ON + no token + no guest marker — redirects to /login', () => {
    renderGuard({ landing_first: true });

    expect(screen.getByTestId('login-page')).toBeInTheDocument();
    expect(screen.queryByTestId('search-page')).not.toBeInTheDocument();
  });

  it('C) flag ON + guest marker set — renders SearchPage (escape hatch)', () => {
    renderGuard({ landing_first: true }, { guestBrowse: true });

    expect(screen.getByTestId('search-page')).toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
  });

  it('D) flag ON + authenticated — renders SearchPage (token present)', () => {
    renderGuard({ landing_first: true }, { token: 'bearer-token-xyz' });

    expect(screen.getByTestId('search-page')).toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
  });

  it('E) DEMO-04 — flag ON + anon + /maps/:id route → NOT intercepted by the index guard', () => {
    const queryClient = createTestClient();
    queryClient.setQueryData(['auth', 'config'], {
      registration_enabled: false,
      landing_first: true,
      auth_methods: [],
    });
    act(() => {
      useAuthStore.setState({ token: null, user: null, refreshToken: null, expiresAt: null });
    });
    sessionStorage.removeItem('gl-guest-browse');

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/maps/some-map-id']}>
          <Routes>
            <Route index element={<LandingFirstGuard />} />
            <Route path="/maps/:id" element={<div data-testid="map-route">Map</div>} />
            <Route path="/login" element={<LoginSpy />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    // The index guard is NOT mounted at /maps/:id — it only guards "/".
    // The map route renders; login is NOT shown.
    expect(screen.getByTestId('map-route')).toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
  });

  /**
   * fix(#1515): the guest-browse marker is read DURING RENDER, so a throw here
   * is a blank page. `typeof sessionStorage !== 'undefined'` did not protect
   * it — the property exists and the READ is what raises. Observed as
   * "SecurityError: Failed to read the 'sessionStorage' property from 'Window'"
   * inside a sandboxed frame, surfaced by React Router as a page error.
   *
   * Deny the way the browser denies: a getter that throws on property access.
   * Mocking getItem to return null would prove nothing, because the old code
   * never reached getItem.
   */
  function denyStorage(): () => void {
    const original = Object.getOwnPropertyDescriptor(window, 'sessionStorage');
    const descriptor: PropertyDescriptor = {
      configurable: true,
      get() {
        throw new DOMException(
          "Failed to read the 'sessionStorage' property from 'Window': The document " +
            "is sandboxed and lacks the 'allow-same-origin' flag.",
          'SecurityError',
        );
      },
    };
    Object.defineProperty(window, 'sessionStorage', descriptor);
    if (globalThis !== (window as unknown as typeof globalThis)) {
      Object.defineProperty(globalThis, 'sessionStorage', descriptor);
    }
    return () => {
      if (original) {
        Object.defineProperty(window, 'sessionStorage', original);
        if (globalThis !== (window as unknown as typeof globalThis)) {
          Object.defineProperty(globalThis, 'sessionStorage', original);
        }
      }
    };
  }

  function renderWithConfig(landingFirst: boolean) {
    const queryClient = createTestClient();
    queryClient.setQueryData(['auth', 'config'], {
      registration_enabled: false,
      landing_first: landingFirst,
      auth_methods: [],
    });
    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/']}>
          <Routes>
            <Route index element={<LandingFirstGuard />} />
            <Route path="/login" element={<LoginSpy />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it('F) #1515 — storage denied + flag OFF: renders SearchPage instead of throwing', () => {
    const restore = denyStorage();
    try {
      act(() => {
        useAuthStore.setState({ token: null, user: null, refreshToken: null, expiresAt: null });
      });
      renderWithConfig(false);
      expect(screen.getByTestId('search-page')).toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it('F2) #1515 — storage denied + flag ON + anon: redirects, treating the marker as absent', () => {
    const restore = denyStorage();
    try {
      act(() => {
        useAuthStore.setState({ token: null, user: null, refreshToken: null, expiresAt: null });
      });
      renderWithConfig(true);
      expect(screen.getByTestId('login-page')).toBeInTheDocument();
      expect(screen.queryByTestId('search-page')).not.toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it('config absent (undefined) — defaults to flag OFF → SearchPage', () => {
    const queryClient = createTestClient();
    // No query data seeded — config will be undefined

    act(() => {
      useAuthStore.setState({ token: null, user: null, refreshToken: null, expiresAt: null });
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/']}>
          <Routes>
            <Route index element={<LandingFirstGuard />} />
            <Route path="/login" element={<LoginSpy />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByTestId('search-page')).toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
  });
});
