import { render, screen } from '@/test/test-utils';
import { MemoryRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useAuthStore } from '@/stores/auth-store';
import { RegisterPage } from '../RegisterPage';

// Mock sonner so we can assert on toast calls without needing the DOM provider.
vi.mock('sonner', () => ({
  toast: {
    info: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

// Mock getAuthConfig so no real network call is made.
vi.mock('@/api/auth', () => ({
  getAuthConfig: vi.fn().mockResolvedValue({ registration_enabled: false }),
  registerUser: vi.fn(),
  loginUser: vi.fn(),
}));

// Import after mocks are registered.
import { toast } from 'sonner';

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  function Wrapper({ children: _children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <MemoryRouter initialEntries={['/register']}>
            <Routes>
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/" element={<div>HOME</div>} />
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>
    );
  }
  return { Wrapper, queryClient };
}

describe('RegisterPage — authenticated user redirect (ROUTE-03)', () => {
  beforeEach(() => {
    // Reset auth store to anonymous state before each test.
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

  it('Test 1: authenticated user sees toast and is redirected to /', async () => {
    // Set up authenticated state.
    useAuthStore.setState({
      token: 'fake-jwt-token',
      refreshToken: 'fake-refresh',
      expiresAt: Date.now() + 3600 * 1000,
      user: {
        id: '1',
        username: 'admin',
        email: 'admin@example.com',
        roles: ['admin'],
        is_active: true,
        status: 'active',
        last_login_at: null,
        created_at: new Date().toISOString(),
      },
    });

    const { Wrapper } = makeWrapper();
    render(<RegisterPage />, { wrapper: Wrapper });

    // The page should redirect to "/" — HOME sentinel should appear.
    await screen.findByText('HOME');

    // toast.info must have been called with the alreadySignedIn i18n string.
    expect(toast.info).toHaveBeenCalledTimes(1);
    expect(toast.info).toHaveBeenCalledWith(
      'You\'re already signed in — redirected to home.'
    );
  });

  it('Test 2: anonymous user sees Registration Disabled card without any toast', async () => {
    // token is null (set in beforeEach).
    const { Wrapper } = makeWrapper();
    render(<RegisterPage />, { wrapper: Wrapper });

    // The "Registration Disabled" card should appear (registration_enabled: false).
    await screen.findByText('Registration Disabled');

    // No toast should fire.
    expect(toast.info).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('Test 3: re-rendering the authenticated page does not fire toast a second time', async () => {
    useAuthStore.setState({
      token: 'fake-jwt-token',
      refreshToken: 'fake-refresh',
      expiresAt: Date.now() + 3600 * 1000,
      user: {
        id: '1',
        username: 'admin',
        email: 'admin@example.com',
        roles: ['admin'],
        is_active: true,
        status: 'active',
        last_login_at: null,
        created_at: new Date().toISOString(),
      },
    });

    const { Wrapper } = makeWrapper();
    const { rerender } = render(<RegisterPage />, { wrapper: Wrapper });

    // Wait for redirect.
    await screen.findByText('HOME');

    // Force a re-render.
    rerender(<RegisterPage />);

    // Toast must still only have been called once.
    expect(toast.info).toHaveBeenCalledTimes(1);
  });
});
