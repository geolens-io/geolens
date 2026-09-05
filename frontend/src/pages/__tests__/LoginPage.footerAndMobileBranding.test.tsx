/**
 * fix(#1852): /login sits outside AppLayout, so it never got the site
 * footer AppLayout renders on every other route, and the desktop brand
 * panel (logo/headline/features) is `hidden` entirely below 880px, leaving
 * a phone visitor with a bare, unbranded password form. Also, the wordmark
 * used to Link to="/", which with landing_first on bounces straight back
 * to /login for a signed-out visitor — a dead click.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useAuthStore } from '@/stores/auth-store';
import { useBranding } from '@/hooks/use-settings';
import { useEdition } from '@/hooks/use-edition';

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

const mockGetAuthConfig = vi.fn();
const mockGetOAuthProviders = vi.fn();
vi.mock('@/api/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/auth')>();
  return {
    ...actual,
    getAuthConfig: () => mockGetAuthConfig(),
    getOAuthProviders: () => mockGetOAuthProviders(),
  };
});

vi.mock('@/hooks/use-settings', () => ({
  useBranding: vi.fn(),
}));
const mockedUseBranding = vi.mocked(useBranding);

vi.mock('@/hooks/use-edition', () => ({
  useEdition: vi.fn(),
}));
const mockedUseEdition = vi.mocked(useEdition);

// Import after mocks.
import { LoginPage } from '../LoginPage';

function makeWrapper(homeContent: React.ReactNode = <div>HOME</div>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <MemoryRouter initialEntries={['/login']}>
            <Routes>
              <Route path="/login" element={children} />
              <Route path="/" element={homeContent} />
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>
    );
  }
  return { Wrapper };
}

describe('LoginPage footer and mobile branding (#1852)', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
    vi.clearAllMocks();
    mockGetAuthConfig.mockResolvedValue({
      registration_enabled: false,
      password_login_enabled: true,
    });
    mockGetOAuthProviders.mockResolvedValue([]);
    mockedUseBranding.mockReturnValue({
      data: { show_badge: true, privacy_url: null },
    } as ReturnType<typeof useBranding>);
    mockedUseEdition.mockReturnValue({
      isEnterprise: false,
      isLoading: false,
      isResolved: true,
    } as unknown as ReturnType<typeof useEdition>);
  });

  it('renders the same site footer every other route gets (GitHub / Docs / Community / API / license)', async () => {
    const { Wrapper } = makeWrapper();
    render(<LoginPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    });

    expect(screen.getByRole('link', { name: /github/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /docs/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /community/i })).toBeInTheDocument();
  });

  it('adds a compact wordmark + one-line headline for narrow widths (no longer bare below 880px)', async () => {
    const { Wrapper } = makeWrapper();
    render(<LoginPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    });

    // The headline now renders twice: once in the desktop-only hero panel,
    // once in the new mobile-only compact block (each hidden at the other
    // width via CSS — jsdom does not evaluate media queries, so both are
    // present in the DOM; a regression that drops the mobile block back to
    // zero occurrences would fail this).
    expect(screen.getAllByText('Your spatial data, all in one workspace.')).toHaveLength(2);
  });

  it('routes the wordmark through the guest-browse escape hatch, not a bare Link to "/"', async () => {
    const { Wrapper } = makeWrapper(<div data-testid="home">HOME</div>);
    render(<LoginPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    });

    const wordmark = screen.getByRole('button', { name: /GeoLens/ });
    await userEvent.click(wordmark);

    // A plain Link to="/" would also land on HOME in this test's stub route,
    // so the meaningful assertion is the marker LandingFirstGuard reads in
    // production to avoid bouncing the visitor straight back to /login.
    await waitFor(() => expect(screen.getByTestId('home')).toBeInTheDocument());
    expect(sessionStorage.getItem('gl-guest-browse')).toBe('true');
  });

  // fix(#1863 P2, codex round 1): useEdition() reports isEnterprise === false
  // (its default) until the edition query resolves, so an enterprise
  // instance with show_badge false briefly rendered the "Powered by
  // GeoLens" badge, then removed it once isEnterprise flipped true.
  describe('footer badge does not flash before the edition query resolves (#1863 P2)', () => {
    it('does not render the badge while the edition query is unresolved, even on an enterprise instance with the badge hidden', async () => {
      mockedUseBranding.mockReturnValue({
        data: { show_badge: false, privacy_url: null },
      } as ReturnType<typeof useBranding>);
      mockedUseEdition.mockReturnValue({
        // Matches useEdition's real defaults while its query is in flight —
        // isEnterprise defaults false, NOT yet known to be true.
        isEnterprise: false,
        isLoading: true,
        isResolved: false,
      } as unknown as ReturnType<typeof useEdition>);

      const { Wrapper } = makeWrapper();
      render(<LoginPage />, { wrapper: Wrapper });

      await waitFor(() => {
        expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
      });

      // Unresolved: must not show the badge on the strength of a default
      // that has not been confirmed yet.
      expect(screen.queryByRole('link', { name: /powered by geolens/i })).not.toBeInTheDocument();
    });

    it('renders the badge once resolved on a community instance', async () => {
      mockedUseEdition.mockReturnValue({
        isEnterprise: false,
        isLoading: false,
        isResolved: true,
      } as unknown as ReturnType<typeof useEdition>);

      const { Wrapper } = makeWrapper();
      render(<LoginPage />, { wrapper: Wrapper });

      await waitFor(() => {
        expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
      });

      expect(screen.getByRole('link', { name: /powered by geolens/i })).toBeInTheDocument();
    });

    it('hides the badge once resolved on an enterprise instance with the badge disabled', async () => {
      mockedUseBranding.mockReturnValue({
        data: { show_badge: false, privacy_url: null },
      } as ReturnType<typeof useBranding>);
      mockedUseEdition.mockReturnValue({
        isEnterprise: true,
        isLoading: false,
        isResolved: true,
      } as unknown as ReturnType<typeof useEdition>);

      const { Wrapper } = makeWrapper();
      render(<LoginPage />, { wrapper: Wrapper });

      await waitFor(() => {
        expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
      });

      expect(screen.queryByRole('link', { name: /powered by geolens/i })).not.toBeInTheDocument();
    });
  });
});
