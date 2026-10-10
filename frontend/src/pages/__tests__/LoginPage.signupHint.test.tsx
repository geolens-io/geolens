import { render, screen } from '@/test/test-utils';
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

// Partial mock: control getAuthConfig + getOAuthProviders; keep all other exports real.
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

describe('LoginPage sign-up and support hint', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
    vi.clearAllMocks();
    mockGetOAuthProviders.mockResolvedValue([]);
  });

  it('shows the support hint and no sign-up link while sign-up is closed', async () => {
    mockGetAuthConfig.mockResolvedValue({ allow_signup: false, password_login_enabled: true });

    const { Wrapper } = makeWrapper();
    render(<LoginPage />, { wrapper: Wrapper });

    expect(await screen.findByText(/contact a geolens administrator/i)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /create one/i })).not.toBeInTheDocument();
  });

  it('shows the sign-up link and no support hint while sign-up is open', async () => {
    mockGetAuthConfig.mockResolvedValue({ allow_signup: true, password_login_enabled: true });

    const { Wrapper } = makeWrapper();
    render(<LoginPage />, { wrapper: Wrapper });

    expect(await screen.findByRole('link', { name: /create one/i })).toBeInTheDocument();
    expect(screen.queryByText(/contact a geolens administrator/i)).not.toBeInTheDocument();
  });
});
