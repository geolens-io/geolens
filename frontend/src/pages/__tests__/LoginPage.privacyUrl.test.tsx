/**
 * PRIV-1: the login page's privacy-policy link is per-instance config, not a
 * hardcoded getgeolens.com URL. The consent paragraph only makes sense with a
 * link in it ("agree to our [Privacy Policy]"), so the whole paragraph is
 * gated on `privacy_url`, not just the anchor.
 */
import { render, screen, waitFor } from '@/test/test-utils';
import { MemoryRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useAuthStore } from '@/stores/auth-store';
import { useBranding } from '@/hooks/use-settings';

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

// Import after mocks.
import { LoginPage } from '../LoginPage';

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  // Renders `children` (the `ui` passed to `render(ui, { wrapper: Wrapper })`)
  // at the /login route, rather than a second, independent <LoginPage />
  // that happened to look the same as what the test actually passed in.
  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <MemoryRouter initialEntries={['/login']}>
            <Routes>
              <Route path="/login" element={children} />
              <Route path="/" element={<div>HOME</div>} />
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>
    );
  }
  return { Wrapper };
}

describe('LoginPage privacy-policy link (PRIV-1)', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
    vi.clearAllMocks();
    mockGetAuthConfig.mockResolvedValue({
      registration_enabled: false,
      password_login_enabled: true,
    });
    mockGetOAuthProviders.mockResolvedValue([]);
  });

  it('shows the privacy policy link when the operator has configured one', async () => {
    mockedUseBranding.mockReturnValue({
      data: { show_badge: true, privacy_url: 'https://operator.example.com/privacy' },
    } as ReturnType<typeof useBranding>);

    const { Wrapper } = makeWrapper();
    render(<LoginPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    });
    const privacyLink = screen.getByRole('link', { name: /privacy policy/i });
    expect(privacyLink).toHaveAttribute('href', 'https://operator.example.com/privacy');
  });

  it('hides the consent paragraph when no privacy URL is configured', async () => {
    mockedUseBranding.mockReturnValue({
      data: { show_badge: true, privacy_url: null },
    } as ReturnType<typeof useBranding>);

    const { Wrapper } = makeWrapper();
    render(<LoginPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    });
    // The link alone is not enough: an <a> with no href has role "generic",
    // not "link", so a gate that only hid the anchor (leaving the "By
    // signing in you agree to our ." copy behind, sentence and all) would
    // still pass a role-only query. Assert the whole paragraph is gone.
    expect(screen.queryByRole('link', { name: /privacy policy/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/agree to our/i)).not.toBeInTheDocument();
  });

  it('does not render the link for an unsafe stored value (client-side scheme guard)', async () => {
    // The backend validates privacy_url three times over (admin write, boot,
    // read), but a rolling upgrade can have a stale API pod still serving a
    // pre-check value. This is the client-side belt-and-braces guard for
    // that window, not a re-test of the backend's own validation.
    mockedUseBranding.mockReturnValue({
      data: { show_badge: true, privacy_url: 'javascript:alert(document.cookie)' },
    } as ReturnType<typeof useBranding>);

    const { Wrapper } = makeWrapper();
    render(<LoginPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    });
    expect(screen.queryByRole('link', { name: /privacy policy/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/agree to our/i)).not.toBeInTheDocument();
  });
});
