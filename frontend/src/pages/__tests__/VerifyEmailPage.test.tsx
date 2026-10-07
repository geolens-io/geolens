import { act, render, screen, waitFor } from '@/test/test-utils';
import { Link, MemoryRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import userEvent from '@testing-library/user-event';

// Mock sonner so we can assert on toast calls.
vi.mock('sonner', () => ({
  toast: {
    info: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

// Mock auth API — all test-specific resolution is done per-test below.
vi.mock('@/api/auth', () => ({
  verifyEmail: vi.fn(),
  resendVerification: vi.fn(),
  getAuthConfig: vi.fn().mockResolvedValue({ registration_enabled: true }),
}));

import { toast } from 'sonner';
import { verifyEmail, resendVerification } from '@/api/auth';
import { VerifyEmailPage } from '../VerifyEmailPage';

const mockedVerifyEmail = vi.mocked(verifyEmail);
const mockedResendVerification = vi.mocked(resendVerification);

function makeWrapper(initialUrl: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  function Wrapper({ children: _children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <MemoryRouter initialEntries={[initialUrl]}>
            <Routes>
              <Route path="/verify-email" element={<VerifyEmailPage />} />
              <Route
                path="/login"
                element={<div>LOGIN PAGE <Link to="/catalog">Catalog</Link></div>}
              />
              <Route path="/catalog" element={<div>CATALOG PAGE</div>} />
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>
    );
  }
  return Wrapper;
}

describe('VerifyEmailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('(a) valid token: calls verifyEmail and navigates to /login on success', async () => {
    mockedVerifyEmail.mockResolvedValue({ message: 'Email verified successfully. You can now log in.' });

    const Wrapper = makeWrapper('/verify-email?token=valid-token-abc123');
    render(<VerifyEmailPage />, { wrapper: Wrapper });

    // Should show the success state after the API resolves.
    await waitFor(() => {
      expect(mockedVerifyEmail).toHaveBeenCalledWith('valid-token-abc123');
    });

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledTimes(1);
    });

    // Advance timers past the 1500ms redirect delay.
    vi.advanceTimersByTime(2000);

    await waitFor(() => {
      expect(screen.getByText('LOGIN PAGE')).toBeInTheDocument();
    });
  });

  it('(b) invalid token: renders error card with working resend control', async () => {
    mockedVerifyEmail.mockRejectedValue(new Error('Invalid or expired verification link'));
    mockedResendVerification.mockResolvedValue({ message: 'If an unverified account with that email exists, a new verification link has been sent.' });

    const Wrapper = makeWrapper('/verify-email?token=expired-token');
    render(<VerifyEmailPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(mockedVerifyEmail).toHaveBeenCalledWith('expired-token');
    });

    // Error heading should be visible.
    await screen.findByText(/verification link/i);

    // Email input should be present.
    const emailInput = screen.getByLabelText(/email/i);
    expect(emailInput).toBeInTheDocument();

    // Fill in email and submit.
    const user = userEvent.setup({ delay: null });
    await user.type(emailInput, 'user@example.com');
    await user.click(screen.getByRole('button', { name: /resend/i }));

    await waitFor(() => {
      expect(mockedResendVerification).toHaveBeenCalledWith('user@example.com');
    });
  });

  it('(c) resend confirmation is generic — does not reveal existence of the email', async () => {
    mockedVerifyEmail.mockRejectedValue(new Error('Invalid or expired verification link'));
    // The backend always returns the same body regardless of whether the email
    // is registered — frontend must show a generic confirmation (T-1231-11).
    mockedResendVerification.mockResolvedValue({
      message: 'If an unverified account with that email exists, a new verification link has been sent.',
    });

    const Wrapper = makeWrapper('/verify-email?token=bad-token');
    render(<VerifyEmailPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(mockedVerifyEmail).toHaveBeenCalledWith('bad-token');
    });

    // Wait for the error card.
    await screen.findByRole('button', { name: /resend/i });

    const user = userEvent.setup({ delay: null });
    const emailInput = screen.getByLabelText(/email/i);
    await user.type(emailInput, 'nonexistent@example.com');
    await user.click(screen.getByRole('button', { name: /resend/i }));

    await waitFor(() => {
      // The generic "resendSent" confirmation text should appear — not a
      // message that reveals whether the email is registered.
      const confirmationEl = screen.queryByRole('button', { name: /resend/i });
      expect(confirmationEl).not.toBeInTheDocument();
    });

    // Confirm the resend was called (enumeration-safe: same 200 regardless of email).
    expect(mockedResendVerification).toHaveBeenCalledWith('nonexistent@example.com');
  });

  it('(d) missing token shows error without calling verifyEmail', async () => {
    const Wrapper = makeWrapper('/verify-email');
    render(<VerifyEmailPage />, { wrapper: Wrapper });

    // With no token param the error state should render.
    await screen.findByRole('button', { name: /resend/i });
    expect(mockedVerifyEmail).not.toHaveBeenCalled();
  });

  it('keeps the page the user navigated to after verifying', async () => {
    mockedVerifyEmail.mockResolvedValue({ message: 'verified' });

    const Wrapper = makeWrapper('/verify-email?token=valid-token');
    render(<VerifyEmailPage />, { wrapper: Wrapper });

    const user = userEvent.setup({ delay: null, advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole('link', { name: /sign in/i }));
    await user.click(await screen.findByRole('link', { name: 'Catalog' }));
    expect(screen.getByText('CATALOG PAGE')).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(2000);
    });

    expect(screen.getByText('CATALOG PAGE')).toBeInTheDocument();
    expect(screen.queryByText(/LOGIN PAGE/)).not.toBeInTheDocument();
  });

  it('keeps the resend form and announces a failed resend', async () => {
    mockedVerifyEmail.mockRejectedValue(new Error('Invalid or expired verification link'));
    mockedResendVerification.mockRejectedValueOnce(new Error('Service unavailable'));

    const Wrapper = makeWrapper('/verify-email?token=expired-token');
    render(<VerifyEmailPage />, { wrapper: Wrapper });

    const user = userEvent.setup({ delay: null });
    await user.type(await screen.findByLabelText(/email/i), 'user@example.com');
    await user.click(screen.getByRole('button', { name: /resend/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn.t send a new link/i);
    expect(screen.queryByText(/a new link has been sent/i)).not.toBeInTheDocument();

    mockedResendVerification.mockResolvedValueOnce({ message: 'sent' });
    await user.click(screen.getByRole('button', { name: /resend/i }));

    expect(await screen.findByText(/a new link has been sent/i)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(mockedResendVerification).toHaveBeenCalledTimes(2);
  });
});
