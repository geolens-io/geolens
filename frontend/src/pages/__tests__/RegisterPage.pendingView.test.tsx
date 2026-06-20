import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useAuthStore } from '@/stores/auth-store';
import { getAuthConfig, registerUser } from '@/api/auth';
import { RegisterPage } from '../RegisterPage';

// M1 follow-up (Phase 1234): the post-submit pending view is driven by the
// server's authoritative RegisterResponse.next_step — NOT inferred from a cached
// /auth/config snapshot. This eliminates the config-fetch race and matches
// exactly what the backend did (which is also enumeration-safe: a collision and
// a new signup return the same next_step).

vi.mock('sonner', () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

vi.mock('@/api/auth', () => ({
  getAuthConfig: vi.fn(),
  registerUser: vi.fn(),
  loginUser: vi.fn(),
}));

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <MemoryRouter initialEntries={['/register']}>
            <Routes>
              <Route path="/register" element={children} />
              <Route path="/" element={<div>HOME</div>} />
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>
    );
  }
  return Wrapper;
}

async function submitRegistration() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/username/i), 'newuser');
  await user.type(screen.getByLabelText(/email/i), 'new@example.com');
  await user.type(screen.getByLabelText(/password/i), 'TestPass1234!');
  await user.click(screen.getByRole('button', { name: /create account/i }));
}

describe('RegisterPage — post-submit view follows server next_step (M1 follow-up)', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
    vi.clearAllMocks();
    // Config only gates whether the form is shown; it must NOT drive the
    // post-submit branch anymore. Set verification ON to prove that.
    vi.mocked(getAuthConfig).mockResolvedValue({
      registration_enabled: true,
      email_verification_required: true,
    });
  });

  it('next_step="await_approval" → shows admin-approval, not "check your email"', async () => {
    vi.mocked(registerUser).mockResolvedValue({ message: 'ok', next_step: 'await_approval' });

    render(<RegisterPage />, { wrapper: makeWrapper() });
    await screen.findByRole('button', { name: /create account/i });
    await submitRegistration();

    expect(await screen.findByText('Account Pending Approval')).toBeInTheDocument();
    expect(screen.queryByText('Check Your Email')).not.toBeInTheDocument();
  });

  it('next_step="verify_email" → shows "check your email"', async () => {
    vi.mocked(registerUser).mockResolvedValue({ message: 'ok', next_step: 'verify_email' });

    render(<RegisterPage />, { wrapper: makeWrapper() });
    await screen.findByRole('button', { name: /create account/i });
    await submitRegistration();

    expect(await screen.findByText('Check Your Email')).toBeInTheDocument();
    expect(screen.queryByText('Account Pending Approval')).not.toBeInTheDocument();
  });

  it('missing next_step (older server) → defaults to admin-approval', async () => {
    vi.mocked(registerUser).mockResolvedValue({ message: 'ok' });

    render(<RegisterPage />, { wrapper: makeWrapper() });
    await screen.findByRole('button', { name: /create account/i });
    await submitRegistration();

    expect(await screen.findByText('Account Pending Approval')).toBeInTheDocument();
    expect(screen.queryByText('Check Your Email')).not.toBeInTheDocument();
  });
});
