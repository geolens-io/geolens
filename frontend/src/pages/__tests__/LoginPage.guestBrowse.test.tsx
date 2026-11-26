/**
 * Guest-browse escape hatch under denied storage.
 *
 * The claim under test is "an anonymous visitor can reach the catalog", NOT
 * "a navigation happened". Those come apart: the button writes
 * `gl-guest-browse` to sessionStorage and navigates to "/", where the REAL
 * `LandingFirstGuard` reads that marker back and bounces anyone without it to
 * /login. A write that silently no-ops therefore leaves the button dead, and
 * the visitor cannot tell that from a click that did nothing.
 *
 * So this file routes "/" through the production guard. An earlier revision
 * substituted a dummy catalog route, which asserted the navigation and
 * could mask the bounce. `SearchPage` is still stubbed, which is
 * a sound substitution: it is the destination's content, not the component
 * whose behaviour is the claim.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useAuthStore } from '@/stores/auth-store';
import { queryKeys } from '@/lib/query-keys';
import { denySessionStorage } from '@/test/deny-storage';
import { _resetSessionStorageFallback } from '@/lib/storage';
import type { AuthConfigResponse } from '@/types/api';

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({
    login: vi.fn(),
    logout: vi.fn(),
    token: null,
    user: null,
    isAdmin: false,
    isEditor: false,
  }),
}));

// The catalog's CONTENT is stubbed; the guard in front of it is real.
vi.mock('@/pages/SearchPage', () => ({
  SearchPage: () => <div data-testid="search-page">SearchPage</div>,
}));

vi.mock('@/api/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/auth')>();
  return {
    ...actual,
    getAuthConfig: vi.fn(),
    getOAuthProviders: vi.fn(),
  };
});

import { getAuthConfig, getOAuthProviders } from '@/api/auth';
import { LandingFirstGuard } from '@/components/auth/LandingFirstGuard';
import { landDotsPath, restLongitude } from '@/lib/login-globe';
import { LoginPage } from '../LoginPage';

const LANDING_FIRST_CONFIG = {
  registration_enabled: false,
  landing_first: true,
  password_login_enabled: true,
  auth_methods: [],
} as unknown as AuthConfigResponse;

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  queryClient.setQueryData(queryKeys.authConfig.config, LANDING_FIRST_CONFIG);
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <MemoryRouter initialEntries={['/login']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            {/* The production guard, not a stand-in. */}
            <Route path="/" element={<LandingFirstGuard />} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

async function clickBrowseCatalog() {
  const [browse] = await screen.findAllByRole('button', { name: /browse the catalog/i });
  await userEvent.click(browse);
}

describe('LoginPage guest-browse reaches the catalog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getAuthConfig).mockResolvedValue(LANDING_FIRST_CONFIG);
    vi.mocked(getOAuthProviders).mockResolvedValue([]);
    useAuthStore.setState({ token: null, user: null });
    sessionStorage.clear();
    // The mirror is module state; sessionStorage.clear() does not reach it.
    _resetSessionStorageFallback();
  });

  it('reaches the catalog and records the marker when storage works', async () => {
    renderApp();
    await clickBrowseCatalog();

    await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
    expect(sessionStorage.getItem('gl-guest-browse')).toBe('true');
  });

  // Navigation must preserve the marker or LandingFirstGuard returns the visitor to /login.
  it('reaches the catalog when sessionStorage access throws', async () => {
    renderApp();

    const restore = denySessionStorage();
    try {
      await clickBrowseCatalog();

      await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
    } finally {
      restore();
    }
  });
});

describe('LoginPage accessibility', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getOAuthProviders).mockResolvedValue([]);
    useAuthStore.setState({ token: null, user: null });
  });

  it('announces a failed auth-config load as an alert', async () => {
    vi.mocked(getAuthConfig).mockRejectedValue(new Error('boom'));
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <TooltipProvider>
          <MemoryRouter initialEntries={['/login']}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole('alert')).toHaveTextContent(/sign-in settings/i);
  });

  it('shows the page while the sign-in settings load, with only the form waiting', () => {
    vi.mocked(getAuthConfig).mockReturnValue(new Promise(() => {}));
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <TooltipProvider>
          <MemoryRouter initialEntries={['/login']}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>,
    );
    expect(screen.getByRole('heading', { name: 'Sign In' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /browse the catalog/i }).length).toBeGreaterThan(0);
    expect(screen.getByRole('status')).toHaveTextContent('Loading...');
    expect(screen.queryByLabelText(/username/i)).not.toBeInTheDocument();
  });
});

describe('LoginPage decorative globe', () => {
  const landPath = (container: HTMLElement) =>
    container.querySelector('svg[viewBox="0 0 800 800"] path[stroke-linecap="round"]')?.getAttribute('d');

  /** Pins the browser's UTC offset so no test depends on the machine's time zone. */
  const setUtcOffset = (minutes: number) =>
    vi.spyOn(Date.prototype, 'getTimezoneOffset').mockReturnValue(minutes);

  function stubMedia({ reducedMotion = false, wide = true } = {}) {
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('prefers-reduced-motion') ? reducedMotion : wide,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
  }

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getAuthConfig).mockResolvedValue(LANDING_FIRST_CONFIG);
    vi.mocked(getOAuthProviders).mockResolvedValue([]);
    useAuthStore.setState({ token: null, user: null });
    setUtcOffset(300);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('turns into the pose for the browser time zone and stops well inside five seconds', () => {
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance'] });
    const { container } = renderApp();
    expect(landPath(container)).not.toBe(landDotsPath(restLongitude(300)));

    vi.advanceTimersByTime(3000);
    expect(landPath(container)).toBe(landDotsPath(restLongitude(300)));
    // A frame still queued here would mean the motion never ends (WCAG 2.2.2).
    expect(vi.getTimerCount()).toBe(0);
  });

  it('faces a different part of the world for a different time zone', () => {
    setUtcOffset(-330);
    stubMedia({ reducedMotion: true });
    const { container } = renderApp();
    expect(landPath(container)).toBe(landDotsPath(restLongitude(-330)));
    expect(landPath(container)).not.toBe(landDotsPath(restLongitude(300)));
  });

  it('cancels the turn when the page unmounts', () => {
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance'] });
    const { unmount } = renderApp();
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('stays still for people who asked their system for less motion', () => {
    stubMedia({ reducedMotion: true });
    const raf = vi.spyOn(window, 'requestAnimationFrame');
    const { container } = renderApp();
    expect(landPath(container)).toBe(landDotsPath(restLongitude(300)));
    expect(raf).not.toHaveBeenCalled();
  });

  it('does not animate where the brand panel is hidden', () => {
    stubMedia({ wide: false });
    const raf = vi.spyOn(window, 'requestAnimationFrame');
    renderApp();
    expect(raf).not.toHaveBeenCalled();
  });

  it('hides the decoration from assistive technology and prints no coordinate', () => {
    stubMedia({ reducedMotion: true });
    const { container } = renderApp();
    expect(container.querySelector('svg[viewBox="0 0 800 800"]')).toHaveAttribute('aria-hidden', 'true');
    expect(container.textContent).not.toContain('°');
  });
});
