import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { LoginForm } from '../LoginForm';

const mockLogin = vi.fn().mockResolvedValue(undefined);
const mockNavigate = vi.fn();

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({
    login: mockLogin,
    logout: vi.fn(),
    token: null,
    user: null,
    isAdmin: false,
    isEditor: false,
  }),
}));

const mockLocationState: { from?: string } = {};

vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useLocation: () => ({
      pathname: '/login',
      search: '',
      hash: '',
      key: 'default',
      state: mockLocationState,
    }),
  };
});

describe('LoginForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLocationState.from = undefined;
    sessionStorage.clear();
  });

  it('renders username and password fields', () => {
    render(<LoginForm />);

    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText('Password', { exact: true })).toBeInTheDocument();
  });

  it('renders sign in button', () => {
    render(<LoginForm />);

    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('accepts user input in fields', async () => {
    const user = userEvent.setup();
    render(<LoginForm />);

    const usernameInput = screen.getByLabelText(/username/i);
    const passwordInput = screen.getByLabelText('Password', { exact: true });

    await user.type(usernameInput, 'admin');
    await user.type(passwordInput, 'secret');

    expect(usernameInput).toHaveValue('admin');
    expect(passwordInput).toHaveValue('secret');
  });

  it('shows loading state on submit', async () => {
    // Make login hang so we can observe loading state
    mockLogin.mockImplementation(() => new Promise(() => {}));
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText(/username/i), 'admin');
    await user.type(screen.getByLabelText('Password', { exact: true }), 'secret');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /signing in/i })).toBeInTheDocument();
    });
  });

  it('navigates to state.from after successful login', async () => {
    mockLogin.mockResolvedValue(undefined);
    mockLocationState.from = '/datasets/abc';
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText(/username/i), 'admin');
    await user.type(screen.getByLabelText('Password', { exact: true }), 'secret');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/datasets/abc', { replace: true });
    });
  });

  it('navigates to /search when no state.from is present', async () => {
    mockLogin.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText(/username/i), 'admin');
    await user.type(screen.getByLabelText('Password', { exact: true }), 'secret');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/search', { replace: true });
    });
  });

  it('ignores external URLs in state.from (security)', async () => {
    mockLogin.mockResolvedValue(undefined);
    mockLocationState.from = 'https://evil.com/steal';
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText(/username/i), 'admin');
    await user.type(screen.getByLabelText('Password', { exact: true }), 'secret');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/search', { replace: true });
    });
  });

  it('clears sessionStorage redirect after login', async () => {
    mockLogin.mockResolvedValue(undefined);
    sessionStorage.setItem('geolens-login-redirect', '/datasets/abc');
    mockLocationState.from = '/datasets/abc';
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText(/username/i), 'admin');
    await user.type(screen.getByLabelText('Password', { exact: true }), 'secret');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(sessionStorage.getItem('geolens-login-redirect')).toBeNull();
    });
  });
});
