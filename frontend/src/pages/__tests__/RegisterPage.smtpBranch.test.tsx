import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useAuthStore } from '@/stores/auth-store';
import { getAuthConfig, registerUser } from '@/api/auth';
import { RegisterPage } from '../RegisterPage';

// M1 (Phase 1234 follow-up): RegisterPage must mirror the server contract —
// "check your email" is shown only when email verification is required AND an
// SMTP channel is configured. On a no-SMTP deploy the server falls back to
// admin-approval, so the page must show PendingApproval, not VerificationPending.

vi.mock('sonner', () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

vi.mock('@/api/auth', () => ({
  getAuthConfig: vi.fn(),
  registerUser: vi.fn().mockResolvedValue({ message: 'ok' }),
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

describe('RegisterPage — SMTP-aware post-submit message (M1)', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
    vi.clearAllMocks();
    vi.mocked(registerUser).mockResolvedValue({ message: 'ok' });
  });

  it('verification required but NO SMTP → shows admin-approval, not "check your email"', async () => {
    vi.mocked(getAuthConfig).mockResolvedValue({
      registration_enabled: true,
      email_verification_required: true,
      smtp_configured: false,
    });

    render(<RegisterPage />, { wrapper: makeWrapper() });
    await screen.findByRole('button', { name: /create account/i });
    await submitRegistration();

    expect(await screen.findByText('Account Pending Approval')).toBeInTheDocument();
    expect(screen.queryByText('Check Your Email')).not.toBeInTheDocument();
  });

  it('verification required AND SMTP configured → shows "check your email"', async () => {
    vi.mocked(getAuthConfig).mockResolvedValue({
      registration_enabled: true,
      email_verification_required: true,
      smtp_configured: true,
    });

    render(<RegisterPage />, { wrapper: makeWrapper() });
    await screen.findByRole('button', { name: /create account/i });
    await submitRegistration();

    expect(await screen.findByText('Check Your Email')).toBeInTheDocument();
    expect(screen.queryByText('Account Pending Approval')).not.toBeInTheDocument();
  });
});
