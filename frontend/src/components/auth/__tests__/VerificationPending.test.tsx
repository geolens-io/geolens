import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { resendVerification } from '@/api/auth';
import { VerificationPending } from '../VerificationPending';

vi.mock('@/api/auth', () => ({ resendVerification: vi.fn() }));

describe('VerificationPending', () => {
  beforeEach(() => vi.clearAllMocks());

  it('keeps the resend button and announces a failed resend', async () => {
    vi.mocked(resendVerification).mockRejectedValueOnce(new Error('Too many requests'));
    render(<VerificationPending email="user@example.com" />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /resend/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn.t send a new link/i);
    expect(screen.getByRole('button', { name: /resend/i })).toBeEnabled();
    expect(screen.queryByText(/a new link has been sent/i)).not.toBeInTheDocument();
  });

  it('shows the generic confirmation once the resend is accepted', async () => {
    vi.mocked(resendVerification).mockResolvedValueOnce({ message: 'sent' });
    render(<VerificationPending email="user@example.com" />);

    await userEvent.setup().click(screen.getByRole('button', { name: /resend/i }));

    expect(await screen.findByText(/a new link has been sent/i)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
