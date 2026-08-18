import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { RegisterForm } from '../RegisterForm';
import { useBranding } from '@/hooks/use-settings';

vi.mock('@/api/auth', () => ({
  registerUser: vi.fn().mockResolvedValue({ message: 'ok' }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useBranding: vi.fn(),
}));

const mockedUseBranding = vi.mocked(useBranding);

describe('RegisterForm', () => {
  beforeEach(() => {
    mockedUseBranding.mockReturnValue({
      data: { show_badge: true, privacy_url: null },
    } as ReturnType<typeof useBranding>);
  });

  it('renders username, email, and password fields', () => {
    render(<RegisterForm onSuccess={vi.fn()} />);

    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    // password field now carries a reveal toggle (aria-label "Show password"),
    // so scope the lookup to the input to avoid matching the button.
    expect(screen.getByLabelText(/password/i, { selector: 'input' })).toBeInTheDocument();
  });

  it('renders create account button', () => {
    render(<RegisterForm onSuccess={vi.fn()} />);

    expect(screen.getByRole('button', { name: /create account/i })).toBeInTheDocument();
  });

  it('accepts user input', async () => {
    const user = userEvent.setup();
    render(<RegisterForm onSuccess={vi.fn()} />);

    const usernameInput = screen.getByLabelText(/username/i);
    const emailInput = screen.getByLabelText(/email/i);
    const passwordInput = screen.getByLabelText(/password/i, { selector: 'input' });

    await user.type(usernameInput, 'newuser');
    await user.type(emailInput, 'new@example.com');
    await user.type(passwordInput, 'password123');

    expect(usernameInput).toHaveValue('newuser');
    expect(emailInput).toHaveValue('new@example.com');
    expect(passwordInput).toHaveValue('password123');
  });

  it('shows sign in link', () => {
    render(<RegisterForm onSuccess={vi.fn()} />);

    const signInLink = screen.getByRole('link', { name: /sign in/i });
    expect(signInLink).toBeInTheDocument();
    expect(signInLink).toHaveAttribute('href', '/login');
  });

  it('shows the privacy policy link when the operator has configured one', () => {
    mockedUseBranding.mockReturnValue({
      data: { show_badge: true, privacy_url: 'https://operator.example.com/privacy' },
    } as ReturnType<typeof useBranding>);
    render(<RegisterForm onSuccess={vi.fn()} />);

    const privacyLink = screen.getByRole('link', { name: /privacy policy/i });
    expect(privacyLink).toHaveAttribute('href', 'https://operator.example.com/privacy');
  });

  it('hides the privacy policy link when no privacy URL is configured', () => {
    mockedUseBranding.mockReturnValue({
      data: { show_badge: true, privacy_url: null },
    } as ReturnType<typeof useBranding>);
    render(<RegisterForm onSuccess={vi.fn()} />);

    expect(screen.queryByRole('link', { name: /privacy policy/i })).not.toBeInTheDocument();
  });
});
