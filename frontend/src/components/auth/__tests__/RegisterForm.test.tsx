import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { RegisterForm } from '../RegisterForm';

vi.mock('@/api/auth', () => ({
  registerUser: vi.fn().mockResolvedValue({ message: 'ok' }),
}));

describe('RegisterForm', () => {
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
});
