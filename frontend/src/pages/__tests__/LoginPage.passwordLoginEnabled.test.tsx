/**
 * SSO-03 (Phase 1236 Plan 02): LoginPage conditional render based on
 * password_login_enabled from /auth/config.
 *
 * When password_login_enabled is false, the username/password form (LoginForm)
 * must NOT render; a "sign in with provider" message must appear.
 * When true or undefined (absent — back-compat), the form must render normally.
 */
import { render, screen, waitFor } from '@/test/test-utils';
import { MemoryRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useAuthStore } from '@/stores/auth-store';

// Mock sonner to suppress toast effects during tests.
vi.mock('sonner', () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

// Mock use-auth so LoginForm does not require a live network.
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

// Partial mock: control getAuthConfig; keep all other exports real.
const mockGetAuthConfig = vi.fn();
vi.mock('@/api/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/auth')>();
  return {
    ...actual,
    getAuthConfig: () => mockGetAuthConfig(),
  };
});

// Import after mocks.
import { LoginPage } from '../LoginPage';

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  function Wrapper({ children: _children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <MemoryRouter initialEntries={['/login']}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/" element={<div>HOME</div>} />
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>
    );
  }
  return { Wrapper, queryClient };
}

describe('LoginPage — password_login_enabled conditional render (SSO-03)', () => {
  beforeEach(() => {
    // Start as anonymous (no token).
    useAuthStore.setState({
      token: null,
      refreshToken: null,
      expiresAt: null,
      user: null,
    });
    vi.clearAllMocks();
  });

  afterEach(() => {
    useAuthStore.setState({
      token: null,
      refreshToken: null,
      expiresAt: null,
      user: null,
    });
  });

  it('shows the username/password form when password_login_enabled is true', async () => {
    mockGetAuthConfig.mockResolvedValue({
      registration_enabled: false,
      password_login_enabled: true,
    });

    const { Wrapper } = makeWrapper();
    render(<LoginPage />, { wrapper: Wrapper });

    // Wait for config to resolve and form to appear.
    await waitFor(() => {
      expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    });
    expect(screen.getByLabelText('Password', { exact: true })).toBeInTheDocument();
    expect(screen.queryByText(/sign in using your organization/i)).not.toBeInTheDocument();
  });

  it('shows the username/password form when password_login_enabled is absent (back-compat)', async () => {
    mockGetAuthConfig.mockResolvedValue({
      registration_enabled: false,
      // password_login_enabled intentionally absent — older server.
    });

    const { Wrapper } = makeWrapper();
    render(<LoginPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/sign in using your organization/i)).not.toBeInTheDocument();
  });

  it('hides the username/password form and shows SSO-only message when password_login_enabled is false', async () => {
    mockGetAuthConfig.mockResolvedValue({
      registration_enabled: false,
      password_login_enabled: false,
    });

    const { Wrapper } = makeWrapper();
    render(<LoginPage />, { wrapper: Wrapper });

    // Wait for the SSO-only message to appear after config resolves.
    await waitFor(() => {
      expect(
        screen.getByText(/sign in using your organization/i)
      ).toBeInTheDocument();
    });
    // The username/password form must not render.
    expect(screen.queryByLabelText(/username/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Password', { exact: true })).not.toBeInTheDocument();
  });
});
